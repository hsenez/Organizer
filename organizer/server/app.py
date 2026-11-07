"""Point d'entrée du serveur : ``python run_server.py`` (écoute sur 0.0.0.0:2603 par défaut)."""

from __future__ import annotations

import logging

from nicegui import app, ui

from organizer.config import Settings, load_settings
from organizer.server.pages import register_pages
from organizer.server.state import AppState, create_state
from organizer.server.wiring import install

log = logging.getLogger("organizer")


def build(settings: Settings | None = None) -> AppState:
    """Prépare la base, le middleware, l'API et les pages sur l'application NiceGUI."""
    state = create_state(settings or load_settings())
    install(app, state)
    register_pages()

    app.on_startup(lambda: log.info("%d session(s) expirée(s) purgée(s)", state.auth.purge_expired()))
    return state


def main() -> None:
    state = build()
    ui.run(
        host=state.settings.host,
        port=state.settings.port,
        title="Organizer",
        favicon="📋",
        dark=None,  # suit le thème du système
        language="fr",
        reload=False,
        show=False,
        fastapi_docs=True,  # documentation de l'API sur /docs
        show_welcome_message=True,
    )
