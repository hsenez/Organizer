"""Compte de l'utilisateur connecté : profil, mot de passe, appareils connectés, comptes (admin).

Utilisé par l'API REST et par l'interface (via la DataSource), pour que les règles soient les mêmes :
changer son mot de passe déconnecte ses autres appareils ; désactiver un compte ou réinitialiser son mot de
passe le déconnecte partout. Les jetons de sauvegarde sont gérés par les administrateurs.
"""

from __future__ import annotations

from organizer.core.errors import Forbidden
from organizer.core.schemas import (
    AdminUserPatch,
    ApiKeyCreated,
    ApiKeyOut,
    PasswordChange,
    ProfilePatch,
    SessionOut,
    UserCreateIn,
    UserOut,
)
from organizer.core.services.auth import AuthService
from organizer.core.services.users import UserService


class AccountService:
    def __init__(self, users: UserService, auth: AuthService, user_id: int, session_id: int | None = None):
        self.users = users
        self.auth = auth
        self.user_id = user_id
        self.session_id = session_id

    def me(self) -> UserOut:
        return self.users.get(self.user_id)

    # --- profil ---

    def update_profile(self, patch: ProfilePatch) -> UserOut:
        return self.users.update_profile(self.user_id, patch)

    def change_password(self, change: PasswordChange) -> None:
        self.users.change_password(self.user_id, change)
        self.auth.revoke_all(self.user_id, except_session_id=self.session_id)

    # --- préférences d'affichage (filtres, tri…) ---

    def get_pref(self, key: str, default=None):
        return self.users.get_pref(self.user_id, key, default)

    def set_pref(self, key: str, value) -> None:
        self.users.set_pref(self.user_id, key, value)

    # --- appareils connectés ---

    def sessions(self) -> list[SessionOut]:
        return self.auth.list_sessions(self.user_id, current_id=self.session_id)

    def revoke_session(self, session_id: int) -> None:
        self.auth.revoke(self.user_id, session_id)

    def revoke_other_sessions(self) -> int:
        return self.auth.revoke_all(self.user_id, except_session_id=self.session_id)

    # --- administration ---

    def _admin(self):
        actor = self.users.actor_for(self.user_id)
        if not actor.is_admin:
            raise Forbidden("Réservé aux administrateurs.")
        return actor

    def all_users(self) -> list[UserOut]:
        self._admin()
        return self.users.list()

    def create_user(self, data: UserCreateIn) -> UserOut:
        return self.users.create_user(
            data.username, data.password, data.display_name, data.is_admin, by=self._admin()
        )

    def admin_update(self, user_id: int, patch: AdminUserPatch) -> UserOut:
        updated = self.users.admin_update(self._admin(), user_id, patch)
        if patch.is_active is False or patch.new_password:
            self.auth.revoke_all(user_id)
        return updated

    # --- jetons de sauvegarde (admin) ---

    def backup_keys(self) -> list[ApiKeyOut]:
        self._admin()
        return self.auth.list_api_keys("backup")

    def create_backup_key(self, label: str = "") -> ApiKeyCreated:
        """Nouveau jeton de sauvegarde : le secret n'est renvoyé qu'ici, une seule fois."""
        return self.auth.create_api_key(self._admin().id, "backup", label or "Sauvegarde")

    def revoke_backup_key(self, key_id: int) -> None:
        self._admin()
        self.auth.revoke_api_key(key_id, "backup")
