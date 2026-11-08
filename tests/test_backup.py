"""Sauvegarde : archive .tar (base cohérente, pièces jointes, manifeste), route d'export, jetons."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import sqlite3
import subprocess
import tarfile

import pytest
import uvicorn
from fastapi.testclient import TestClient

from organizer import __version__
from organizer.config import Settings
from organizer.core.errors import Forbidden, NotFound
from organizer.core.schemas import AdminUserPatch, TaskCreate
from organizer.core.services.account import AccountService
from organizer.server.backup import MANIFEST_NAME, BackupArchive
from organizer.server.state import create_state
from organizer.server.wiring import create_api_app

API = "/api/v1"
LOCAL = ("127.0.0.1", 40000)  # le script de sauvegarde, sur le Pi
LAN = ("192.168.1.50", 40000)  # une machine de la maison
INTERNET = ("86.245.12.7", 40000)


@pytest.fixture
def state(tmp_path):
    st = create_state(Settings(data_dir=tmp_path / "data"))
    yield st
    st.engine.dispose()


@pytest.fixture
def alice(state):
    return state.users.create_user("alice", "motdepasse-12", "Alice", is_admin=True)


@pytest.fixture
def bob(state, alice):
    return state.users.create_user("bob", "motdepasse-12", "Bob", by=state.users.actor_for(alice.id))


def with_attachment(state, user, content: bytes = b"facture du plombier") -> str:
    sv = state.services_for(user)
    task = sv.tasks.create(TaskCreate(title="Facture"))
    return sv.attachments.upload(task.id, "facture.pdf", io.BytesIO(content)).target


def open_tar(data: bytes) -> tarfile.TarFile:
    return tarfile.open(fileobj=io.BytesIO(data))


def build(state, **kwargs) -> bytes:
    return b"".join(BackupArchive(state.settings, **kwargs).chunks())


# --- archive ----------------------------------------------------------------------------------------------


def test_archive_contents_and_manifest(state, alice, tmp_path):
    attachment = with_attachment(state, alice)
    uploads = state.settings.uploads_dir
    (uploads / "abc123.part").write_bytes(b"envoi en cours")  # ignoré
    (uploads / "notes.txt").write_bytes(b"fichier sans rapport")  # ignoré (pas un identifiant)

    data = build(state)
    assert len(data) % tarfile.RECORDSIZE == 0
    tar = open_tar(data)
    names = tar.getnames()
    assert names == [
        "organizer.db",
        "uploads",
        f"uploads/{attachment}",
        MANIFEST_NAME,
    ]  # manifeste en dernier
    assert tar.extractfile(f"uploads/{attachment}").read() == b"facture du plombier"

    manifest = json.loads(tar.extractfile(MANIFEST_NAME).read())
    assert manifest["format"] == "organizer-backup" and manifest["format_version"] == 1
    assert manifest["version"] == __version__ and manifest["includes_uploads"] is True
    assert manifest["counts"] == {"user": 1, "task": 1, "project": 0, "tag": 0, "board": 0, "attachment": 1}
    for entry in manifest["files"]:
        content = tar.extractfile(entry["name"]).read()
        assert len(content) == entry["size"] and hashlib.sha256(content).hexdigest() == entry["sha256"]

    # La base extraite est autonome (un seul fichier, sans -wal) et lisible.
    tar.extract("organizer.db", tmp_path / "out", filter="data")
    db = sqlite3.connect(tmp_path / "out" / "organizer.db")
    assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert db.execute("SELECT title FROM task").fetchall() == [("Facture",)]
    db.close()


def test_snapshot_includes_changes_still_in_wal(state, alice):
    """Les dernières modifications sont encore dans ``organizer.db-wal`` (pas recopiées dans le fichier
    principal) : l'image de la base les contient quand même."""
    state.services_for(alice).tasks.create(TaskCreate(title="Toute fraîche"))
    assert state.settings.db_path.with_name("organizer.db-wal").stat().st_size > 0
    tar = open_tar(build(state))
    db_bytes = tar.extractfile("organizer.db").read()
    db = sqlite3.connect(":memory:")
    db.deserialize(db_bytes)
    assert ("Toute fraîche",) in db.execute("SELECT title FROM task").fetchall()


