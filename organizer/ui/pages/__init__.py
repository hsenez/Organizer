"""Pages de l'application. Enregistrées par :func:`register_app_pages`, qui reçoit une fabrique de contexte :
le serveur fournit la sienne (cookie → LocalDataSource), le client bureau fournira la sienne (étape 7)."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Request
from fastapi.responses import Response
from nicegui import ui

from organizer.ui.context import UiContext
from organizer.ui.pages import home, kanban, matrix, settings, tasks

ContextFactory = Callable[[Request], "UiContext | Response"]


def register_app_pages(make_context: ContextFactory) -> None:
    common = {"favicon": "📋", "dark": None}
    ui.page("/", title="Accueil · Organizer", **common)(home.page(make_context))
    ui.page("/tasks", title="Toutes les tâches · Organizer", **common)(tasks.page(make_context))
    ui.page("/search", title="Recherche · Organizer", **common)(tasks.search_page(make_context))
    ui.page("/settings", title="Réglages · Organizer", **common)(settings.page(make_context))
    ui.page("/kanban", title="Kanbans · Organizer", **common)(kanban.page(make_context))
    ui.page("/matrix", title="Matrice · Organizer", **common)(matrix.page(make_context))
