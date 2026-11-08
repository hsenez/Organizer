"""Routes des tâches, sous-tâches, liens, partages et pièces jointes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from organizer.core.schemas import (
    LinkIn,
    LinkOut,
    LinkPatch,
    TaskCreate,
    TaskFilter,
    TaskOut,
    TaskPatch,
    TaskSort,
)
from organizer.core.services import Services
from organizer.server.api.deps import get_services

router = APIRouter(tags=["Tâches"])

# Types affichables directement dans le navigateur ; tout le reste est proposé en téléchargement
# (un fichier HTML ou SVG envoyé par quelqu'un ne doit jamais s'exécuter dans la page).
_INLINE_TYPES = {
    "application/pdf",
    "text/plain",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "audio/mpeg",
    "video/mp4",
}


class TaskQuery(BaseModel):
    filter: TaskFilter = Field(default_factory=TaskFilter)
    sort: TaskSort = Field(default_factory=TaskSort)


class AttachIn(BaseModel):
    parent_id: int


class IdsIn(BaseModel):
    ids: list[int]


class MoveIn(BaseModel):
    patch: TaskPatch | None = None
    order: list[int] | None = None


class SharesIn(BaseModel):
    user_ids: list[int]


@router.post("/tasks/query", response_model=list[TaskOut])
def query_tasks(query: TaskQuery, sv: Services = Depends(get_services)):
    """Liste filtrée et triée (même critères que la barre de filtres)."""
    return sv.tasks.list(query.filter, query.sort)


@router.get("/tasks/reminders", response_model=list[TaskOut])
def reminders(sv: Services = Depends(get_services)):
    """Suivis dont la date de rappel est atteinte."""
    return sv.tasks.reminders_due()


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(data: TaskCreate, sv: Services = Depends(get_services)):
    return sv.tasks.create(data)


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: int, sv: Services = Depends(get_services)):
    return sv.tasks.get(task_id)


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: int, patch: TaskPatch, sv: Services = Depends(get_services)):
    """Seuls les champs présents dans le JSON sont modifiés (``null`` efface un champ facultatif)."""
    return sv.tasks.update(task_id, patch)


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, with_subtasks: bool = False, sv: Services = Depends(get_services)):
    sv.tasks.delete(task_id, with_subtasks=with_subtasks)
    return Response(status_code=204)


@router.post("/tasks/{task_id}/duplicate", response_model=TaskOut, status_code=201)
def duplicate_task(task_id: int, sv: Services = Depends(get_services)):
    """Duplique la tâche et ses sous-tâches (statut « Pas commencé »)."""
    return sv.tasks.duplicate(task_id)


# --- sous-tâches ---


@router.get("/tasks/{task_id}/subtasks", response_model=list[TaskOut])
def subtasks(task_id: int, sv: Services = Depends(get_services)):
    return sv.tasks.subtasks(task_id)


@router.post("/tasks/{task_id}/attach", response_model=TaskOut)
def attach(task_id: int, data: AttachIn, sv: Services = Depends(get_services)):
    """Fait de cette tâche une sous-tâche de ``parent_id`` (Ctrl + glisser-déposer)."""
    return sv.tasks.attach(task_id, data.parent_id)


@router.post("/tasks/{task_id}/move", response_model=TaskOut)
def move(task_id: int, data: MoveIn, sv: Services = Depends(get_services)):
    """Glisser-déposer dans un kanban : changement de colonne (``patch``) et reclassement (``order`` :
    identifiants de la colonne d'arrivée dans l'ordre affiché) ; l'urgence s'ajuste aux voisines."""
    return sv.tasks.move(task_id, data.patch, data.order)


@router.post("/tasks/{task_id}/detach", response_model=TaskOut)
def detach(task_id: int, sv: Services = Depends(get_services)):
    return sv.tasks.detach(task_id)


@router.post("/tasks/{task_id}/subtasks/reorder", response_model=list[TaskOut])
def reorder_subtasks(task_id: int, data: IdsIn, sv: Services = Depends(get_services)):
    return sv.tasks.reorder_subtasks(task_id, data.ids)


# --- partage ---


@router.put("/tasks/{task_id}/shares", response_model=TaskOut)
def set_shares(task_id: int, data: SharesIn, sv: Services = Depends(get_services)):
    return sv.tasks.set_shares(task_id, data.user_ids)


# --- liens ---


@router.post("/tasks/{task_id}/links", response_model=LinkOut, status_code=201)
def add_link(task_id: int, data: LinkIn, sv: Services = Depends(get_services)):
    return sv.tasks.add_link(task_id, data)


@router.patch("/links/{link_id}", response_model=LinkOut)
def update_link(link_id: int, patch: LinkPatch, sv: Services = Depends(get_services)):
    return sv.tasks.update_link(link_id, patch)


@router.delete("/links/{link_id}", status_code=204)
def remove_link(link_id: int, sv: Services = Depends(get_services)):
    sv.tasks.remove_link(link_id)
    return Response(status_code=204)


# --- pièces jointes ---


@router.post("/tasks/{task_id}/attachments", response_model=LinkOut, status_code=201)
def upload_attachment(task_id: int, file: UploadFile = File(...), sv: Services = Depends(get_services)):
    """Envoie un fichier et l'ajoute aux liens de la tâche."""
    return sv.attachments.upload(task_id, file.filename or "fichier", file.file, file.content_type)


@router.get("/attachments/{attachment_id}")
def download_attachment(attachment_id: str, download: bool = False, sv: Services = Depends(get_services)):
    meta, path = sv.attachments.get(attachment_id)
    inline = not download and meta.content_type in _INLINE_TYPES
    return FileResponse(
        path,
        media_type=meta.content_type if inline else "application/octet-stream",
        filename=meta.filename,
        content_disposition_type="inline" if inline else "attachment",
        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"},
    )
