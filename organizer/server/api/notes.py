"""Routes des notes (``/notes``), de leurs partages et épingles, et des liens internes (``/refs``)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from organizer.core.schemas import NoteCreate, NoteFilter, NoteOut, NotePatch, RefOut, ShareSpec
from organizer.core.services import Services
from organizer.server.api.deps import get_services

router = APIRouter(tags=["Notes"])


class NoteSharesIn(BaseModel):
    shares: list[ShareSpec]


class PinIn(BaseModel):
    pinned: bool


class RefsIn(BaseModel):
    refs: list[str]


@router.post("/notes/query", response_model=list[NoteOut])
def query_notes(flt: NoteFilter, sv: Services = Depends(get_services)):
    """Notes visibles (épinglées d'abord, puis les plus récentes), filtrées comme dans la page Notes."""
    return sv.notes.list(flt)


@router.post("/notes", response_model=NoteOut, status_code=201)
def create_note(data: NoteCreate, sv: Services = Depends(get_services)):
    return sv.notes.create(data)


@router.get("/notes/{note_id}", response_model=NoteOut)
def get_note(note_id: int, sv: Services = Depends(get_services)):
    return sv.notes.get(note_id)


@router.patch("/notes/{note_id}", response_model=NoteOut)
def update_note(note_id: int, patch: NotePatch, sv: Services = Depends(get_services)):
    """Seuls les champs présents dans le JSON sont modifiés."""
    return sv.notes.update(note_id, patch)


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: int, sv: Services = Depends(get_services)):
    sv.notes.delete(note_id)
    return Response(status_code=204)


@router.put("/notes/{note_id}/shares", response_model=NoteOut)
def set_note_shares(note_id: int, data: NoteSharesIn, sv: Services = Depends(get_services)):
    """Avec qui la note est partagée, et si chacun peut la modifier (propriétaire seulement)."""
    return sv.notes.set_shares(note_id, data.shares)


@router.put("/notes/{note_id}/pin", response_model=NoteOut)
def set_note_pinned(note_id: int, data: PinIn, sv: Services = Depends(get_services)):
    """Épingle (ou non) la note en haut de **ma** liste."""
    return sv.notes.set_pinned(note_id, data.pinned)


@router.post("/refs/resolve", response_model=list[RefOut])
def resolve_refs(data: RefsIn, sv: Services = Depends(get_services)):
    """Ce que désigne chaque lien interne (``task:12``, ``event:8``, ``note:5``) : titre actuel, ou
    inaccessible."""
    return sv.notes.resolve(data.refs)


@router.get("/refs/backlinks", response_model=list[RefOut])
def backlinks(ref: str, sv: Services = Depends(get_services)):
    """Notes, tâches et événements visibles dont le texte contient un lien vers ``ref``."""
    return sv.notes.backlinks(ref)
