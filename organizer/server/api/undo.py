"""Routes annuler / rétablir (Ctrl+Z / Ctrl+Maj+Z)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from organizer.core.schemas import UndoResult, UndoStatus
from organizer.core.services import Services
from organizer.server.api.deps import get_services

router = APIRouter(tags=["Annuler / rétablir"])


@router.get("/undo", response_model=UndoStatus)
def undo_status(sv: Services = Depends(get_services)):
    """Libellés de ce qu'annuleraient / rétabliraient Ctrl+Z et Ctrl+Maj+Z."""
    return sv.undo.status()


@router.post("/undo", response_model=UndoResult | None)
def undo(sv: Services = Depends(get_services)):
    """Annule la dernière action (``null`` s'il n'y a rien à annuler)."""
    return sv.undo.undo()


@router.post("/redo", response_model=UndoResult | None)
def redo(sv: Services = Depends(get_services)):
    return sv.undo.redo()
