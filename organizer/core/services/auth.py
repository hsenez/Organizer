"""Sessions de connexion : cookies du navigateur et jetons du client bureau.

- Le jeton est un secret aléatoire (256 bits) ; seule son empreinte SHA-256 est stockée.
- Les sessions sont **glissantes** : chaque utilisation (au plus toutes les 10 minutes) repousse l'expiration.
- Connexion d'un utilisateur désactivé ou session expirée → refusée.

Jetons d'accès limités (:class:`ApiKey`, ex. sauvegarde) : jamais acceptés comme session, seulement par la
route de leur portée (:meth:`AuthService.resolve_api_key`).
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
from organizer.core.models import ApiKey, AuthSession, User, utcnow
from organizer.core.schemas import ApiKeyCreated, ApiKeyOut, SessionOut, UserOut

RENEW_EVERY = timedelta(minutes=10)
# Préfixe des jetons d'accès limités : les reconnaître d'un coup d'œil (et dans un outil de détection de
# secrets).
API_KEY_PREFIX = {"backup": "orgbk_"}


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

    # --- jetons d'accès limités (sauvegarde) ---

    def create_api_key(self, user_id: int, scope: str = "backup", label: str = "") -> ApiKeyCreated:
        """Crée un jeton de portée ``scope`` ; renvoie le secret, à transmettre une seule fois."""
        token = API_KEY_PREFIX[scope] + secrets.token_urlsafe(32)
        with Session(self.engine) as s:
            row = ApiKey(
                user_id=user_id, token_hash=hash_token(token), scope=scope, label=label.strip()[:100]
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            return ApiKeyCreated(token=token, key=ApiKeyOut.model_validate(row))

    def list_api_keys(self, scope: str = "backup") -> list[ApiKeyOut]:
        with Session(self.engine) as s:
            rows = s.exec(select(ApiKey).where(ApiKey.scope == scope).order_by(ApiKey.created_at)).all()
            return [ApiKeyOut.model_validate(r) for r in rows]

    def revoke_api_key(self, key_id: int, scope: str = "backup") -> None:
        with Session(self.engine) as s:
            row = s.get(ApiKey, key_id)
            if row is None or row.scope != scope:
                raise NotFound("Jeton introuvable.")
            s.delete(row)
            s.commit()

    def resolve_api_key(self, token: str | None, scope: str, ip: str = "") -> ApiKeyOut | None:
        """Jeton valide pour ``scope`` (son créateur est toujours un administrateur actif), ou None.
        Note la date et l'adresse de cette utilisation."""
        if not token or not token.startswith(API_KEY_PREFIX[scope]):
            return None
        with Session(self.engine) as s:
            row = s.exec(select(ApiKey).where(ApiKey.token_hash == hash_token(token))).first()
            if row is None or row.scope != scope:
                return None
            creator = s.get(User, row.user_id)
            if creator is None or not creator.is_active or not creator.is_admin:
                return None
            row.last_used_at = utcnow()
            row.last_used_ip = ip[:64]
            s.add(row)
            s.commit()
            s.refresh(row)
            return ApiKeyOut.model_validate(row)

    def purge_expired(self) -> int:
        with Session(self.engine) as s:
            result = s.exec(delete(AuthSession).where(AuthSession.expires_at <= utcnow()))
            s.commit()
            return result.rowcount or 0


@dataclass(frozen=True)
class LoginBlock:
    """Blocage en cours : secondes restantes et portée (``"ip"`` : ce visiteur ; ``"account"`` : compte)."""

    seconds: float
    scope: str


class LoginThrottle:
    """Anti force brute en mémoire, à deux niveaux.

    - Par couple (adresse IP, identifiant) : peu d'échecs tolérés (5 en 10 min par défaut). Une connexion
      réussie remet ce compteur à zéro.
    - Par identifiant, **toutes adresses confondues** (20 en 1 h par défaut) : arrête un attaquant qui change
      d'adresse à chaque essai. Une connexion réussie ne le remet **pas** à zéro (sinon l'attaquant n'aurait
      qu'à attendre que le propriétaire se connecte). Un compte bloqué refuse seulement les **nouvelles**
      connexions : les appareils déjà connectés le restent. ``account_max_failures=0`` : niveau désactivé.

    Les compteurs portent sur l'identifiant tapé, qu'il existe ou non : la réponse ne révèle donc pas
    l'existence d'un compte.
    """

    MAX_KEYS = 10_000  # au-delà, ménage des entrées expirées (identifiants inventés en masse)

    def __init__(
        self,
        max_failures: int,
        window_seconds: float,
        account_max_failures: int = 0,
        account_window_seconds: float = 0.0,
        clock=time.monotonic,
    ):
        self.max_failures = max_failures
        self.window = window_seconds
        self.account_max_failures = account_max_failures
        self.account_window = account_window_seconds
        self.clock = clock
        self._failures: dict[tuple[str, ...], list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    @staticmethod
    def _name(username: str) -> str:
        return username.strip().lower()

    def _keys(self, ip: str, username: str) -> list[tuple[tuple[str, ...], int, float]]:
        """(clé, échecs tolérés, fenêtre) de chaque niveau actif."""
        name = self._name(username)
        levels = [(("ip", ip, name), self.max_failures, self.window)]
        if self.account_max_failures > 0:
            levels.append((("account", name), self.account_max_failures, self.account_window))
        return levels

    def _recent(self, key: tuple[str, ...], window: float) -> list[float]:
        cutoff = self.clock() - window
        recent = [t for t in self._failures.get(key, []) if t > cutoff]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def block(self, ip: str, username: str) -> LoginBlock | None:
        """Blocage en cours pour cette tentative (le plus long des deux niveaux), ou None."""
        with self._lock:
            found: LoginBlock | None = None
            for key, limit, window in self._keys(ip, username):
                recent = self._recent(key, window)
                if len(recent) >= limit:
                    # Libéré quand le plus ancien des ``limit`` derniers échecs sort de la fenêtre.
                    wait = max(0.0, recent[-limit] + window - self.clock())
                    if found is None or wait > found.seconds:
                        found = LoginBlock(wait, key[0])
            return found

    def retry_after(self, ip: str, username: str) -> float:
        """Secondes à attendre avant de pouvoir réessayer (0 = autorisé)."""
        found = self.block(ip, username)
        return found.seconds if found else 0.0

    def failure(self, ip: str, username: str) -> None:
        with self._lock:
            if len(self._failures) > self.MAX_KEYS:
                self._purge()
            for key, _limit, window in self._keys(ip, username):
                self._recent(key, window)
                self._failures[key].append(self.clock())

    def success(self, ip: str, username: str) -> None:
        """Remet à zéro le compteur de ce visiteur (pas celui du compte)."""
        with self._lock:
            self._failures.pop(("ip", ip, self._name(username)), None)

    def _purge(self) -> None:
        for key in list(self._failures):
            self._recent(key, self.window if key[0] == "ip" else self.account_window)
