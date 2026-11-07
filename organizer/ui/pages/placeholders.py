"""Modules à venir : la page existe déjà dans la navigation et annonce son étape."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import Response
from nicegui import ui

from organizer.ui.layout import app_frame

_UPCOMING = {
    "/kanban": (
        "📊",
        "Kanbans",
        6,
        "Boards par statut, échéance, type et projet, boards personnalisés, glisser-déposer.",
    ),
    "/matrix": ("🎯", "Matrice", 6, "Matrice d'Eisenhower 2×2 et 4×4, glisser-déposer entre quadrants."),
}


def _builder(path: str, emoji: str, title: str, step: int, text: str):
    def make(make_context):
        def placeholder_page(request: Request):
            ctx = make_context(request)
            if isinstance(ctx, Response):
                return ctx
            with app_frame(ctx, path, title):
                with ui.card().classes("w-full items-center py-10 gap-2 rounded-xl"):
                    ui.label(emoji).classes("text-6xl")
                    ui.label(title).classes("text-2xl font-bold")
                    ui.label(f"🚧 Arrive à l'étape {step}").classes("text-amber-700")
                    ui.label(text).classes("text-gray-500 text-center")
            return None

        return placeholder_page

    return make


PAGES = {path: _builder(path, *info) for path, info in _UPCOMING.items()}
