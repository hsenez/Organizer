"""Client bureau : RemoteDataSource (même contrat que les services locaux, via l'API), connexion,
configuration, verrou de la fenêtre, notifications des rappels, ouverture des fichiers."""

from __future__ import annotations

import io
import os
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from organizer.client import system
from organizer.client.api import ApiClient, error_from
from organizer.client.app import DesktopClient, LaunchGuard
from organizer.client.config import ClientConfig, ConfigStore, normalize_server_url
from organizer.client.notifications import NotifiedLog, ReminderNotifier, describe
from organizer.client.remote import RemoteDataSource
from organizer.config import Settings
from organizer.core.enums import Importance, LinkKind, Status, TaskKind, Urgency
from organizer.core.errors import (
    Forbidden,
    InvalidOperation,
    NotAuthenticated,
    NotFound,
    ServerUnreachable,
    UndoConflict,
)
from organizer.core.schemas import (
    BoardIn,
    ColumnIn,
    LinkIn,
    ProfilePatch,
    ProjectIn,
    TagIn,
    TaskCreate,
    TaskFilter,
    TaskPatch,
    TaskSort,
    UserCreateIn,
)
from organizer.server.state import create_state
from organizer.server.wiring import create_api_app

SERVER = "http://pi:2603"


@pytest.fixture
def state(tmp_path):
    st = create_state(Settings(data_dir=tmp_path / "server", undo_merge_window_seconds=0.0))
    yield st
    st.engine.dispose()


@pytest.fixture
def http(state):
    return TestClient(create_api_app(state), base_url=SERVER)


@pytest.fixture
def alice_user(state):
    return state.users.create_user("alice", "motdepasse-12", "Alice")


@pytest.fixture
def local(state, alice_user):
    """Services locaux d'Alice : la référence du contrat."""
    return state.services_for(alice_user)


@pytest.fixture
def opened():
    return []


@pytest.fixture
def remote(state, http, alice_user, tmp_path, opened) -> RemoteDataSource:
    token, _ = state.auth.create_session(alice_user.id, kind="api", label="test")
    return RemoteDataSource(
        ApiClient(SERVER, token, http=http),
        opener=opened.append,
        browser=opened.append,
        cache_dir=tmp_path / "cache",
    )


# --- contrat : mêmes résultats qu'en local ------------------------------------------------------------------


def test_tasks_through_api_match_local(remote, local):
    project = remote.projects.create(ProjectIn(name="Maison", emoji="🏠"))
    tag = remote.tags.create(TagIn(name="urgent"))
    parent = remote.tasks.create(
        TaskCreate(
            title="Repeindre",
            importance=Importance(4),
            due_date=date.today() + timedelta(days=3),
            project_id=project.id,
            tag_ids=[tag.id],
        )
    )
    # Sous-tâche : hérite des attributs non fournis (le client n'envoie que les champs donnés).
    sub = remote.tasks.create(TaskCreate(title="Acheter la peinture", parent_id=parent.id))
    assert sub.importance == 4 and sub.project.id == project.id and sub.due_date == parent.due_date
    # Patch partiel ; ``None`` explicite efface.
    updated = remote.tasks.update(parent.id, TaskPatch(due_date=None, status=Status.IN_PROGRESS))
    assert updated.due_date is None and updated.status is Status.IN_PROGRESS and updated.title == "Repeindre"

    flt, sort = TaskFilter(include_subtasks=True, text="peint"), TaskSort(key="title")
    assert remote.tasks.list(flt, sort) == local.tasks.list(flt, sort)
    assert remote.tasks.get(parent.id) == local.tasks.get(parent.id)
    assert remote.tasks.subtasks(parent.id) == local.tasks.subtasks(parent.id)

    other = remote.tasks.create(TaskCreate(title="Autre", urgency=Urgency(1)))
    moved = remote.tasks.move(other.id, TaskPatch(status=Status.IN_PROGRESS), [other.id, parent.id])
    assert moved.status is Status.IN_PROGRESS and moved.urgency == parent.urgency
    copy = remote.tasks.duplicate(parent.id)
    assert copy.title.startswith("Repeindre") and copy.id != parent.id
    remote.tasks.delete(copy.id, with_subtasks=True)
    with pytest.raises(NotFound, match="introuvable"):
        remote.tasks.get(copy.id)


def test_subtasks_links_shares_and_errors(remote, state, local):
    a = remote.tasks.create(TaskCreate(title="A"))
    b = remote.tasks.create(TaskCreate(title="B"))
    assert remote.tasks.attach(b.id, a.id).parent_id == a.id
    c = remote.tasks.create(TaskCreate(title="C"))
    with pytest.raises(InvalidOperation, match="un seul niveau"):
        remote.tasks.attach(c.id, b.id)
    assert remote.tasks.detach(b.id).parent_id is None

    link = remote.tasks.add_link(a.id, LinkIn(kind=LinkKind.URL, target="www.example.org"))
    assert link.kind is LinkKind.URL
    remote.tasks.remove_link(link.id)
    assert remote.tasks.get(a.id).links == []

    bob = state.users.create_user("bob", "motdepasse-12", "Bob", by=state.users.actor_for(local.actor.id))
    assert remote.tasks.set_shares(a.id, [bob.id]).shared_with == [bob.id]
    assert {u.username for u in remote.users_public()} == {"alice", "bob"}
    secret = state.services_for(bob).tasks.create(TaskCreate(title="Secret de Bob"))
    with pytest.raises(NotFound):
        remote.tasks.update(secret.id, TaskPatch(title="piraté"))


