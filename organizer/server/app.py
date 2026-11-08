"""Point d'entrée du serveur : ``python run_server.py`` (écoute sur 0.0.0.0:2603 par défaut)."""

from __future__ import annotations

import logging

from nicegui import app, ui

from organizer.config import Settings, load_settings
from organizer.server import pwa
from organizer.server.pages import register_pages
from organizer.server.state import AppState, create_state
from organizer.server.wiring import install

log = logging.getLogger("organizer")


def build(settings: Settings | None = None) -> AppState:
    """Prépare la base, le middleware, l'API et les pages sur l'application NiceGUI."""
    state = create_state(settings or load_settings())
    install(app, state)
    register_pages()
    pwa.add_static(app)
    pwa.add_head()

    app.on_startup(lambda: log.info("%d session(s) expirée(s) purgée(s)", state.auth.purge_expired()))
    return state


def configure_logging() -> None:
    """Messages d'Organizer (niveau INFO et plus) sur la sortie d'erreur, que systemd range dans le journal
    du service (``journalctl -u organizer``). Sans cela, seuls les avertissements apparaîtraient."""
    logger = logging.getLogger("organizer")
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s : %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


SHUTDOWN_GRACE_SECONDS = 3


def main() -> None:
    configure_logging()
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
        # À l'arrêt (systemctl restart…), uvicorn attend la fin des connexions en cours ; le flux temps réel
        # d'un client bureau ne se termine jamais de lui-même : sans limite, systemd devait forcer l'arrêt
        # au bout de 90 s. Le client se reconnecte tout seul.
        timeout_graceful_shutdown=SHUTDOWN_GRACE_SECONDS,
        **(
            {"ssl_certfile": state.settings.ssl_cert, "ssl_keyfile": state.settings.ssl_key}
            if state.settings.https
            else {}
        ),
    )
