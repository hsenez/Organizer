"""Pages du client bureau (simulateur NiceGUI) : connexion, application sur l'API, déconnexion."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from nicegui import ui
from nicegui.testing import User

from organizer.config import Settings
from organizer.core.enums import Status
from organizer.core.schemas import TaskCreate
from organizer.server.state import create_state
from organizer.server.wiring import create_api_app
from tests import client_harness

pytestmark = pytest.mark.nicegui_main_file("tests/client_main.py")


@pytest.fixture(autouse=True)
def client_dir(tmp_path, monkeypatch):
    """Avant le simulateur : ``client_main.py`` lit ce dossier au démarrage."""
    monkeypatch.setenv("ORGANIZER_CLIENT_DIR", str(tmp_path / "client"))


@pytest.fixture
def server(tmp_path):
    state = create_state(Settings(data_dir=tmp_path / "server"))
    client_harness.HTTP = TestClient(create_api_app(state), base_url="http://pi:2603")
    yield state
    client_harness.HTTP = None
    state.engine.dispose()


def fill(user: User, marker: str, text: str) -> None:
    user.find(kind=ui.input, marker=marker).type(text)


async def connect(user: User, password: str = "motdepasse") -> None:
    await user.open("/")
    await user.should_see(marker="connect-server")
    fill(user, "connect-server", "pi")
    fill(user, "connect-username", "alice")
    fill(user, "connect-password", password)
    user.find(marker="connect-submit").click()


async def test_connect_use_and_logout(server, user: User):
    account = server.users.create_user("alice", "motdepasse", "Alice")
    sv = server.services_for(account)
    task = sv.tasks.create(TaskCreate(title="Tâche du Pi"))

    await connect(user, "mauvais")
    await user.should_see("incorrect")
    await connect(user)
    await user.should_see("Bonjour Alice")
    await user.should_see("Tâche du Pi")

    await user.open("/kanban?board=status")
    await user.should_see(marker="zone-status:done")
    user.find(marker="dnd").trigger("drop", {"task": task.id, "zone": "status:done", "index": None})
    await user.should_see(marker="zone-status:done")
    assert sv.tasks.get(task.id).status is Status.DONE  # écrit sur le serveur, via l'API

    await user.open("/settings?tab=connection")
    await user.should_see("Serveur : http://pi:2603")
    user.find(marker="connection-logout").click()
    await user.should_see(marker="connect-server")
    assert not any(s.kind == "api" for s in server.auth.list_sessions(account.id))  # jeton révoqué


async def test_server_without_account(server, user: User):
    await connect(user)
    await user.should_see("aucun compte")


async def test_version_banner(server, user: User, monkeypatch):
    from organizer.server.api import auth as auth_routes

    monkeypatch.setattr(auth_routes, "__version__", "9.0.0")  # le serveur a été mis à jour
    server.users.create_user("alice", "motdepasse", "Alice")
    await connect(user)
    await user.should_see(marker="version-banner")
    await user.should_see("Ce poste est en retard")
    await user.open("/settings?tab=connection")
    await user.should_see("serveur 9.0.0")
