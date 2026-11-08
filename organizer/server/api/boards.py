"""Routes des boards personnalisés (colonnes, cartes, partage)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from organizer.core.schemas import (
    BoardContent,
    BoardIn,
    BoardOut,
    BoardPatch,
    ColumnIn,
    ColumnPatch,
    TaskFilter,
)
from organizer.core.services import Services
from organizer.server.api.deps import get_services

router = APIRouter(tags=["Boards"])


class IdsIn(BaseModel):
    ids: list[int]


class SharesIn(BaseModel):
    user_ids: list[int]


class PlaceIn(BaseModel):
    column_id: int
    index: int | None = None


@router.get("/boards", response_model=list[BoardOut])
def list_boards(sv: Services = Depends(get_services)):
    return sv.boards.list()


@router.post("/boards", response_model=BoardOut, status_code=201)
def create_board(data: BoardIn, sv: Services = Depends(get_services)):
    return sv.boards.create(data)


@router.get("/boards/{board_id}", response_model=BoardOut)
def get_board(board_id: int, sv: Services = Depends(get_services)):
    return sv.boards.get(board_id)


@router.post("/boards/{board_id}/content", response_model=BoardContent)
def board_content(board_id: int, flt: TaskFilter | None = None, sv: Services = Depends(get_services)):
    """Tâches du board par colonne (filtre facultatif, comme la barre de filtres)."""
    return sv.boards.content(board_id, flt)


@router.patch("/boards/{board_id}", response_model=BoardOut)
def update_board(board_id: int, patch: BoardPatch, sv: Services = Depends(get_services)):
    return sv.boards.update(board_id, patch)


@router.delete("/boards/{board_id}", status_code=204)
def delete_board(board_id: int, sv: Services = Depends(get_services)):
    sv.boards.delete(board_id)
    return Response(status_code=204)


@router.put("/boards/{board_id}/shares", response_model=BoardOut)
def share_board(board_id: int, data: SharesIn, sv: Services = Depends(get_services)):
    return sv.boards.set_shares(board_id, data.user_ids)


@router.post("/boards/{board_id}/columns", response_model=BoardOut, status_code=201)
def add_column(board_id: int, data: ColumnIn, sv: Services = Depends(get_services)):
    return sv.boards.add_column(board_id, data)


@router.post("/boards/{board_id}/columns/reorder", response_model=BoardOut)
def reorder_columns(board_id: int, data: IdsIn, sv: Services = Depends(get_services)):
    return sv.boards.reorder_columns(board_id, data.ids)


@router.patch("/columns/{column_id}", response_model=BoardOut)
def update_column(column_id: int, patch: ColumnPatch, sv: Services = Depends(get_services)):
    return sv.boards.update_column(column_id, patch)


@router.delete("/columns/{column_id}", response_model=BoardOut)
def delete_column(column_id: int, sv: Services = Depends(get_services)):
    """Supprime la colonne ; ses cartes passent dans la première colonne restante."""
    return sv.boards.delete_column(column_id)


@router.put("/boards/{board_id}/cards/{task_id}", status_code=204)
def place_card(board_id: int, task_id: int, data: PlaceIn, sv: Services = Depends(get_services)):
    """Pose ou déplace une tâche dans une colonne (``index`` : position, fin de colonne par défaut)."""
    sv.boards.place(board_id, task_id, data.column_id, data.index)
    return Response(status_code=204)


@router.delete("/boards/{board_id}/cards/{task_id}", status_code=204)
def remove_card(board_id: int, task_id: int, sv: Services = Depends(get_services)):
    sv.boards.remove(board_id, task_id)
    return Response(status_code=204)
