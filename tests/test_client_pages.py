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


async def connect(user: User, password: str = "motdepasse-12") -> None:
    await user.open("/")
    await user.should_see(marker="connect-server")
    fill(user, "connect-server", "pi")
    fill(user, "connect-username", "alice")
    fill(user, "connect-password", password)
    user.find(marker="connect-submit").click()


async def test_connect_use_and_logout(server, user: User):
    account = server.users.create_user("alice", "motdepasse-12", "Alice")
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
    server.users.create_user("alice", "motdepasse-12", "Alice")
    await connect(user)
    await user.should_see(marker="version-banner")
    await user.should_see("Ce poste est en retard")
    await user.open("/settings?tab=connection")
    await user.should_see("serveur 9.0.0")


async def test_short_password_banner_on_desktop(server, user: User, monkeypatch):
    """Client bureau connecté (par l'API) avec un ancien mot de passe court : même bandeau que le web."""
    from organizer.core.services import users as users_module

    monkeypatch.setattr(users_module, "MIN_PASSWORD_LENGTH", 6)
    server.users.create_user("alice", "ancien", "Alice")
    monkeypatch.undo()
    await connect(user, "ancien")
    await user.should_see("Bonjour Alice")
    await user.should_see(marker="password-banner")
    await user.should_not_see(marker="version-banner")


async def test_backup_saved_to_downloads_on_desktop(server, user: User, tmp_path):
    """Client bureau : le bouton enregistre l'archive dans « Téléchargements » (ici le dossier du client)."""
    import asyncio

    server.users.create_user("alice", "motdepasse-12", "Alice")
    await connect(user)
    await user.should_see("Bonjour Alice")
    await user.open("/settings?tab=data")
    user.find(marker="backup-download").click()
    folder = tmp_path / "client" / "downloads"
    for _ in range(50):
        if list(folder.glob("organizer-*.tar")):
            break
        await asyncio.sleep(0.05)
    (archive,) = folder.glob("organizer-*.tar")
    await user.should_see("Sauvegarde enregistrée")
    assert archive.stat().st_size > 0 and not list(folder.glob("*.part"))


async def test_dropped_file_paths_are_read_on_desktop(server, user: User, tmp_path):
    """Client bureau : un fichier déposé connu seulement par son adresse file:// est lu sur le poste."""
    account = server.users.create_user("alice", "motdepasse-12", "Alice")
    sv = server.services_for(account)
    task = sv.tasks.create(TaskCreate(title="Devis"))
    document = tmp_path / "devis signé.txt"
    document.write_text("signé")
    await connect(user)
    await user.should_see("Bonjour Alice")
    await user.open("/tasks")
    await user.should_see(marker=f"task-card-{task.id}")
    uri = "file://" + str(document).replace(" ", "%20")
    user.find(marker="file-drop").trigger("paths", {"kind": "card", "task": task.id, "uris": [uri]})
    await user.should_see("joint(s) à « Devis »")
    (link,) = sv.tasks.get(task.id).links
    assert link.label == "devis signé.txt"
    _, path = sv.attachments.get(link.target)
    assert path.read_text() == "signé"


async def test_connection_tab_shows_the_route(server, user: User):
    server.users.create_user("alice", "motdepasse-12", "Alice")
    await connect(user)
    await user.should_see("Bonjour Alice")
    await user.open("/settings?tab=connection")
    await user.should_see(marker="connection-route")
    await user.should_see("En ce moment : adresse du serveur")
    user.find(marker="connection-lan").click()  # désactivé
    await user.should_see("réseau local désactivé")


async def test_connection_badge_on_desktop(server, user: User):
    server.users.create_user("alice", "motdepasse-12", "Alice")
    await connect(user)
    await user.should_see("Bonjour Alice")
    (badge,) = user.find(marker="connection-badge").elements
    assert (
        badge.text == "🌍"
    )  # serveur de test « http://pi:2603 » : ni adresse locale, ni réseau local trouvé