def test_labels_boards_undo_and_reminders(remote, local):
    t1 = remote.tags.create(TagIn(name="a"))
    t2 = remote.tags.create(TagIn(name="b", avoid_colors=[t1.color]))
    assert t1.color != t2.color and remote.tags.suggest_color([t1.color]).startswith("#")
    remote.tags.reorder([t2.id, t1.id])
    assert [t.name for t in remote.tags.list()] == ["b", "a"]
    assert remote.tags.merge(t1.id, t2.id).name == "b"
    p = remote.projects.create(ProjectIn(name="P"))
    remote.projects.delete(p.id)
    assert remote.projects.list(include_archived=True) == []

    board = remote.boards.create(BoardIn(name="Travaux"))
    board = remote.boards.add_column(board.id, ColumnIn(name="Plus tard"))
    task = remote.tasks.create(TaskCreate(title="Carrelage"))
    remote.boards.place(board.id, task.id, board.columns[-1].id, 0)
    content = remote.boards.content(board.id)
    assert [t.title for t in content.columns[board.columns[-1].id]] == ["Carrelage"]
    assert remote.boards.content(board.id, TaskFilter(text="rien")).columns[board.columns[-1].id] == []
    assert remote.boards.list() == local.boards.list()
    remote.boards.remove(board.id, task.id)

    status = remote.undo.status()
    assert status.undo_label and "Carrelage" in status.undo_label
    assert remote.undo.undo().action == "undo"
    assert remote.undo.redo().action == "redo"

    follow = remote.tasks.create(
        TaskCreate(
            title="Relancer", kind=TaskKind.FOLLOWUP, due_date=date.today(), reminder_date=date.today()
        )
    )
    assert [t.id for t in remote.tasks.reminders_due()] == [follow.id]


def test_undo_conflict_is_mapped(remote, state, local):
    bob = state.users.create_user("bob", "motdepasse-12", "Bob", by=state.users.actor_for(local.actor.id))
    task = remote.tasks.create(TaskCreate(title="v1"))
    remote.tasks.set_shares(task.id, [bob.id])
    remote.tasks.update(task.id, TaskPatch(title="v2"))
    state.services_for(bob).tasks.update(task.id, TaskPatch(title="v3 (Bob)"))
    with pytest.raises(UndoConflict):
        remote.undo.undo()


def test_account_and_prefs(remote, state):
    remote.account.set_pref("board:status", {"collapsed": ["status:done"], "widths": {}})
    assert remote.account.get_pref("board:status")["collapsed"] == ["status:done"]
    assert remote.account.get_pref("absente", {"défaut": 1}) == {"défaut": 1}
    remote.account.set_pref("view:x", None)
    assert remote.account.get_pref("view:x", "rien") == "rien"
    assert remote.account.update_profile(ProfilePatch(display_name="Alice B.")).display_name == "Alice B."
    created = remote.account.create_user(UserCreateIn(username="carol", password="motdepasse-12"))
    assert "carol" in {u.username for u in remote.account.all_users()}
    assert any(s.current for s in remote.account.sessions())
    assert created.username == "carol"


def test_attachments_and_opening(remote, opened, tmp_path):
    task = remote.tasks.create(TaskCreate(title="Facture"))
    link = remote.attachments.upload(task.id, "facture été.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")
    path = remote.open_attachment(link.target)
    assert path.name == "facture été.pdf" and path.read_bytes() == b"%PDF-1.4" and opened == [str(path)]

    doc = tmp_path / "notes.txt"
    doc.write_text("x")
    remote.open_path(str(doc))
    remote.open_url("https://example.org")
    assert opened[-2:] == [str(doc), "https://example.org"]
    with pytest.raises(NotFound, match="Introuvable sur ce poste"):
        remote.open_path("/n/existe/pas.txt")


def test_expired_token_and_unreachable_server(http, state, alice_user):
    with pytest.raises(NotAuthenticated):
        RemoteDataSource(ApiClient(SERVER, "mauvais-jeton", http=http))
    api = ApiClient("http://127.0.0.1:9", "x", timeout=0.5)  # port fermé
    with pytest.raises(ServerUnreachable, match="injoignable"):
        api.call("GET", "/auth/me")


def test_error_mapping():
    import httpx

    def response(code, detail):
        return httpx.Response(code, json={"detail": detail})

    assert isinstance(error_from(response(403, "Non")), Forbidden)
    assert isinstance(error_from(response(409, "Conflit")), UndoConflict)
    err = error_from(response(422, [{"loc": ["body", "title"], "msg": "x"}]))
    assert isinstance(err, InvalidOperation) and "title" in err.message
    assert "Erreur du serveur" in error_from(httpx.Response(500, text="boum")).message


