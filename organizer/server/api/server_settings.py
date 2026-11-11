"""Réglages du serveur partagés par tous les comptes : adresse publique (liens à partager)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from organizer.core.services.account import AccountService
from organizer.server.api.deps import get_account

router = APIRouter(prefix="/server", tags=["Serveur"])


class PublicUrl(BaseModel):
    url: str | None = None


@router.get("/public-url", response_model=PublicUrl)
def get_public_url(account: AccountService = Depends(get_account)):
    """Adresse par laquelle on joint le serveur de partout (None : pas réglée)."""
    return PublicUrl(url=account.public_url())


@router.put("/public-url", response_model=PublicUrl)
def set_public_url(data: PublicUrl, account: AccountService = Depends(get_account)):
    """Règle l'adresse publique (administrateurs) ; vide = l'effacer."""
    return PublicUrl(url=account.set_public_url(data.url))
