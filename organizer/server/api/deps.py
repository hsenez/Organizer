"""Dépendances FastAPI communes aux routes de l'API."""

from __future__ import annotations

from fastapi import HTTPException, Request

from organizer.core.events import ORIGIN_HEADER
from organizer.core.schemas import UserOut
from organizer.core.services import Services
from organizer.core.services.account import AccountService
from organizer.core.services.auth import ResolvedSession
from organizer.server.security import request_auth
from organizer.server.state import AppState


def get_state(request: Request) -> AppState:
    return request.app.state.organizer


def get_auth(request: Request) -> ResolvedSession:
    auth = request_auth(request)
    if auth is None:
        raise HTTPException(status_code=401, detail="Non connecté (ou session expirée).")
    return auth


def get_user(request: Request) -> UserOut:
    return get_auth(request).user


def get_admin(request: Request) -> UserOut:
    user = get_user(request)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Réservé aux administrateurs.")
    return user


def get_services(request: Request) -> Services:
    # L'en-tête d'origine permet au client bureau de ne pas se rafraîchir pour ses propres modifications.
    origin = request.headers.get(ORIGIN_HEADER) or None
    return get_state(request).services_for(get_user(request), origin=origin[:64] if origin else None)


def get_account(request: Request) -> AccountService:
    auth = get_auth(request)
    state = get_state(request)
    return AccountService(state.users, state.auth, auth.user.id, auth.session.id)