def test_database_only(state, alice):
    with_attachment(state, alice)
    tar = open_tar(build(state, include_uploads=False))
    assert tar.getnames() == ["organizer.db", MANIFEST_NAME]
    manifest = json.loads(tar.extractfile(MANIFEST_NAME).read())
    assert manifest["includes_uploads"] is False and manifest["counts"]["attachment"] == 1


def test_temporary_snapshot_always_removed(state, alice):
    def leftovers():
        return sorted(p.name for p in state.settings.data_dir.glob(".backup-*"))

    archive = BackupArchive(state.settings)
    assert len(leftovers()) == 1
    chunks = archive.chunks()
    next(chunks)
    chunks.close()  # téléchargement interrompu
    assert leftovers() == []
    BackupArchive(state.settings).cleanup()  # réponse jamais envoyée
    assert leftovers() == []
    build(state)
    assert leftovers() == []


@pytest.mark.skipif(shutil.which("tar") is None, reason="tar absent")
def test_readable_by_system_tar(state, alice, tmp_path):
    attachment = with_attachment(state, alice)
    path = tmp_path / "s.tar"
    path.write_bytes(build(state))
    listing = subprocess.run(["tar", "-tf", str(path)], capture_output=True, text=True, check=True)
    assert listing.stdout.split() == ["organizer.db", "uploads/", f"uploads/{attachment}", MANIFEST_NAME]
    assert listing.stderr == ""


# --- jetons (service) -------------------------------------------------------------------------------------


def account(state, user) -> AccountService:
    return AccountService(state.users, state.auth, user.id)


def test_backup_keys_service(state, alice, bob):
    created = account(state, alice).create_backup_key("borg")
    assert created.token.startswith("orgbk_") and created.key.label == "borg"
    assert created.key.last_used_at is None
    assert [k.id for k in account(state, alice).backup_keys()] == [created.key.id]
    assert "token" not in account(state, alice).backup_keys()[0].model_dump()
    with pytest.raises(Forbidden):
        account(state, bob).backup_keys()
    with pytest.raises(Forbidden):
        account(state, bob).create_backup_key()
    with pytest.raises(Forbidden):
        account(state, bob).revoke_backup_key(created.key.id)

    used = state.auth.resolve_api_key(created.token, "backup", "127.0.0.1")
    assert used is not None and used.last_used_at is not None and used.last_used_ip == "127.0.0.1"
    assert state.auth.resolve_api_key(created.token[:-1] + "x", "backup") is None
    # Jamais accepté comme session de connexion.
    assert state.auth.resolve(created.token) is None

    account(state, alice).revoke_backup_key(created.key.id)
    assert state.auth.resolve_api_key(created.token, "backup") is None
    with pytest.raises(NotFound):
        account(state, alice).revoke_backup_key(created.key.id)


def test_key_stops_working_when_creator_is_no_longer_admin(state, alice, bob):
    account(state, alice).admin_update(bob.id, AdminUserPatch(is_admin=True))
    token = account(state, bob).create_backup_key().token
    assert state.auth.resolve_api_key(token, "backup") is not None
    account(state, alice).admin_update(bob.id, AdminUserPatch(is_admin=False))
    assert state.auth.resolve_api_key(token, "backup") is None
    account(state, alice).admin_update(bob.id, AdminUserPatch(is_admin=True))
    assert state.auth.resolve_api_key(token, "backup") is not None
    account(state, alice).admin_update(bob.id, AdminUserPatch(is_active=False))
    assert state.auth.resolve_api_key(token, "backup") is None


# --- route d'export ---------------------------------------------------------------------------------------


@pytest.fixture
def app(state):
    return create_api_app(state)


def client(app, peer=LOCAL, **headers) -> TestClient:
    return TestClient(app, client=peer, headers=headers)


