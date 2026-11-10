"""Client bureau : RemoteDataSource (même contrat que les services locaux, via l'API), connexion,
configuration, verrou de la fenêtre, notifications des rappels, ouverture des fichiers."""

from __future__ import annotations

import io
import json
import os
import tarfile
from datetime import date, time, timedelta

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
    EventCreate,
    EventFilter,
    EventPatch,
    EventTimes,
    LinkIn,
    LinkPatch,
    ProfilePatch,
    ProjectIn,
    ShareSpec,
    TagIn,
    TaskCreate,
    TaskFilter,
    TaskPatch,
    TaskSort,
    UserCreateIn,
)
from organizer.core.services.account import AccountService
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


def test_agenda_through_api_matches_local(remote, local, state):
    bob = state.users.create_user("bob", "motdepasse-12", "Bob", by=local.actor)
    tag = remote.tags.create(TagIn(name="sport"))
    day = date(2026, 11, 12)
    event = remote.agenda.create(
        EventCreate(title="Piscine", start_date=day, start_time=time(18, 0), tag_ids=[tag.id], location="Ici")
    )
    assert (event.end_date, event.end_time) == (day, time(19, 0))  # une heure par défaut
    assert remote.agenda.get(event.id) == local.agenda.get(event.id)
    flt = EventFilter(start=day, end=day, text="pisc")
    assert remote.agenda.list(flt) == local.agenda.list(flt) and len(remote.agenda.list(flt)) == 1
    # Patch partiel : seule l'heure de fin change ; ``None`` explicite = toute la journée.
    assert remote.agenda.update(event.id, EventPatch(end_time=time(20, 0))).start_time == time(18, 0)
    assert remote.agenda.update(event.id, EventPatch(start_time=None)).all_day
    shared = remote.agenda.set_shares(event.id, [ShareSpec(user_id=bob.id, can_edit=False)])
    assert shared.shares == [ShareSpec(user_id=bob.id, can_edit=False)]

    link = remote.agenda.add_link(event.id, LinkIn(kind=LinkKind.URL, target="exemple.fr"))
    assert link.event_id == event.id
    assert remote.agenda.update_link(link.id, LinkPatch(label="Site")).label == "Site"
    remote.agenda.remove_link(link.id)
    file = remote.attachments.upload_event(event.id, "plan.txt", io.BytesIO(b"plan"), "text/plain")
    assert local.agenda.get(event.id).links[0].target == file.target

    task = remote.agenda.to_task(event.id)
    assert task.title == "Piscine" and task.due_date == day
    again = remote.agenda.from_task(task.id)  # sans corps : à l'échéance, une heure
    assert again.start_date == day and not again.all_day
    task = remote.agenda.to_task(again.id)
    custom = remote.agenda.from_task(
        task.id, EventTimes(start_date=day, end_date=date(2026, 11, 14)), EventPatch(location="Là-bas")
    )
    assert custom.all_day and custom.end_date == date(2026, 11, 14) and custom.location == "Là-bas"
    back = remote.agenda.to_task(custom.id, TaskPatch(importance=Importance(4)))
    assert back.importance == 4
    custom = remote.agenda.from_task(back.id)
    remote.agenda.delete(custom.id)
    with pytest.raises(NotFound, match="introuvable"):
        remote.agenda.get(custom.id)
    with pytest.raises(InvalidOperation):
        remote.agenda.create(EventCreate(title="X", start_date=day, start_time=time(9), end_time=time(8)))


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


def test_backup_keys_and_download(remote, state, tmp_path):
    """Jetons de sauvegarde et téléchargement de l'archive, comme en local (Alice est l'admin)."""
    local_account = AccountService(state.users, state.auth, remote.user.id)
    created = remote.account.create_backup_key("borg")
    assert created.token.startswith("orgbk_")
    assert remote.account.backup_keys() == local_account.backup_keys()
    remote.account.revoke_backup_key(created.key.id)
    assert remote.account.backup_keys() == []
    with pytest.raises(NotFound):
        remote.account.revoke_backup_key(created.key.id)

    task = remote.tasks.create(TaskCreate(title="Facture"))
    link = remote.attachments.upload(task.id, "f.pdf", io.BytesIO(b"%PDF"), "application/pdf")
    folder = tmp_path / "Téléchargements"
    folder.mkdir()
    path = remote.save_backup(folder=folder)
    assert path.parent == folder and path.name.startswith("organizer-") and path.suffix == ".tar"
    with tarfile.open(path) as tar:
        assert tar.getnames() == ["organizer.db", "uploads", f"uploads/{link.target}", "manifest.json"]
    assert [p.name for p in folder.iterdir()] == [path.name]  # pas de fichier .part laissé
    db_only = remote.save_backup(uploads=False, folder=folder)
    with tarfile.open(db_only) as tar:
        assert tar.getnames() == ["organizer.db", "manifest.json"]


