"""Accès direct par le réseau local (client bureau) : voir :mod:`organizer.server.local_access`."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request

from organizer.core.schemas import LocalAccessOut, UserOut
from organizer.server import local_access
from organizer.server.api.deps import get_state, get_user
from organizer.server.security import client_ip, is_local_address
from organizer.server.state import AppState

router = APIRouter(prefix="/local-access", tags=["Réseau local"])
NONCE = re.compile(r"^[0-9a-f]{16,128}$")


@router.get("", response_model=LocalAccessOut)
def local_access_info(user: UserOut = Depends(get_user), state: AppState = Depends(get_state)):
    """Adresses du serveur sur le réseau local et clé du compte (à garder secrète, comme le jeton)."""
    return LocalAccessOut(
        urls=local_access.local_urls(state.settings),
        key=local_access.user_key(state.local_key, user.id),
        user_id=user.id,
    )


@router.get("/proof")
def local_access_proof(user: int, nonce: str, request: Request, state: AppState = Depends(get_state)):
    """Preuve d'identité du serveur pour le compte ``user`` et le nombre ``nonce`` (hexadécimal) tiré par
    le client. Réservée aux machines du réseau local : sinon un faux serveur pourrait la faire calculer par
    le vrai, à travers Internet, et la présenter comme la sienne."""
    if not is_local_address(client_ip(request)):
        raise HTTPException(status_code=403, detail="Réservé aux machines du réseau local.")
    if not NONCE.match(nonce):
        raise HTTPException(status_code=422, detail="Nombre aléatoire invalide.")
    return {"proof": local_access.proof(local_access.user_key(state.local_key, user), nonce)}
