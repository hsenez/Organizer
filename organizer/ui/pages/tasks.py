"""📋 Toutes les tâches et 🔍 Recherche : liste filtrable, triable et regroupable (voir ``TaskListView``)."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import Response
from nicegui import ui

from organizer.core.schemas import TaskFilter, TaskSort
from organizer.ui.components.task_list import TaskListView
from organizer.ui.layout import app_frame


def page(make_context):
    def tasks_page(request: Request):
        ctx = make_context(request)
        if isinstance(ctx, Response):
            return ctx
        with app_frame(ctx, "/tasks", "Toutes les tâches", open_task=request.query_params.get("task")):
            with ui.row().classes("items-center gap-2"):
                ui.label("📋").classes("text-2xl")
                ui.label("Toutes les tâches").classes("text-2xl font-bold")
            TaskListView(ctx, "view:tasks", default_sort=TaskSort(key="priority"))
        return None

    return tasks_page


def search_page(make_context):
    def search(request: Request):
        ctx = make_context(request)
        if isinstance(ctx, Response):
            return ctx
        with app_frame(ctx, "/search", "Recherche", open_task=request.query_params.get("task")):
            with ui.row().classes("items-center gap-2"):
                ui.label("🔍").classes("text-2xl")
                ui.label("Recherche").classes("text-2xl font-bold")
                ui.label("dans toutes les tâches, sous-tâches et tâches terminées comprises").classes(
                    "text-sm text-gray-500"
                )
            TaskListView(
                ctx,
                "view:search",
                default_filter=TaskFilter(include_subtasks=True),
                default_sort=TaskSort(key="priority"),
                initial_text=request.query_params.get("q"),
                mixed_closed=True,
                autofocus=True,
            )
        return None

    return search
