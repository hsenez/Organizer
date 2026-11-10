"""Routes des événements du calendrier (``/agenda`` : ``/events`` est le flux temps réel), de leurs liens,
partages et pièces jointes, et de la conversion tâche ↔ événement."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Response, UploadFile
from pydantic import BaseModel

from organizer.core.schemas import (
    EventCreate,
    EventFilter,
    EventOut,
    EventPatch,
    EventTimes,
    LinkIn,
    LinkOut,
    LinkPatch,
    ShareSpec,
    TaskOut,
)
from organizer.core.services import Services
from organizer.server.api.deps import get_services

router = APIRouter(tags=["Événements"])


class EventSharesIn(BaseModel):
    shares: list[ShareSpec]


@router.post("/agenda/query", response_model=list[EventOut])
def query_events(flt: EventFilter, sv: Services = Depends(get_services)):
    """Événements visibles qui touchent la période ``[start, end]``, filtrés comme dans le calendrier."""
    return sv.agenda.list(flt)


@router.post("/agenda", response_model=EventOut, status_code=201)
def create_event(data: EventCreate, sv: Services = Depends(get_services)):
    return sv.agenda.create(data)


@router.get("/agenda/{event_id}", response_model=EventOut)
def get_event(event_id: int, sv: Services = Depends(get_services)):
    return sv.agenda.get(event_id)


@router.patch("/agenda/{event_id}", response_model=EventOut)
def update_event(event_id: int, patch: EventPatch, sv: Services = Depends(get_services)):
    """Seuls les champs présents dans le JSON sont modifiés (``start_time: null`` = toute la journée)."""
    return sv.agenda.update(event_id, patch)


@router.delete("/agenda/{event_id}", status_code=204)
def delete_event(event_id: int, sv: Services = Depends(get_services)):
    sv.agenda.delete(event_id)
    return Response(status_code=204)


@router.put("/agenda/{event_id}/shares", response_model=EventOut)
def set_event_shares(event_id: int, data: EventSharesIn, sv: Services = Depends(get_services)):
    """Avec qui l'événement est partagé, et si chacun peut le modifier (propriétaire seulement)."""
    return sv.agenda.set_shares(event_id, data.shares)


@router.post("/agenda/{event_id}/links", response_model=LinkOut, status_code=201)
def add_event_link(event_id: int, data: LinkIn, sv: Services = Depends(get_services)):
    return sv.agenda.add_link(event_id, data)


@router.patch("/agenda-links/{link_id}", response_model=LinkOut)
def update_event_link(link_id: int, patch: LinkPatch, sv: Services = Depends(get_services)):
    return sv.agenda.update_link(link_id, patch)


@router.delete("/agenda-links/{link_id}", status_code=204)
def remove_event_link(link_id: int, sv: Services = Depends(get_services)):
    sv.agenda.remove_link(link_id)
    return Response(status_code=204)


@router.post("/agenda/{event_id}/attachments", response_model=LinkOut, status_code=201)
def upload_event_attachment(
    event_id: int, file: UploadFile = File(...), sv: Services = Depends(get_services)
):
    """Envoie un fichier et l'ajoute aux liens de l'événement."""
    return sv.attachments.upload_event(event_id, file.filename or "fichier", file.file, file.content_type)


@router.post("/agenda/{event_id}/to-task", response_model=TaskOut, status_code=201)
def event_to_task(event_id: int, sv: Services = Depends(get_services)):
    """Transforme l'événement en tâche (échéance = début)."""
    return sv.agenda.to_task(event_id)


@router.post("/tasks/{task_id}/to-event", response_model=EventOut, status_code=201)
def task_to_event(task_id: int, times: EventTimes | None = None, sv: Services = Depends(get_services)):
    """Transforme la tâche en événement (sans corps : il commence à l'échéance et dure une heure)."""
    return sv.agenda.from_task(task_id, times)