# --- connexion et configuration -----------------------------------------------------------------------------


def test_normalize_server_url():
    assert normalize_server_url("raspberrypi.local") == "http://raspberrypi.local:2603"
    assert normalize_server_url(" 192.168.1.20:8000/ ") == "http://192.168.1.20:8000"
    assert normalize_server_url("HTTPS://organizer.example.org") == "https://organizer.example.org"
    with pytest.raises(ValueError):
        normalize_server_url("  ")


def test_config_store_roundtrip(tmp_path):
    store = ConfigStore(tmp_path / "conf")
    assert store.load() == ClientConfig()
    store.save(ClientConfig(server="http://pi:2603", username="alice", token="t"))
    assert store.load().token == "t"
    if os.name == "posix":
        assert store.path.stat().st_mode & 0o777 == 0o600
    store.path.write_text("pas du json")
    assert store.load() == ClientConfig()


def test_desktop_client_login_flow(state, http, tmp_path):
    client = DesktopClient(ConfigStore(tmp_path / "conf"), http_factory=lambda _server: http)
    with pytest.raises(InvalidOperation, match="aucun compte"):
        client.login("pi", "alice", "motdepasse-12")
    state.users.create_user("alice", "motdepasse-12", "Alice")
    with pytest.raises(Exception, match="incorrect"):
        client.login("pi", "alice", "mauvais")
    user = client.login("pi", "alice", "motdepasse-12")
    assert user.username == "alice"
    saved = client.store.path.read_text()
    assert "motdepasse-12" not in saved and client.store.load().server == "http://pi:2603"
    assert client.api is not None and client.api.call("GET", "/auth/me") is None  # appel authentifié ok
    assert any("Client bureau" in s.label for s in state.auth.list_sessions(user.id))
    client.forget_token()
    assert client.api is None and client.store.load().token is None


def test_launch_guard():
    api = FastAPI()
    api.add_middleware(LaunchGuard, secret="s3cret")

    @api.get("/")
    def home():
        return {"ok": True}

    browser = TestClient(api, base_url="http://127.0.0.1")
    assert browser.get("/").status_code == 403
    assert browser.get("/?launch=autre").status_code == 403
    first = browser.get("/?launch=s3cret", follow_redirects=False)
    assert first.status_code == 303 and "organizer_window" in first.headers["set-cookie"]
    assert browser.get("/").json() == {"ok": True}  # le cookie suffit ensuite
    assert TestClient(api).get("/_nicegui/static/x").status_code == 404  # ressources : pas de verrou


# --- notifications des rappels ------------------------------------------------------------------------------


def _task(remote, title, **kw):
    return remote.tasks.create(TaskCreate(title=title, **kw))


async def test_reminder_notifier(remote, tmp_path):
    today = date.today()
    tasks = [_task(remote, f"Suivi {i}", due_date=today + timedelta(days=1)) for i in range(5)]
    sent = []

    async def send(title, message, on_clicked):
        sent.append((title, message, on_clicked))

    enabled = {"value": True}
    clicked = []
    notifier = ReminderNotifier(
        lambda: (enabled["value"], tasks[:2]),
        NotifiedLog(tmp_path / "notified.json"),
        send,
        open_task=clicked.append,
    )
    assert [t.id for t in await notifier.check()] == [tasks[0].id, tasks[1].id]
    assert sent[0][0] == "🔔 Rappel : Suivi 0" and "Demain" in sent[0][1]
    sent[0][2]()
    assert clicked == [tasks[0].id]
    assert await notifier.check() == []  # une seule fois par jour
    notifier.today = lambda: today + timedelta(days=1)
    assert len(await notifier.check()) == 2  # le lendemain, de nouveau
    enabled["value"] = False
    notifier.today = lambda: today + timedelta(days=2)
    assert await notifier.check() == []
    grouped = describe(tasks, today)
    assert len(grouped) == 1 and grouped[0][0] == "🔔 5 rappels" and grouped[0][2] is None


# --- système ------------------------------------------------------------------------------------------------


def test_system_helpers(tmp_path, monkeypatch):
    assert (
        system.filename_from_disposition("attachment; filename*=utf-8''r%C3%A9sum%C3%A9.pdf") == "résumé.pdf"
    )
    assert system.filename_from_disposition('attachment; filename="a b.txt"') == "a b.txt"
    assert system.filename_from_disposition("") == "fichier"
    path = system.cache_file(tmp_path, "abc", "../../etc/passwd")
    assert path.parent == tmp_path / "abc" and "/" not in path.name
    target = tmp_path / "dossier avec espace" / "f.txt"
    target.parent.mkdir()
    target.write_text("x")
    assert system.resolve_local_path(f"file://{target.as_posix()}".replace(" ", "%20")) == target
    monkeypatch.setenv("HOME", str(tmp_path))
    assert system.resolve_local_path("~/dossier avec espace/f.txt") == target
    monkeypatch.setenv("ORGANIZER_CLIENT_DIR", str(tmp_path / "c"))
    assert system.config_dir() == tmp_path / "c" and system.cache_dir() == tmp_path / "c" / "cache"
