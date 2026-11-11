"""Pages de l'application. Enregistrées par :func:`register_app_pages`, qui reçoit une fabrique de contexte :
le serveur fournit la sienne (cookie → LocalDataSource), le client bureau fournira la sienne (étape 7)."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Request
from fastapi.responses import Response
from nicegui import ui

from organizer import FAVICON
from organizer.ui.components.viewport import VIEWPORT
from organizer.ui.context import UiContext
from organizer.ui.pages import calendar, home, kanban, matrix, notes, notifications, settings, tasks

ContextFactory = Callable[[Request], "UiContext | Response"]


def register_app_pages(make_context: ContextFactory) -> None:
    common = {"favicon": FAVICON, "dark": None, "viewport": VIEWPORT}
    ui.page("/", title="Accueil · Organizer", **common)(home.page(make_context))
    ui.page("/tasks", title="Toutes les tâches · Organizer", **common)(tasks.page(make_context))
    ui.page("/search", title="Recherche · Organizer", **common)(tasks.search_page(make_context))
    ui.page("/settings", title="Réglages · Organizer", **common)(settings.page(make_context))
    ui.page("/kanban", title="Kanbans · Organizer", **common)(kanban.page(make_context))
    ui.page("/matrix", title="Matrice · Organizer", **common)(matrix.page(make_context))
    ui.page("/calendar", title="Calendrier · Organizer", **common)(calendar.page(make_context))
    ui.page("/notes", title="Notes · Organizer", **common)(notes.page(make_context))
    ui.page("/notifications", title="Notifications · Organizer", **common)(notifications.page(make_context))
