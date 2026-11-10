"""Routes des notifications de l'utilisateur connecté (ce que d'autres ont fait qui le concerne)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from organizer.core.schemas import NotificationOut
from organizer.core.services import Services
from organizer.server.api.deps import get_services

router = APIRouter(tags=["Notifications"])


class ReadIn(BaseModel):
    ids: list[int] | None = None  # None : toutes


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(sv: Services = Depends(get_services)):
    """Les plus récentes d'abord."""
    return sv.notifications.list()


@router.get("/notifications/unread-count", response_model=int)
def unread_count(sv: Services = Depends(get_services)):
    return sv.notifications.unread_count()


@router.post("/notifications/read", response_model=int)
def mark_read(data: ReadIn, sv: Services = Depends(get_services)):
    """Marque comme lues (toutes sans ``ids``) ; renvoie le nombre de non lues restantes."""
    return sv.notifications.mark_read(data.ids)
