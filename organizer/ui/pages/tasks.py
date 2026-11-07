"""📋 Toutes les tâches (version simple : les filtres et tris arrivent à l'étape 5)."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import Response
from nicegui import ui

from organizer.core.schemas import TaskSort
from organizer.ui.components.task_card import task_card
from organizer.ui.context import UiContext
from organizer.ui.layout import app_frame, card_grid, empty_state, section_title


def page(make_context):
    def tasks_page(request: Request):
        ctx = make_context(request)
        if isinstance(ctx, Response):
            return ctx
        with app_frame(ctx, "/tasks", "Toutes les tâches", open_task=request.query_params.get("task")):
            body = ui.refreshable(lambda: _body(ctx))
            body()
            ctx.on_refresh(body.refresh)
        return None

    return tasks_page


def _body(ctx: UiContext) -> None:
    tasks = ctx.ds.tasks.list(sort=TaskSort(key="priority"))
    open_tasks = [t for t in tasks if not t.status.is_closed]
    closed = [t for t in tasks if t.status.is_closed]
    section_title("📋", "Tâches ouvertes", len(open_tasks), "Triées par priorité (importance + urgence)")
    if not open_tasks:
        empty_state("🗒️", "Aucune tâche ouverte. Le bouton ➕ (ou la touche N) en crée une.")
    with card_grid():
        for task in open_tasks:
            task_card(task, ctx)
    if closed:
        with ui.expansion(f"✅ Terminées et annulées ({len(closed)})").classes("w-full"):
            with card_grid():
                for task in closed:
                    task_card(task, ctx)