def test_backup_refused_to_non_admin(remote, state, http, tmp_path):
    bob = remote.account.create_user(UserCreateIn(username="bob", password="motdepasse-12"))
    token, _ = state.auth.create_session(bob.id, kind="api")
    bob_remote = RemoteDataSource(ApiClient(SERVER, token, http=http))
    with pytest.raises(Forbidden):
        bob_remote.save_backup(folder=tmp_path)
    with pytest.raises(Forbidden):
        bob_remote.account.backup_keys()
    assert list(tmp_path.glob("*.part")) == []


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
    # Nom de domaine public sans protocole : https (derrière Cloudflare, le port 2603 n'est pas servi).
    assert normalize_server_url("organizer.blou.top/") == "https://organizer.blou.top"
    assert normalize_server_url("http://organizer.blou.top") == "http://organizer.blou.top:2603"
    assert normalize_server_url("organizer.blou.top:2603") == "http://organizer.blou.top:2603"
    # Réseau local, IP, nom sans point : http et port 2603.
    assert normalize_server_url("raspberrypi") == "http://raspberrypi:2603"
    assert normalize_server_url("pi.lan") == "http://pi.lan:2603"
    assert normalize_server_url("localhost") == "http://localhost:2603"
    assert normalize_server_url("86.245.12.7") == "http://86.245.12.7:2603"
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
    assert system.resolve_local_path(target.as_uri()) == target
    # Forme approximative (file://C:/… sous Windows, file:///home/… ailleurs) : acceptée aussi.
    assert system.resolve_local_path(f"file://{target.as_posix()}".replace(" ", "%20")) == target
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # « ~ » sous Windows
    assert system.resolve_local_path("~/dossier avec espace/f.txt") == target
    monkeypatch.setenv("ORGANIZER_CLIENT_DIR", str(tmp_path / "c"))
    assert system.config_dir() == tmp_path / "c" and system.cache_dir() == tmp_path / "c" / "cache"
    assert system.downloads_dir() == tmp_path / "c" / "downloads"
    assert system.safe_filename("a/b:c?.tar") == "a_b_c_.tar" and system.safe_filename(" .. ") == "fichier"


def test_xdg_downloads_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("ORGANIZER_CLIENT_DIR", raising=False)
    monkeypatch.setattr(system.sys, "platform", "linux")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Path.home() quand le test tourne sous Windows
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    assert system.downloads_dir() == tmp_path / "Downloads"  # pas de user-dirs.dirs
    (tmp_path / ".config").mkdir()
    (tmp_path / ".config" / "user-dirs.dirs").write_text(
        '# commentaire\nXDG_DESKTOP_DIR="$HOME/Bureau"\nXDG_DOWNLOAD_DIR="$HOME/Téléchargements"\n',
        encoding="utf-8",
    )
    assert system.downloads_dir() == tmp_path / "Téléchargements"
    assert (tmp_path / "Téléchargements").is_dir()


def test_dropped_file_uris_from_gtk():
    from organizer.client.window import file_uris

    assert file_uris(["file:///home/a/x.txt", "https://exemple.org"]) == ["file:///home/a/x.txt"]
    assert file_uris(None, "file:///home/a/x.txt\r\nfile:///home/a/y%20z.txt\n") == [
        "file:///home/a/x.txt",
        "file:///home/a/y%20z.txt",
    ]
    assert file_uris([], None) == []


# --- mémoire du client (moins d'allers-retours) -----------------------------------------------------------


def _counting(remote) -> list[str]:
    """Liste (méthode chemin) des requêtes envoyées au serveur par ``remote``."""
    sent: list[str] = []
    original = remote.api.request

    def request(method, path, **kwargs):
        sent.append(f"{method} {path}")
        return original(method, path, **kwargs)

    remote.api.request = request
    return sent


