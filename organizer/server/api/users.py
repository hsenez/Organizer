"""Routes des comptes : profil, mot de passe, gestion par l'administrateur."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from organizer.core.schemas import (
    AdminUserPatch,
    PasswordChange,
    ProfilePatch,
    UserCreateIn,
    UserOut,
    UserPublic,
)
from organizer.core.services.auth import ResolvedSession
from organizer.server.api.deps import get_admin, get_auth, get_state, get_user
from organizer.server.state import AppState

router = APIRouter(prefix="/users", tags=["Utilisateurs"])


@router.get("", response_model=list[UserPublic])
def list_users(_: UserOut = Depends(get_user), state: AppState = Depends(get_state)):
    """Comptes actifs (pour le partage)."""
    return state.users.list_public()


@router.get("/all", response_model=list[UserOut])
def list_all(_: UserOut = Depends(get_admin), state: AppState = Depends(get_state)):
    return state.users.list()


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    data: UserCreateIn, admin: UserOut = Depends(get_admin), state: AppState = Depends(get_state)
):
    return state.users.create_user(
        data.username, data.password, data.display_name, data.is_admin, by=state.users.actor_for(admin.id)
    )


@router.patch("/me", response_model=UserOut)
def update_me(patch: ProfilePatch, user: UserOut = Depends(get_user), state: AppState = Depends(get_state)):
    return state.users.update_profile(user.id, patch)


@router.post("/me/password", status_code=204)
def change_password(
    change: PasswordChange, auth: ResolvedSession = Depends(get_auth), state: AppState = Depends(get_state)
):
    """Change le mot de passe et déconnecte les autres appareils."""
    state.users.change_password(auth.user.id, change)
    state.auth.revoke_all(auth.user.id, except_session_id=auth.session.id)
    return Response(status_code=204)


@router.patch("/{user_id}", response_model=UserOut)
def admin_update(
    user_id: int,
    patch: AdminUserPatch,
    admin: UserOut = Depends(get_admin),
    state: AppState = Depends(get_state),
):
    """Activer / désactiver, donner / retirer les droits admin, réinitialiser le mot de passe.
    Désactiver un compte ou changer son mot de passe le déconnecte partout."""
    updated = state.users.admin_update(state.users.actor_for(admin.id), user_id, patch)
    if patch.is_active is False or patch.new_password:
        state.auth.revoke_all(user_id)
    return updated
