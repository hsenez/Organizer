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


class MuteIn(BaseModel):
    muted: bool


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(after: int | None = None, sv: Services = Depends(get_services)):
    """Les plus récentes d'abord ; ``after`` : seulement les non lues de numéro supérieur."""
    return sv.notifications.list(after=after)


@router.get("/notifications/mute/{item_type}/{item_id}", response_model=bool)
def is_muted(item_type: str, item_id: int, sv: Services = Depends(get_services)):
    """Les notifications de cet élément sont-elles coupées pour moi ?"""
    return sv.notifications.muted(item_type, item_id)


@router.put("/notifications/mute/{item_type}/{item_id}", response_model=bool)
def set_muted(item_type: str, item_id: int, data: MuteIn, sv: Services = Depends(get_services)):
    """Coupe ou rétablit les notifications de cet élément pour moi (annulable)."""
    return sv.notifications.set_muted(item_type, item_id, data.muted)


@router.get("/notifications/unread-count", response_model=int)
def unread_count(sv: Services = Depends(get_services)):
    return sv.notifications.unread_count()


@router.get("/notifications/conflict-target/{item_type}/{item_id}", response_model=int | None)
def conflict_target(item_type: str, item_id: int, sv: Services = Depends(get_services)):
    """Tag / projet public en conflit de nom avec mon tag / projet privé ``item_id`` (null : plus de
    conflit)."""
    return sv.notifications.conflict_target(item_type, item_id)


@router.post("/notifications/read", response_model=int)
def mark_read(data: ReadIn, sv: Services = Depends(get_services)):
    """Marque comme lues (toutes sans ``ids``) ; renvoie le nombre de non lues restantes."""
    return sv.notifications.mark_read(data.ids)
