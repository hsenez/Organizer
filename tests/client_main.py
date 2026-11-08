"""Fichier principal du simulateur NiceGUI pour les pages du client bureau (``test_client_pages.py``) :
le client parle à un serveur de test en mémoire (``client_harness.HTTP``)."""

import os
from pathlib import Path

from nicegui import ui

from organizer.client.app import DesktopClient
from organizer.client.config import ConfigStore
from tests import client_harness

client = DesktopClient(
    ConfigStore(Path(os.environ["ORGANIZER_CLIENT_DIR"])), http_factory=lambda _server: client_harness.HTTP
)
client.install(notifications=False, live=False)
ui.run()
