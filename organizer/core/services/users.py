"""Comptes utilisateurs (création, mots de passe, préférences).

Ces opérations ne passent pas par l'historique annuler / rétablir et n'ont pas besoin d'utilisateur courant :
elles prennent directement le moteur de base de données.
"""

from __future__ import annotations

import json
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import Engine, func
from sqlmodel import Session, select

from organizer.core.errors import Forbidden, InvalidOperation, NotFound
from organizer.core.models import User, UserPref, utcnow
from organizer.core.schemas import AdminUserPatch, PasswordChange, ProfilePatch, UserOut, UserPublic
from organizer.core.services.base import Actor

_hasher = PasswordHasher()

# Minimum pour tout nouveau mot de passe (accès possible depuis Internet). Un compte dont le mot de passe
# date d'avant (plus court) fonctionne toujours, mais un bandeau invite à le changer (WEAK_PASSWORD_PREF).
MIN_PASSWORD_LENGTH = 12
# Préférence posée à la connexion quand le mot de passe tapé est plus court que le minimum (le serveur ne
# peut le mesurer qu'à ce moment-là : la base ne garde que son empreinte) ; retirée quand il change.
WEAK_PASSWORD_PREF = "security:weak_password"


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise InvalidOperation(f"Le mot de passe doit faire au moins {MIN_PASSWORD_LENGTH} caractères.")


def _mark_weak_password(s: Session, user_id: int, weak: bool) -> None:
    """Pose ou retire :data:`WEAK_PASSWORD_PREF` (sans écriture si rien ne change)."""
    row = s.get(UserPref, (user_id, WEAK_PASSWORD_PREF))
    if weak and row is None:
        s.add(UserPref(user_id=user_id, key=WEAK_PASSWORD_PREF, value="true"))
    elif not weak and row is not None:
        s.delete(row)


class UserService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def count(self) -> int:
        with Session(self.engine) as s:
            return s.exec(select(func.count()).select_from(User)).one()

    def create_user(
        self,
        username: str,
        password: str,
        display_name: str = "",
        is_admin: bool = False,
        *,
        by: Actor | None = None,
    ) -> UserOut:
        """Crée un compte. Le tout premier compte est créé sans ``by`` et devient admin ; ensuite seul un
        admin peut créer des comptes."""
        username = username.strip()
        if not username:
            raise InvalidOperation("L'identifiant est obligatoire.")
        _check_password(password)
        with Session(self.engine) as s:
            first = s.exec(select(func.count()).select_from(User)).one() == 0
            if not first and (by is None or not by.is_admin):
                raise Forbidden("Seul un administrateur peut créer des comptes.")
            if s.exec(select(User).where(func.lower(User.username) == username.lower())).first():
                raise InvalidOperation(f"L'identifiant « {username} » est déjà pris.")
            user = User(
                username=username,
                display_name=display_name.strip() or username,
                password_hash=_hasher.hash(password),
                is_admin=is_admin or first,
            )
            s.add(user)
            s.commit()
            s.refresh(user)
            return UserOut.model_validate(user)

    def authenticate(self, username: str, password: str) -> UserOut | None:
        with Session(self.engine) as s:
            user = s.exec(select(User).where(func.lower(User.username) == username.strip().lower())).first()
            if user is None or not user.is_active:
                return None
            try:
                _hasher.verify(user.password_hash, password)
            except (VerificationError, InvalidHashError):
                return None
            if _hasher.check_needs_rehash(user.password_hash):
                user.password_hash = _hasher.hash(password)
                s.add(user)
            _mark_weak_password(s, user.id, len(password) < MIN_PASSWORD_LENGTH)
            s.commit()
            s.refresh(user)
            return UserOut.model_validate(user)

    def get(self, user_id: int) -> UserOut:
        with Session(self.engine) as s:
            user = s.get(User, user_id)
            if user is None:
                raise NotFound("Utilisateur introuvable.")
            return UserOut.model_validate(user)

    def list(self) -> list[UserOut]:
        with Session(self.engine) as s:
            return [UserOut.model_validate(u) for u in s.exec(select(User).order_by(User.display_name)).all()]

    def actor_for(self, user_id: int) -> Actor:
        user = self.get(user_id)
        return Actor(id=user.id, is_admin=user.is_admin, reminder_offset_days=user.reminder_offset_days)

    # --- préférences d'affichage ---

    def get_pref(self, user_id: int, key: str, default: Any = None) -> Any:
        with Session(self.engine) as s:
            row = s.get(UserPref, (user_id, key))
            return json.loads(row.value) if row is not None else default

    def set_pref(self, user_id: int, key: str, value: Any) -> None:
        with Session(self.engine) as s:
            row = s.get(UserPref, (user_id, key)) or UserPref(user_id=user_id, key=key, value="null")
            row.value = json.dumps(value, ensure_ascii=False)
            row.updated_at = utcnow()
            s.add(row)
            s.commit()

    def list_public(self) -> list[UserPublic]:
        """Comptes actifs, pour choisir avec qui partager."""
        with Session(self.engine) as s:
            users = s.exec(select(User).where(User.is_active == True).order_by(User.display_name)).all()  # noqa: E712
            return [UserPublic.model_validate(u) for u in users]

    def update_profile(self, user_id: int, patch: ProfilePatch) -> UserOut:
        with Session(self.engine) as s:
            user = s.get(User, user_id)
            if user is None:
                raise NotFound("Utilisateur introuvable.")
            for key, value in patch.model_dump(exclude_unset=True).items():
                if value is not None:
                    setattr(user, key, value.strip() if isinstance(value, str) else value)
            s.add(user)
            s.commit()
            s.refresh(user)
            return UserOut.model_validate(user)

    def change_password(self, user_id: int, change: PasswordChange) -> None:
        _check_password(change.new_password)
        with Session(self.engine) as s:
            user = s.get(User, user_id)
            if user is None:
                raise NotFound("Utilisateur introuvable.")
            try:
                _hasher.verify(user.password_hash, change.old_password)
            except (VerificationError, InvalidHashError):
                raise InvalidOperation("L'ancien mot de passe est incorrect.") from None
            user.password_hash = _hasher.hash(change.new_password)
            s.add(user)
            _mark_weak_password(s, user.id, False)
            s.commit()

    def admin_update(self, by: Actor, user_id: int, patch: AdminUserPatch) -> UserOut:
        """Activation, droits admin, réinitialisation du mot de passe (réservé aux admins)."""
        if not by.is_admin:
            raise Forbidden("Réservé aux administrateurs.")
        fields = patch.model_dump(exclude_unset=True)
        if user_id == by.id and ("is_active" in fields or "is_admin" in fields):
            raise InvalidOperation(
                "Vous ne pouvez pas modifier vos propres droits ou désactiver votre compte."
            )
        with Session(self.engine) as s:
            user = s.get(User, user_id)
            if user is None:
                raise NotFound("Utilisateur introuvable.")
            if fields.get("is_active") is not None:
                user.is_active = fields["is_active"]
            if fields.get("is_admin") is not None:
                user.is_admin = fields["is_admin"]
            if fields.get("new_password"):
                _check_password(fields["new_password"])
                user.password_hash = _hasher.hash(fields["new_password"])
                _mark_weak_password(s, user.id, False)
            s.add(user)
            s.commit()
            s.refresh(user)
            return UserOut.model_validate(user)
