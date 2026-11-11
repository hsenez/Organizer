"""Liens à partager : adresses (``organizer.links``), page ``/open/<type>/<id>``, adresse publique du serveur
(réglage admin, API, client bureau)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from organizer import links
from organizer.core.errors import Forbidden, InvalidOperation
from organizer.core.services.account import AccountService, normalize_public_url
from organizer.core.services.auth import AuthService


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("organizer://note/5", "note:5"),
        ("ORGANIZER://Task/12/", "task:12"),
        ("organizer:event/8", "event:8"),
        ("organizer:///note/3", "note:3"),
        ("https://organizer.blou.top/open/note/5", "note:5"),
        ("http://192.168.1.20:2603/open/task/7/", "task:7"),
        ("/open/event/9", "event:9"),
        ("https://organizer.blou.top/notes?note=5", "note:5"),
        ("http://localhost:2603/tasks?task=12", "task:12"),
        ("https://x.fr/calendar?event=8", "event:8"),
        ("https://x.fr/tasks?task=12&tab=2", None),  # autre chose qu'un simple lien d'élément
        ("https://jira.fr/browse?task=12", None),
        ("https://x.fr/open/projet/3", None),
        ("note:5", None),  # (lien interne : traité par rules.parse_ref)
        ("organizer://n'importe-quoi", None),
        ("ftp://x.fr/open/note/5", None),
        ("du texte", None),
    ],
)
def test_from_url(url, expected):
    assert links.from_url(url) == expected


def test_paths():
    assert links.page_path("note", 5) == "/notes?note=5"
    assert links.page_path("task", 12) == "/tasks?task=12"
    assert links.page_path("event", 8) == "/calendar?event=8"
    assert links.open_path("note", 5) == "/open/note/5"
    assert links.scheme_url("task", 3) == "organizer://task/3"
    assert links.split_ref("event:8") == ("event", 8) and links.split_ref("x") is None


def test_normalize_public_url():
    assert normalize_public_url(" organizer.blou.top/ ") == "https://organizer.blou.top"
    assert normalize_public_url("http://192.168.1.20:2603") == "http://192.168.1.20:2603"
    assert normalize_public_url("") is None and normalize_public_url(None) is None
    for bad in ("ftp://x.fr", "https://x.fr/?a=1", "https://"):
        with pytest.raises(InvalidOperation):
            normalize_public_url(bad)


def test_public_url_admin_only(engine, users, settings, alice, bob):
    auth = AuthService(engine, settings)
    admin = AccountService(users, auth, alice.actor.id)
    other = AccountService(users, auth, bob.actor.id)
    assert admin.public_url() is None
    assert admin.set_public_url("organizer.blou.top") == "https://organizer.blou.top"
    assert other.public_url() == "https://organizer.blou.top"  # lisible par tous
    with pytest.raises(Forbidden):
        other.set_public_url("https://ailleurs.fr")
    assert admin.set_public_url("") is None and other.public_url() is None


# --- serveur : page /open et API --------------------------------------------------------------------------


@pytest.fixture
def server(tmp_path):
    from organizer.config import Settings
    from organizer.server.state import create_state
    from organizer.server.wiring import create_api_app

    state = create_state(Settings(data_dir=tmp_path))
    return state, TestClient(create_api_app(state))


def test_open_page_without_session(server):
    _, http = server
    response = http.get("/open/note/5")
    assert response.status_code == 200 and "text/html" in response.headers["content-type"]
    assert "organizer://note/5" in response.text and "/notes?note=5" in response.text
    assert "Ouvrir cette note" in response.text
    assert http.get("/open/projet/5").status_code == 422
    assert http.get("/open/note/abc").status_code == 422


def test_public_url_api(server):
    state, http = server
    alice = state.users.create_user("alice", "motdepasse-12", "Alice")
    state.users.create_user("bob", "motdepasse-12", "Bob", by=state.users.actor_for(alice.id))
    assert http.get("/api/v1/server/public-url").status_code == 401

    def login(name):
        token = http.post("/api/v1/auth/login", json={"username": name, "password": "motdepasse-12"}).json()
        return {"Authorization": f"Bearer {token['token']}"}

    admin, bob = login("alice"), login("bob")
    assert http.get("/api/v1/server/public-url", headers=bob).json() == {"url": None}
    response = http.put("/api/v1/server/public-url", json={"url": "organizer.blou.top"}, headers=admin)
    assert response.json() == {"url": "https://organizer.blou.top"}
    assert http.get("/api/v1/server/public-url", headers=bob).json() == {"url": "https://organizer.blou.top"}
    assert http.put("/api/v1/server/public-url", json={"url": "x.fr"}, headers=bob).status_code == 403
    assert http.put("/api/v1/server/public-url", json={"url": "ftp://x"}, headers=admin).status_code == 422
