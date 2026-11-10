"""Routes des projets et des tags."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel

from organizer.core.schemas import ProjectIn, ProjectOut, ProjectPatch, TagIn, TagOut, TagPatch
from organizer.core.services import Services
from organizer.server.api.deps import get_services

router = APIRouter(tags=["Projets et tags"])


class IdsIn(BaseModel):
    ids: list[int]


class MergeIn(BaseModel):
    target_id: int


# --- Projets ---


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(include_archived: bool = False, sv: Services = Depends(get_services)):
    return sv.projects.list(include_archived=include_archived)


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(data: ProjectIn, sv: Services = Depends(get_services)):
    return sv.projects.create(data)


@router.post("/projects/reorder", status_code=204)
def reorder_projects(data: IdsIn, sv: Services = Depends(get_services)):
    sv.projects.reorder(data.ids)
    return Response(status_code=204)


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, sv: Services = Depends(get_services)):
    return sv.projects.get(project_id)


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, patch: ProjectPatch, sv: Services = Depends(get_services)):
    return sv.projects.update(project_id, patch)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: int, sv: Services = Depends(get_services)):
    sv.projects.delete(project_id)
    return Response(status_code=204)


# --- Tags ---


@router.get("/tags", response_model=list[TagOut])
def list_tags(sv: Services = Depends(get_services)):
    return sv.tags.list()


@router.post("/tags", response_model=TagOut, status_code=201)
def create_tag(data: TagIn, sv: Services = Depends(get_services)):
    return sv.tags.create(data)


@router.get("/tags/suggest-color")
def suggest_tag_color(avoid: list[str] = Query(default=[]), sv: Services = Depends(get_services)) -> str:
    """Couleur bien distincte des tags existants (et surtout des couleurs ``avoid``)."""
    return sv.tags.suggest_color(avoid)


@router.post("/tags/reorder", status_code=204)
def reorder_tags(data: IdsIn, sv: Services = Depends(get_services)):
    sv.tags.reorder(data.ids)
    return Response(status_code=204)


@router.get("/tags/{tag_id}", response_model=TagOut)
def get_tag(tag_id: int, sv: Services = Depends(get_services)):
    return sv.tags.get(tag_id)


@router.patch("/tags/{tag_id}", response_model=TagOut)
def update_tag(tag_id: int, patch: TagPatch, sv: Services = Depends(get_services)):
    return sv.tags.update(tag_id, patch)


@router.delete("/tags/{tag_id}", status_code=204)
def delete_tag(tag_id: int, sv: Services = Depends(get_services)):
    sv.tags.delete(tag_id)
    return Response(status_code=204)


@router.post("/projects/{project_id}/merge", response_model=ProjectOut)
def merge_project(project_id: int, data: MergeIn, sv: Services = Depends(get_services)):
    """Fusionne ce projet dans ``target_id`` : ses tâches et événements y passent, ce projet disparaît."""
    return sv.projects.merge(project_id, data.target_id)


@router.post("/tags/{tag_id}/merge", response_model=TagOut)
def merge_tag(tag_id: int, data: MergeIn, sv: Services = Depends(get_services)):
    """Fusionne ce tag dans ``target_id`` (ce tag disparaît)."""
    return sv.tags.merge(tag_id, data.target_id)
