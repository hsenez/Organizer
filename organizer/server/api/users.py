"""Routes des comptes : profil, mot de passe, gestion par l'administrateur."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Response

from organizer.core.schemas import (
    AdminUserPatch,
    PasswordChange,
    ProfilePatch,
    UserCreateIn,
    UserOut,
    UserPublic,
)
from organizer.core.services.account import AccountService
from organizer.server.api.deps import get_account, get_admin, get_state, get_user
from organizer.server.state import AppState

router = APIRouter(prefix="/users", tags=["Utilisateurs"])


@router.get("", response_model=list[UserPublic])
def list_users(_: UserOut = Depends(get_user), state: AppState = Depends(get_state)):
    """Comptes actifs (pour le partage)."""
    return state.users.list_public()


@router.get("/all", response_model=list[UserOut])
def list_all(_: UserOut = Depends(get_admin), state: AppState = Depends(get_state)):
    return state.users.list()


@router.get("/me/prefs/{key}")
def get_pref(key: str, account: AccountService = Depends(get_account)):
    """Préférence d'affichage (JSON libre ; ``null`` si absente)."""
    return account.get_pref(key)


@router.put("/me/prefs/{key}", status_code=204)
def set_pref(key: str, value: Any = Body(default=None), account: AccountService = Depends(get_account)):
    account.set_pref(key, value)
    return Response(status_code=204)


@router.post("", response_model=UserOut, status_code=201)
def create_user(data: UserCreateIn, account: AccountService = Depends(get_account)):
    return account.create_user(data)


@router.patch("/me", response_model=UserOut)
def update_me(patch: ProfilePatch, account: AccountService = Depends(get_account)):
    return account.update_profile(patch)


@router.post("/me/password", status_code=204)
def change_password(change: PasswordChange, account: AccountService = Depends(get_account)):
    """Change le mot de passe et déconnecte les autres appareils."""
    account.change_password(change)
    return Response(status_code=204)


@router.patch("/{user_id}", response_model=UserOut)
def admin_update(user_id: int, patch: AdminUserPatch, account: AccountService = Depends(get_account)):
    """Activer / désactiver, donner / retirer les droits admin, réinitialiser le mot de passe.
    Désactiver un compte ou changer son mot de passe le déconnecte partout."""
    return account.admin_update(user_id, patch)
