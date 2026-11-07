"""API REST et authentification (cookies, jetons, tickets)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from organizer.config import Settings
from organizer.server.security import COOKIE_NAME
from organizer.server.state import create_state
from organizer.server.wiring import create_api_app

API = "/api/v1"


@pytest.fixture
def state(tmp_path):
    st = create_state(Settings(data_dir=tmp_path, login_max_failures=3, max_upload_mb=1))
    yield st
    st.engine.dispose()


@pytest.fixture
def client(state):
    return TestClient(create_api_app(state))


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_token(client):
    r = client.post(
        f"{API}/setup", json={"username": "alice", "password": "motdepasse", "display_name": "Alice"}
    )
    assert r.status_code == 201
    return r.json()["token"]


@pytest.fixture
def bob_token(client, admin_token):
    r = client.post(
        f"{API}/users", json={"username": "bob", "password": "motdepasse"}, headers=bearer(admin_token)
    )
    assert r.status_code == 201
    return client.post(f"{API}/auth/login", json={"username": "bob", "password": "motdepasse"}).json()[
        "token"
    ]


# --- initialisation et connexion --------------------------------------------------------------------------


def test_setup_only_once(client):
    assert client.get(f"{API}/setup").json() == {"needs_setup": True}
    r = client.post(f"{API}/setup", json={"username": "alice", "password": "motdepasse"})
    assert r.status_code == 201 and r.json()["user"]["is_admin"]
    assert client.get(f"{API}/setup").json() == {"needs_setup": False}
    again = client.post(f"{API}/setup", json={"username": "pirate", "password": "motdepasse"})
    assert again.status_code == 409


def test_login_me_logout(client, admin_token):
    r = client.post(
        f"{API}/auth/login", json={"username": "ALICE", "password": "motdepasse", "device_name": "PC"}
    )
    assert r.status_code == 200
    token = r.json()["token"]
    assert r.json()["session"]["label"] == "PC"
    assert client.get(f"{API}/auth/me", headers=bearer(token)).json()["username"] == "alice"
    assert client.post(f"{API}/auth/logout", headers=bearer(token)).status_code == 204
    assert client.get(f"{API}/auth/me", headers=bearer(token)).status_code == 401


def test_requires_authentication(client, admin_token):
    assert client.get(f"{API}/auth/me").status_code == 401
    assert client.get(f"{API}/tags", headers=bearer("faux-jeton")).status_code == 401


def test_bad_password_and_throttling(client, admin_token):
    for _ in range(3):
        r = client.post(f"{API}/auth/login", json={"username": "alice", "password": "mauvais"})
        assert r.status_code == 401
    blocked = client.post(f"{API}/auth/login", json={"username": "alice", "password": "motdepasse"})
    assert blocked.status_code == 429
    assert "Réessayez" in blocked.json()["detail"]


def test_sessions_list_and_revoke(client, admin_token):
    other = client.post(f"{API}/auth/login", json={"username": "alice", "password": "motdepasse"}).json()
    sessions = client.get(f"{API}/auth/sessions", headers=bearer(admin_token)).json()
    assert len(sessions) == 2
    assert sum(s["current"] for s in sessions) == 1
    r = client.delete(f"{API}/auth/sessions/{other['session']['id']}", headers=bearer(admin_token))
    assert r.status_code == 204
    assert client.get(f"{API}/auth/me", headers=bearer(other["token"])).status_code == 401


def test_password_change_revokes_other_sessions(client, admin_token):
    other = client.post(f"{API}/auth/login", json={"username": "alice", "password": "motdepasse"}).json()[
        "token"
    ]
    r = client.post(
        f"{API}/users/me/password",
        json={"old_password": "motdepasse", "new_password": "nouveau-mdp"},
        headers=bearer(admin_token),
    )
    assert r.status_code == 204
    assert client.get(f"{API}/auth/me", headers=bearer(admin_token)).status_code == 200
    assert client.get(f"{API}/auth/me", headers=bearer(other)).status_code == 401
    wrong = client.post(
        f"{API}/users/me/password",
        json={"old_password": "faux", "new_password": "encore-un"},
        headers=bearer(admin_token),
    )
    assert wrong.status_code == 422


def test_admin_rights(client, admin_token, bob_token):
    assert client.get(f"{API}/users/all", headers=bearer(bob_token)).status_code == 403
    assert (
        client.post(
            f"{API}/users", json={"username": "c", "password": "motdepasse"}, headers=bearer(bob_token)
        ).status_code
        == 403
    )
    users = client.get(f"{API}/users", headers=bearer(bob_token)).json()
    assert {u["username"] for u in users} == {"alice", "bob"}
    assert "is_admin" not in users[0]  # vue publique
    bob_id = next(u["id"] for u in users if u["username"] == "bob")
    r = client.patch(f"{API}/users/{bob_id}", json={"is_active": False}, headers=bearer(admin_token))
    assert r.status_code == 200 and not r.json()["is_active"]
    assert client.get(f"{API}/auth/me", headers=bearer(bob_token)).status_code == 401
    assert (
        client.post(f"{API}/auth/login", json={"username": "bob", "password": "motdepasse"}).status_code
        == 401
    )


def test_profile_update(client, admin_token):
    r = client.patch(
        f"{API}/users/me", json={"theme": "dark", "reminder_offset_days": 5}, headers=bearer(admin_token)
    )
    assert r.json()["theme"] == "dark" and r.json()["reminder_offset_days"] == 5
    assert (
        client.patch(f"{API}/users/me", json={"theme": "violet"}, headers=bearer(admin_token)).status_code
        == 422
    )


# --- cookies du navigateur --------------------------------------------------------------------------------


def test_web_ticket_sets_cookie_and_logout_clears_it(client, state, admin_token):
    user_id = client.get(f"{API}/auth/me", headers=bearer(admin_token)).json()["id"]
    ticket = state.tickets.issue(user_id, persistent=True, label="Firefox")
    r = client.get(f"/auth/complete?ticket={ticket}&next=/tasks", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/tasks"
    set_cookie = r.headers["set-cookie"]
    assert f"{COOKIE_NAME}=" in set_cookie and "HttpOnly" in set_cookie and "Max-Age=2592000" in set_cookie
    # Le cookie suffit pour l'API.
    assert client.get(f"{API}/auth/me").json()["username"] == "alice"
    # Ticket à usage unique.
    again = client.get(f"/auth/complete?ticket={ticket}", follow_redirects=False)
    assert again.headers["location"] == "/login?expired=1"
    out = client.get("/auth/logout", follow_redirects=False)
    assert out.headers["location"] == "/login"
    assert client.get(f"{API}/auth/me").status_code == 401


def test_session_cookie_without_remember_me(client, state, admin_token):
    user_id = client.get(f"{API}/auth/me", headers=bearer(admin_token)).json()["id"]
    ticket = state.tickets.issue(user_id, persistent=False)
    r = client.get(f"/auth/complete?ticket={ticket}", follow_redirects=False)
    assert "Max-Age" not in r.headers["set-cookie"]  # cookie de session : disparaît à la fermeture


@pytest.mark.parametrize("target", ["//evil.example", "https://evil.example", "/\\evil", ""])
def test_open_redirect_blocked(client, state, admin_token, target):
    user_id = client.get(f"{API}/auth/me", headers=bearer(admin_token)).json()["id"]
    ticket = state.tickets.issue(user_id, persistent=False)
    r = client.get("/auth/complete", params={"ticket": ticket, "next": target}, follow_redirects=False)
    assert r.headers["location"] == "/"


def test_invalid_cookie_is_cleared(client, admin_token):
    client.cookies.set(COOKIE_NAME, "perime")
    r = client.get(f"{API}/auth/me")
    assert r.status_code == 401
    assert f'{COOKIE_NAME}=""' in r.headers.get("set-cookie", "")


# --- données ----------------------------------------------------------------------------------------------


def test_task_lifecycle_and_undo(client, admin_token):
    h = bearer(admin_token)
    tag = client.post(f"{API}/tags", json={"name": "maison", "is_public": True}, headers=h).json()
    created = client.post(
        f"{API}/tasks",
        json={"title": "Peindre", "importance": 4, "due_date": "2026-12-01", "tag_ids": [tag["id"]]},
        headers=h,
    )
    assert created.status_code == 201
    task = created.json()
    assert task["importance"] == 4 and task["tags"][0]["name"] == "maison"

    patched = client.patch(
        f"{API}/tasks/{task['id']}", json={"status": "in_progress", "due_date": None}, headers=h
    )
    assert patched.json()["status"] == "in_progress" and patched.json()["due_date"] is None

    found = client.post(f"{API}/tasks/query", json={"filter": {"text": "peindre"}}, headers=h).json()
    assert [t["title"] for t in found] == ["Peindre"]

    assert client.get(f"{API}/undo", headers=h).json()["undo_label"].startswith("Modifier")
    undone = client.post(f"{API}/undo", headers=h).json()
    assert undone["action"] == "undo"
    assert client.get(f"{API}/tasks/{task['id']}", headers=h).json()["due_date"] == "2026-12-01"
    assert client.post(f"{API}/redo", headers=h).json()["action"] == "redo"


def test_errors_are_french_json(client, admin_token):
    h = bearer(admin_token)
    r = client.get(f"{API}/tasks/999", headers=h)
    assert r.status_code == 404 and r.json() == {"detail": "Tâche introuvable."}
    parent = client.post(f"{API}/tasks", json={"title": "P"}, headers=h).json()
    sub = client.post(f"{API}/tasks", json={"title": "S", "parent_id": parent["id"]}, headers=h).json()
    other = client.post(f"{API}/tasks", json={"title": "O"}, headers=h).json()
    r = client.post(f"{API}/tasks/{other['id']}/attach", json={"parent_id": sub["id"]}, headers=h)
    assert r.status_code == 422 and "un seul niveau" in r.json()["detail"]


def test_sharing_through_api(client, admin_token, bob_token):
    task = client.post(f"{API}/tasks", json={"title": "Commun"}, headers=bearer(admin_token)).json()
    assert client.get(f"{API}/tasks/{task['id']}", headers=bearer(bob_token)).status_code == 404
    bob_id = client.get(f"{API}/auth/me", headers=bearer(bob_token)).json()["id"]
    r = client.put(
        f"{API}/tasks/{task['id']}/shares", json={"user_ids": [bob_id]}, headers=bearer(admin_token)
    )
    assert r.json()["shared_with"] == [bob_id]
    assert client.get(f"{API}/tasks/{task['id']}", headers=bearer(bob_token)).json()["title"] == "Commun"
    assert client.delete(f"{API}/tasks/{task['id']}", headers=bearer(bob_token)).status_code == 403


def test_projects_and_tags_routes(client, admin_token):
    h = bearer(admin_token)
    p = client.post(f"{API}/projects", json={"name": "Boulot", "emoji": "💼"}, headers=h).json()
    assert client.patch(f"{API}/projects/{p['id']}", json={"archived": True}, headers=h).json()["archived"]
    assert client.get(f"{API}/projects", headers=h).json() == []
    assert len(client.get(f"{API}/projects?include_archived=true", headers=h).json()) == 1
    a = client.post(f"{API}/tags", json={"name": "a"}, headers=h).json()
    b = client.post(f"{API}/tags", json={"name": "b"}, headers=h).json()
    assert (
        client.post(f"{API}/tags/{a['id']}/merge", json={"target_id": b["id"]}, headers=h).json()["name"]
        == "b"
    )
    assert client.post(f"{API}/tags", json={"name": "B"}, headers=h).status_code == 422


# --- pièces jointes ---------------------------------------------------------------------------------------


def test_attachments_upload_download_and_access(client, admin_token, bob_token):
    h = bearer(admin_token)
    task = client.post(f"{API}/tasks", json={"title": "Avec fichier"}, headers=h).json()
    up = client.post(
        f"{API}/tasks/{task['id']}/attachments",
        files={"file": ("../../rapport final.pdf", b"%PDF-1.4 contenu", "application/pdf")},
        headers=h,
    )
    assert up.status_code == 201
    link = up.json()
    assert link["kind"] == "attachment" and link["label"] == "rapport final.pdf"

    got = client.get(f"{API}/attachments/{link['target']}", headers=h)
    assert got.status_code == 200 and got.content == b"%PDF-1.4 contenu"
    assert got.headers["content-type"] == "application/pdf"
    assert got.headers["content-disposition"].startswith("inline")
    forced = client.get(f"{API}/attachments/{link['target']}?download=true", headers=h)
    assert forced.headers["content-disposition"].startswith("attachment")

    # Bob n'y a pas accès… jusqu'à ce que la tâche soit partagée.
    assert client.get(f"{API}/attachments/{link['target']}", headers=bearer(bob_token)).status_code == 404
    bob_id = client.get(f"{API}/auth/me", headers=bearer(bob_token)).json()["id"]
    client.put(f"{API}/tasks/{task['id']}/shares", json={"user_ids": [bob_id]}, headers=h)
    assert client.get(f"{API}/attachments/{link['target']}", headers=bearer(bob_token)).status_code == 200


def test_dangerous_attachment_is_never_inline(client, admin_token):
    h = bearer(admin_token)
    task = client.post(f"{API}/tasks", json={"title": "T"}, headers=h).json()
    link = client.post(
        f"{API}/tasks/{task['id']}/attachments",
        files={"file": ("page.html", b"<script>alert(1)</script>", "text/html")},
        headers=h,
    ).json()
    got = client.get(f"{API}/attachments/{link['target']}", headers=h)
    assert got.headers["content-disposition"].startswith("attachment")
    assert got.headers["content-type"] == "application/octet-stream"
    assert got.headers["content-security-policy"] == "sandbox"


def test_attachment_size_limit(client, admin_token, state):
    h = bearer(admin_token)
    task = client.post(f"{API}/tasks", json={"title": "T"}, headers=h).json()
    big = b"x" * (1024 * 1024 + 1)
    r = client.post(f"{API}/tasks/{task['id']}/attachments", files={"file": ("gros.bin", big)}, headers=h)
    assert r.status_code == 422 and "trop volumineux" in r.json()["detail"]
    assert list(state.settings.uploads_dir.iterdir()) == []  # aucun fichier orphelin


def test_attachment_link_cannot_be_forged(client, admin_token):
    h = bearer(admin_token)
    task = client.post(f"{API}/tasks", json={"title": "T"}, headers=h).json()
    r = client.post(
        f"{API}/tasks/{task['id']}/links", json={"kind": "attachment", "target": "abc"}, headers=h
    )
    assert r.status_code == 422


def test_prefs_roundtrip(client, admin_token):
    h = bearer(admin_token)
    assert client.get(f"{API}/users/me/prefs/tasks", headers=h).json() is None
    value = {"filter": {"text": "pain"}, "sort": {"key": "due"}, "group": "project"}
    assert client.put(f"{API}/users/me/prefs/tasks", json=value, headers=h).status_code == 204
    assert client.get(f"{API}/users/me/prefs/tasks", headers=h).json() == value


def test_duplicate_route(client, admin_token):
    h = bearer(admin_token)
    task = client.post(f"{API}/tasks", json={"title": "Modèle"}, headers=h).json()
    copy = client.post(f"{API}/tasks/{task['id']}/duplicate", headers=h)
    assert copy.status_code == 201 and copy.json()["title"] == "Modèle (copie)"