def login(app, username: str) -> dict[str, str]:
    r = client(app).post(f"{API}/auth/login", json={"username": username, "password": "motdepasse-12"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_backup_route_requires_admin(app, state, alice, bob):
    with_attachment(state, alice)
    assert client(app).get(f"{API}/admin/backup").status_code == 401
    assert client(app, **login(app, "bob")).get(f"{API}/admin/backup").status_code == 403

    r = client(app, **login(app, "alice")).get(f"{API}/admin/backup")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/x-tar"
    assert r.headers["content-disposition"].startswith('attachment; filename="organizer-')
    assert r.headers["cache-control"] == "no-store"
    assert open_tar(r.content).getnames()[-1] == MANIFEST_NAME

    # Navigateur : le cookie de session suffit (bouton des réglages).
    browser = client(app)
    ticket = state.tickets.issue(alice.id, persistent=False)
    browser.get(f"/auth/complete?ticket={ticket}", follow_redirects=False)
    r = browser.get(f"{API}/admin/backup?uploads=false")
    assert r.status_code == 200 and open_tar(r.content).getnames() == ["organizer.db", MANIFEST_NAME]


def test_backup_with_key(app, state, alice, caplog):
    caplog.set_level("INFO", logger="organizer.backup")
    admin = client(app, **login(app, "alice"))
    r = admin.post(f"{API}/admin/backup-keys", json={"label": "Sauvegarde borg"})
    assert r.status_code == 201
    token, key_id = r.json()["token"], r.json()["key"]["id"]
    listed = admin.get(f"{API}/admin/backup-keys").json()
    assert [k["id"] for k in listed] == [key_id] and "token" not in listed[0]

    key = {"Authorization": f"Bearer {token}"}
    assert client(app, LOCAL, **key).get(f"{API}/admin/backup").status_code == 200
    assert client(app, LAN, **key).get(f"{API}/admin/backup?uploads=0").status_code == 200
    r = client(app, INTERNET, **key).get(f"{API}/admin/backup")
    assert r.status_code == 403 and "réseau local" in r.json()["detail"]
    # Le jeton n'ouvre rien d'autre.
    assert client(app, LOCAL, **key).get(f"{API}/auth/me").status_code == 401
    assert client(app, LOCAL, **key).get(f"{API}/admin/backup-keys").status_code == 401
    assert client(app, LOCAL, **key).get(f"{API}/tasks/reminders").status_code == 401

    used = admin.get(f"{API}/admin/backup-keys").json()[0]
    assert used["last_used_at"] is not None and used["last_used_ip"] == LAN[0]

    assert admin.delete(f"{API}/admin/backup-keys/{key_id}").status_code == 204
    assert client(app, LOCAL, **key).get(f"{API}/admin/backup").status_code == 401

    lines = [r.getMessage() for r in caplog.records if r.name == "organizer.backup"]
    assert lines[0] == "Sauvegarde demandée par le jeton 'Sauvegarde borg' depuis 127.0.0.1"
    assert lines[1] == "Sauvegarde (base seule) demandée par le jeton 'Sauvegarde borg' depuis 192.168.1.50"
    assert any("hors du réseau local" in line and "86.245.12.7" in line for line in lines)
    assert any(line.startswith("Jeton de sauvegarde inconnu ou révoqué") for line in lines)


def test_key_from_internet_behind_proxy_is_refused(state, alice):
    """Derrière Cloudflare Tunnel, la connexion vient de 127.0.0.1 (cloudflared) mais uvicorn rend au
    visiteur son adresse publique, même s'il prétend venir du réseau local."""
    config = uvicorn.Config(create_api_app(state), log_level="error")
    config.load()
    token = account(state, alice).create_backup_key().token
    headers = {"Authorization": f"Bearer {token}", "X-Forwarded-Proto": "https"}
    for forwarded in ("86.245.12.7", "192.168.1.50, 86.245.12.7"):
        visitor = TestClient(
            config.loaded_app, client=LOCAL, headers={**headers, "X-Forwarded-For": forwarded}
        )
        assert visitor.get(f"{API}/admin/backup").status_code == 403
    script = TestClient(config.loaded_app, client=LOCAL, headers={"Authorization": f"Bearer {token}"})
    assert script.get(f"{API}/admin/backup").status_code == 200


def test_backup_keys_routes_are_admin_only(app, alice, bob):
    bob_client = client(app, **login(app, "bob"))
    assert bob_client.get(f"{API}/admin/backup-keys").status_code == 403
    assert bob_client.post(f"{API}/admin/backup-keys", json={}).status_code == 403
    assert client(app).get(f"{API}/admin/backup-keys").status_code == 401
