"""API REST ``/api/v1`` (utilisée par le client bureau, documentée sur ``/docs``)."""

from __future__ import annotations

from fastapi import APIRouter

from organizer.server.api import auth, boards, labels, tasks, undo, users

API_PREFIX = "/api/v1"

api_router = APIRouter(prefix=API_PREFIX)
for module in (auth, users, labels, tasks, boards, undo):
    api_router.include_router(module.router)