def test_cache_keeps_rarely_changing_lists(remote, local):
    sent = _counting(remote)
    remote.projects.create(ProjectIn(name="Maison"))
    remote.tags.create(TagIn(name="urgent"))
    sent.clear()
    for _ in range(3):
        assert [p.name for p in remote.projects.list()] == ["Maison"]
        assert [t.name for t in remote.tags.list()] == ["urgent"]
        remote.users_public()
        remote.account.me()
    # Une seule fois chacun (le compte était déjà en mémoire : lu à la création de la source de données).
    assert sent == ["GET /projects", "GET /tags", "GET /users"]

    # Écriture de ce poste : la liste concernée est relue, pas les autres.
    remote.projects.create(ProjectIn(name="Travail"))
    sent.clear()
    assert [p.name for p in remote.projects.list()] == ["Maison", "Travail"]
    remote.tags.list()
    assert sent == ["GET /projects"]

    # Modification venue d'ailleurs, signalée par le temps réel.
    local.tags.create(TagIn(name="plus tard"))
    remote.api.cache.on_change(["tag"])
    assert sorted(t.name for t in remote.tags.list()) == ["plus tard", "urgent"]


def test_undo_status_comes_with_each_write(remote, local):
    sent = _counting(remote)
    task = remote.tasks.create(TaskCreate(title="Courses"))
    remote.tasks.update(task.id, TaskPatch(title="Courses du samedi"))
    sent.clear()
    status = remote.undo.status()
    assert sent == []  # donné par la réponse de l'écriture (en-tête X-Organizer-Undo)
    assert status == local.undo.status() and status.undo_label
    remote.undo.undo()
    assert remote.undo.status() == local.undo.status()
    assert sent == ["POST /undo"]
    # Modification faite sur un autre appareil : l'état est relu.
    local.tasks.create(TaskCreate(title="Ailleurs"))
    remote.api.cache.on_change(["task"])
    assert remote.undo.status() == local.undo.status()
    assert sent[-1] == "GET /undo"


def test_undo_brings_back_a_deleted_project(remote):
    project = remote.projects.create(ProjectIn(name="Maison"))
    assert [p.name for p in remote.projects.list()] == ["Maison"]
    remote.projects.delete(project.id)
    assert remote.projects.list() == []
    remote.undo.undo()  # sans attendre l'événement temps réel
    assert [p.name for p in remote.projects.list()] == ["Maison"]


def test_prefs_are_remembered_and_copied(remote):
    sent = _counting(remote)
    remote.account.set_pref("view:tasks", {"filter": {"status": ["done"]}})
    view = remote.account.get_pref("view:tasks")
    view["filter"]["status"].append("cancelled")  # l'appelant modifie sa copie…
    assert remote.account.get_pref("view:tasks") == {"filter": {"status": ["done"]}}  # … pas la mémoire
    assert sent == ["PUT /users/me/prefs/view%3Atasks"]


def test_reconnection_forgets_everything(remote):
    sent = _counting(remote)
    remote.tags.list()
    remote.api.cache.on_change(None)  # flux temps réel rétabli : des modifications ont pu être manquées
    remote.tags.list()
    assert sent == ["GET /tags", "GET /tags"]


def test_cache_expires():
    from organizer.client.cache import RemoteCache

    now = [0.0]
    cache = RemoteCache(ttl=300, short_ttl=60, clock=lambda: now[0])
    loads = []
    assert cache.get("users", lambda: loads.append(1) or ["a"]) == ["a"]
    cache.get("projects", lambda: loads.append(2) or ["p"], tables=["project"])
    now[0] = 61  # les comptes (sans événement) sont relus au bout d'une minute, les projets non
    cache.get("users", lambda: loads.append(1) or ["a"])
    cache.get("projects", lambda: loads.append(2) or ["p"], tables=["project"])
    assert loads == [1, 2, 1]


def test_undo_header_only_for_desktop_writes(state, http, alice_user):
    from organizer.core.events import UNDO_HEADER

    token, _ = state.auth.create_session(alice_user.id, kind="api")
    headers = {"Authorization": f"Bearer {token}"}
    r = http.post("/api/v1/tasks", json={"title": "Pain"}, headers=headers)
    assert r.status_code == 201
    assert json.loads(r.headers[UNDO_HEADER]) == {"undo_label": "Créer « Pain »", "redo_label": None}
    assert UNDO_HEADER.lower() not in http.get("/api/v1/undo", headers=headers).headers
