"""Routes d'authentification de l'API (client bureau) et d'initialisation (premier compte)."""

from __future__ import annotations

import logging
import math

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from organizer import API_VERSION, __version__
from organizer.core.schemas import LoginIn, LoginOut, SessionOut, SetupIn, UserOut
from organizer.core.services.account import AccountService
from organizer.core.services.auth import ResolvedSession
from organizer.server.api.deps import get_account, get_auth, get_state
from organizer.server.security import client_ip
from organizer.server.state import AppState

log = logging.getLogger("organizer.auth")

router = APIRouter(tags=["Authentification"])


class VersionOut(BaseModel):
    version: str  # version du logiciel (MAJEUR.MINEUR.CORRECTIF)
    api: int  # compatibilité client / serveur


class SetupStatus(BaseModel):
    needs_setup: bool


@router.get("/version", response_model=VersionOut)
def version():
    """Version du serveur (sans connexion) : le client bureau la compare à la sienne."""
    return VersionOut(version=__version__, api=API_VERSION)


@router.get("/setup", response_model=SetupStatus)
def setup_status(state: AppState = Depends(get_state)):
    """Vrai tant qu'aucun compte n'existe (il faut créer l'administrateur)."""
    return SetupStatus(needs_setup=state.users.count() == 0)


@router.post("/setup", response_model=LoginOut, status_code=201)
def setup(data: SetupIn, request: Request, state: AppState = Depends(get_state)):
    """Crée le premier compte (administrateur) et renvoie un jeton de connexion."""
    if state.users.count() > 0:
        raise HTTPException(status_code=409, detail="L'application est déjà initialisée.")
    user = state.users.create_user(data.username, data.password, data.display_name)
    token, session = state.auth.create_session(user.id, kind="api", label=_device(request, ""))
    return LoginOut(token=token, user=user, session=session)


@router.post("/auth/login", response_model=LoginOut)
def login(data: LoginIn, request: Request, state: AppState = Depends(get_state)):
    """Connexion du client bureau : renvoie un jeton à passer en ``Authorization: Bearer <jeton>``."""
    user = check_credentials(state, client_ip(request), data.username, data.password)
    token, session = state.auth.create_session(user.id, kind="api", label=_device(request, data.device_name))
    return LoginOut(token=token, user=user, session=session)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, auth: ResolvedSession = Depends(get_auth), state: AppState = Depends(get_state)):
    state.auth.revoke_token(request.state.auth_token)
    return Response(status_code=204)


@router.get("/auth/me", response_model=UserOut)
def me(auth: ResolvedSession = Depends(get_auth)):
    return auth.user


@router.get("/auth/sessions", response_model=list[SessionOut])
def sessions(account: AccountService = Depends(get_account)):
    """Appareils connectés."""
    return account.sessions()


@router.delete("/auth/sessions/{session_id}", status_code=204)
def revoke_session(session_id: int, account: AccountService = Depends(get_account)):
    account.revoke_session(session_id)
    return Response(status_code=204)


@router.post("/auth/sessions/revoke-others", status_code=204)
def revoke_others(account: AccountService = Depends(get_account)):
    """Déconnecte tous les autres appareils."""
    account.revoke_other_sessions()
    return Response(status_code=204)


# --- utilitaires partagés avec les pages web -------------------------------------------------------------


_BLOCK_REASONS = {
    "ip": ("trop d'échecs depuis cette adresse", "Trop de tentatives. Réessayez dans {} min."),
    "account": (
        "trop d'échecs sur ce compte, toutes adresses confondues",
        "Trop de tentatives sur ce compte. Réessayez dans {} min.",
    ),
}


def check_credentials(state: AppState, ip: str, username: str, password: str) -> UserOut:
    """Vérifie identifiant / mot de passe avec protection anti force brute ; lève HTTPException sinon.

    Chaque tentative est écrite dans le journal du serveur (``journalctl -u organizer``).
    """
    shown = username[:80]  # %r ci-dessous : guillemets, retours à la ligne neutralisés
    block = state.throttle.block(ip, username)
    if block is not None:
        minutes = math.ceil(block.seconds / 60)
        reason, message = _BLOCK_REASONS[block.scope]
        log.warning(
            "Connexion refusée (%s) : identifiant %r depuis %s, encore %d min", reason, shown, ip, minutes
        )
        raise HTTPException(status_code=429, detail=message.format(minutes))
    user = state.users.authenticate(username, password)
    if user is None:
        state.throttle.failure(ip, username)
        log.warning("Échec de connexion : identifiant %r depuis %s", shown, ip)
        now_blocked = state.throttle.block(ip, username)
        if now_blocked is not None:
            log.warning(
                "Blocage pendant %d min (%s) : identifiant %r",
                math.ceil(now_blocked.seconds / 60),
                _BLOCK_REASONS[now_blocked.scope][0],
                shown,
            )
        raise HTTPException(status_code=401, detail="Identifiant ou mot de passe incorrect.")
    state.throttle.success(ip, username)
    log.info("Connexion de %r depuis %s", user.username, ip)
    return user


def _device(request: Request, name: str) -> str:
    return name.strip() or request.headers.get("user-agent", "")[:200]
