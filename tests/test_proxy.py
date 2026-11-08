"""Fonctionnement derrière un proxy (Cloudflare Tunnel…) : vraie IP du visiteur, cookie ``Secure``, en-têtes
de sécurité.

Les requêtes passent par l'application **telle qu'uvicorn la charge** (``uvicorn.Config(...).load()``), donc
avec son ``ProxyHeadersMiddleware`` et ses réglages par défaut, comme dans ``ui.run()`` qui ne les change pas.
"""

from __future__ import annotations

import pytest
import uvicorn
from fastapi.testclient import TestClient

from organizer.config import Settings
from organizer.server.security import COOKIE_NAME, HSTS_MAX_AGE
from organizer.server.state import create_state
from organizer.server.wiring import create_api_app

API = "/api/v1"
PROXY = ("127.0.0.1", 40000)  # cloudflared, sur le Pi lui-même
LAN = ("192.168.1.50", 40000)  # une machine du réseau local qui se connecte directement


@pytest.fixture
def state(tmp_path):
    st = create_state(Settings(data_dir=tmp_path, login_max_failures=3))
    yield st
    st.engine.dispose()


@pytest.fixture
def uvicorn_app(state):
    config = uvicorn.Config(create_api_app(state), log_level="error")
    config.load()
    return config.loaded_app


@pytest.fixture
def admin(state):
    client = TestClient(create_api_app(state))
    r = client.post(f"{API}/setup", json={"username": "alice", "password": "motdepasse"})
    return r.json()["user"]


def via(app, peer, **headers) -> TestClient:
    return TestClient(app, client=peer, headers=headers)


def forwarded(ip: str = "86.245.12.7", proto: str = "https") -> dict[str, str]:
    return {"X-Forwarded-For": ip, "X-Forwarded-Proto": proto}


def login_cookie(client: TestClient, state, user_id: int) -> str:
    ticket = state.tickets.issue(user_id, persistent=True)
    r = client.get(f"/auth/complete?ticket={ticket}", follow_redirects=False)
    return r.headers["set-cookie"]


# --- vraie adresse IP : anti force brute -------------------------------------------------------------------


def _fail(client: TestClient) -> int:
    return client.post(f"{API}/auth/login", json={"username": "alice", "password": "faux"}).status_code


def test_failures_are_counted_per_visitor_behind_proxy(uvicorn_app, admin):
    attacker = via(uvicorn_app, PROXY, **{"X-Forwarded-For": "203.0.113.9"})
    assert [_fail(attacker) for _ in range(4)] == [401, 401, 401, 429]
    # Un autre visiteur passant par le même proxy n'est pas bloqué : le compte reste utilisable.
    owner = via(uvicorn_app, PROXY, **{"X-Forwarded-For": "86.245.12.7"})
    r = owner.post(f"{API}/auth/login", json={"username": "alice", "password": "motdepasse"})
    assert r.status_code == 200


def test_forwarded_headers_ignored_from_untrusted_peer(uvicorn_app, admin):
    """Une machine du réseau local ne peut pas se faire passer pour une autre en écrivant l'en-tête."""
    for i in range(3):
        assert _fail(via(uvicorn_app, LAN, **{"X-Forwarded-For": f"10.0.0.{i}"})) == 401
    assert _fail(via(uvicorn_app, LAN, **{"X-Forwarded-For": "10.0.0.99"})) == 429


# --- cookie Secure -----------------------------------------------------------------------------------------


def test_cookie_secure_when_visitor_uses_https_through_proxy(uvicorn_app, state, admin):
    cookie = login_cookie(via(uvicorn_app, PROXY, **forwarded()), state, admin["id"])
    assert f"{COOKIE_NAME}=" in cookie and "Secure" in cookie and "HttpOnly" in cookie


def test_cookie_not_secure_over_plain_http(uvicorn_app, state, admin):
    """Accès direct sur le réseau local (http://raspberrypi.local:2603) : un cookie Secure n'y serait jamais
    renvoyé par le navigateur, la connexion serait impossible."""
    cookie = login_cookie(via(uvicorn_app, LAN), state, admin["id"])
    assert f"{COOKIE_NAME}=" in cookie and "Secure" not in cookie


def test_cookie_not_secure_when_untrusted_peer_claims_https(uvicorn_app, state, admin):
    cookie = login_cookie(via(uvicorn_app, LAN, **forwarded()), state, admin["id"])
    assert "Secure" not in cookie


def test_cookie_secure_when_server_itself_serves_https(state, admin):
    client = TestClient(create_api_app(state), base_url="https://raspberrypi.local:2603")
    assert "Secure" in login_cookie(client, state, admin["id"])


def test_logout_clears_cookie_with_same_attributes(uvicorn_app, state, admin):
    client = via(uvicorn_app, PROXY, **forwarded())
    login_cookie(client, state, admin["id"])
    cleared = client.get("/auth/logout", follow_redirects=False).headers["set-cookie"]
    assert f'{COOKIE_NAME}=""' in cleared and "Secure" in cleared


# --- en-têtes de sécurité ----------------------------------------------------------------------------------


def test_security_headers_on_every_response(uvicorn_app):
    for path in (f"{API}/version", "/manifest.webmanifest", f"{API}/auth/me"):
        r = via(uvicorn_app, LAN).get(path)
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "SAMEORIGIN"
        assert r.headers["referrer-policy"] == "same-origin"


def test_hsts_only_for_https_visitors(uvicorn_app):
    assert "strict-transport-security" not in via(uvicorn_app, LAN).get(f"{API}/version").headers
    r = via(uvicorn_app, PROXY, **forwarded()).get(f"{API}/version")
    assert r.headers["strict-transport-security"] == f"max-age={HSTS_MAX_AGE}"
    # Le proxy dit « http » (cas d'une redirection non encore faite) : pas de HSTS.
    r = via(uvicorn_app, PROXY, **forwarded(proto="http")).get(f"{API}/version")
    assert "strict-transport-security" not in r.headers


def test_response_headers_not_overridden(state, admin):
    """Une réponse qui fixe déjà un en-tête (ex. pièces jointes) garde le sien, sans doublon."""
    client = TestClient(create_api_app(state))
    token = client.post(f"{API}/auth/login", json={"username": "alice", "password": "motdepasse"}).json()
    h = {"Authorization": f"Bearer {token['token']}"}
    task = client.post(f"{API}/tasks", json={"title": "Facture"}, headers=h).json()
    up = client.post(
        f"{API}/tasks/{task['id']}/attachments",
        files={"file": ("page.html", b"<script>alert(1)</script>", "text/html")},
        headers=h,
    )
    assert up.status_code == 201, up.text
    r = client.get(f"{API}/attachments/{up.json()['target']}", headers=h)
    assert r.status_code == 200
    assert r.headers.get_list("x-content-type-options") == ["nosniff"]
    assert r.headers["content-security-policy"] == "sandbox"
