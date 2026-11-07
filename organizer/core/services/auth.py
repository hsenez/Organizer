"""Sessions de connexion : cookies du navigateur et jetons du client bureau.

- Le jeton est un secret aléatoire (256 bits) ; seule son empreinte SHA-256 est stockée.
- Les sessions sont **glissantes** : chaque utilisation (au plus toutes les 10 minutes) repousse l'expiration.
- Connexion d'un utilisateur désactivé ou session expirée → refusée.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import Engine, delete
from sqlmodel import Session, select

from organizer.config import Settings
from organizer.core.errors import Forbidden, NotFound
from organizer.core.models import AuthSession, User, utcnow
from organizer.core.schemas import SessionOut, UserOut

RENEW_EVERY = timedelta(minutes=10)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class ResolvedSession:
    user: UserOut
    session: SessionOut
    renewed: bool  # l'expiration vient d'être repoussée (le cookie peut être réémis)


class AuthService:
    def __init__(self, engine: Engine, settings: Settings):
        self.engine = engine
        self.settings = settings

    def _duration(self, kind: str, persistent: bool) -> timedelta:
        if kind == "api":
            return timedelta(days=self.settings.api_token_days)
        if persistent:
            return timedelta(days=self.settings.remember_me_days)
        return timedelta(hours=self.settings.web_session_hours)

    def create_session(
        self, user_id: int, kind: str = "web", persistent: bool = False, label: str = ""
    ) -> tuple[str, SessionOut]:
        """Ouvre une session ; renvoie le jeton (à transmettre une seule fois) et sa description."""
        token = secrets.token_urlsafe(32)
        now = utcnow()
        with Session(self.engine) as s:
            user = s.get(User, user_id)
            if user is None or not user.is_active:
                raise Forbidden("Compte inexistant ou désactivé.")
            row = AuthSession(
                user_id=user_id,
                token_hash=hash_token(token),
                kind=kind,
                persistent=persistent or kind == "api",
                label=label[:200],
                created_at=now,
                last_seen_at=now,
                expires_at=now + self._duration(kind, persistent),
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            return token, SessionOut.model_validate(row).model_copy(update={"current": True})

    def resolve(self, token: str | None) -> ResolvedSession | None:
        """Utilisateur correspondant au jeton, ou None (jeton inconnu, expiré, compte désactivé)."""
        if not token:
            return None
        now = utcnow()
        with Session(self.engine) as s:
            row = s.exec(select(AuthSession).where(AuthSession.token_hash == hash_token(token))).first()
            if row is None:
                return None
            if row.expires_at <= now:
                s.delete(row)
                s.commit()
                return None
            user = s.get(User, row.user_id)
            if user is None or not user.is_active:
                return None
            renewed = False
            if now - row.last_seen_at >= RENEW_EVERY:
                row.last_seen_at = now
                row.expires_at = now + self._duration(row.kind, row.persistent)
                s.add(row)
                s.commit()
                s.refresh(row)
                s.refresh(user)
                renewed = True
            return ResolvedSession(
                user=UserOut.model_validate(user),
                session=SessionOut.model_validate(row).model_copy(update={"current": True}),
                renewed=renewed,
            )

    def revoke_token(self, token: str) -> None:
        with Session(self.engine) as s:
            s.exec(delete(AuthSession).where(AuthSession.token_hash == hash_token(token)))
            s.commit()

    def list_sessions(self, user_id: int, current_id: int | None = None) -> list[SessionOut]:
        with Session(self.engine) as s:
            rows = s.exec(
                select(AuthSession)
                .where(AuthSession.user_id == user_id, AuthSession.expires_at > utcnow())
                .order_by(AuthSession.last_seen_at.desc())
            ).all()
            return [
                SessionOut.model_validate(r).model_copy(update={"current": r.id == current_id}) for r in rows
            ]

    def revoke(self, user_id: int, session_id: int) -> None:
        """Déconnecte un appareil (uniquement parmi ses propres sessions)."""
        with Session(self.engine) as s:
            row = s.get(AuthSession, session_id)
            if row is None or row.user_id != user_id:
                raise NotFound("Session introuvable.")
            s.delete(row)
            s.commit()

    def revoke_all(self, user_id: int, except_session_id: int | None = None) -> int:
        with Session(self.engine) as s:
            query = delete(AuthSession).where(AuthSession.user_id == user_id)
            if except_session_id is not None:
                query = query.where(AuthSession.id != except_session_id)
            result = s.exec(query)
            s.commit()
            return result.rowcount or 0

    def purge_expired(self) -> int:
        with Session(self.engine) as s:
            result = s.exec(delete(AuthSession).where(AuthSession.expires_at <= utcnow()))
            s.commit()
            return result.rowcount or 0


class LoginThrottle:
    """Anti force brute en mémoire : trop d'échecs pour un couple (IP, identifiant) → blocage temporaire."""

    def __init__(self, max_failures: int, window_seconds: float, clock=time.monotonic):
        self.max_failures = max_failures
        self.window = window_seconds
        self.clock = clock
        self._failures: dict[tuple[str, str], list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def _key(self, ip: str, username: str) -> tuple[str, str]:
        return ip, username.strip().lower()

    def _recent(self, key: tuple[str, str]) -> list[float]:
        cutoff = self.clock() - self.window
        recent = [t for t in self._failures.get(key, []) if t > cutoff]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def retry_after(self, ip: str, username: str) -> float:
        """Secondes à attendre avant de pouvoir réessayer (0 = autorisé)."""
        with self._lock:
            recent = self._recent(self._key(ip, username))
            if len(recent) < self.max_failures:
                return 0.0
            return max(0.0, recent[0] + self.window - self.clock())

    def failure(self, ip: str, username: str) -> None:
        with self._lock:
            key = self._key(ip, username)
            self._recent(key)
            self._failures[key].append(self.clock())

    def success(self, ip: str, username: str) -> None:
        with self._lock:
            self._failures.pop(self._key(ip, username), None)
