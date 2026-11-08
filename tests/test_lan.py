"""Passage automatique par le réseau local (client bureau) : adresses et clé données par le serveur, preuve
d'identité réservée au réseau local, bascule et retour du client."""

from __future__ import annotations

import os
import stat

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from organizer.client.api import ApiClient
from organizer.client.config import ClientConfig
from organizer.client.lan import RECHECK_AFTER, LanSwitch, expected_proof
from organizer.config import Settings
from organizer.core.schemas import TaskCreate
from organizer.server import local_access
from organizer.server.state import create_state
from organizer.server.wiring import create_api_app

API = "/api/v1"
PUBLIC = "https://organizer.example.org"
LOCAL = "http://192.168.1.13:2603"
HOME_PC = ("192.168.1.50", 40000)  # le poste, à la maison
INTERNET = ("86.245.12.7", 40000)  # le poste, ailleurs (vu à travers Cloudflare)


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv(local_access.ENV_URLS, LOCAL)
    st = create_state(Settings(data_dir=tmp_path / "data"))
    yield st
    st.engine.dispose()


@pytest.fixture
def alice(state):
    return state.users.create_user("alice", "motdepasse-12", "Alice")


def token_for(state, user) -> str:
    return state.auth.create_session(user.id, kind="api")[0]


# --- serveur ----------------------------------------------------------------------------------------------


def test_local_urls_from_listening_address(monkeypatch):
    monkeypatch.delenv(local_access.ENV_URLS, raising=False)
    everywhere = Settings(host="0.0.0.0", port=2603)
    assert local_access.local_urls(everywhere, ["192.168.1.13"]) == ["http://192.168.1.13:2603"]
    assert local_access.local_urls(Settings(host="127.0.0.1"), ["192.168.1.13"]) == []  # tunnel seulement
    assert local_access.local_urls(Settings(host="192.168.1.13", port=2700)) == ["http://192.168.1.13:2700"]
    https = Settings(host="0.0.0.0", ssl_cert="c.pem", ssl_key="k.pem")
    assert local_access.local_urls(https, ["10.0.0.5"]) == ["https://10.0.0.5:2603"]
    monkeypatch.setenv(local_access.ENV_URLS, "http://pi.lan:2603/, http://10.0.0.5:2603")
    assert local_access.local_urls(everywhere) == ["http://pi.lan:2603", "http://10.0.0.5:2603"]
    assert all(local_access._is_lan(a) for a in local_access.machine_addresses())


def test_instance_key_is_kept_and_private(tmp_path):
    key = local_access.instance_key(tmp_path)
    assert len(key) == 32 and local_access.instance_key(tmp_path) == key
    if os.name == "posix":
        assert stat.S_IMODE((tmp_path / local_access.KEY_FILE).stat().st_mode) == 0o600


def test_local_access_info_needs_a_session(state, alice):
    bob = state.users.create_user("bob", "motdepasse-12", "Bob", by=state.users.actor_for(alice.id))
    app = create_api_app(state)
    assert TestClient(app).get(f"{API}/local-access").status_code == 401
    info = (
        TestClient(app, headers={"Authorization": f"Bearer {token_for(state, alice)}"})
        .get(f"{API}/local-access")
        .json()
    )
    assert info["urls"] == [LOCAL] and info["user_id"] == alice.id and len(info["key"]) == 64
    bob_info = (
        TestClient(app, headers={"Authorization": f"Bearer {token_for(state, bob)}"})
        .get(f"{API}/local-access")
        .json()
    )
    assert bob_info["key"] != info["key"]  # Bob ne peut pas se faire passer pour le serveur auprès d'Alice


def test_proof_only_on_the_local_network(state, alice):
    key = local_access.user_key(state.local_key, alice.id)
    nonce = "0123456789abcdef0123456789abcdef"
    app = create_api_app(state)
    r = TestClient(app, client=HOME_PC).get(
        f"{API}/local-access/proof", params={"user": alice.id, "nonce": nonce}
    )
    assert r.status_code == 200 and r.json()["proof"] == expected_proof(key, nonce)
    r = TestClient(app, client=INTERNET).get(
        f"{API}/local-access/proof", params={"user": alice.id, "nonce": nonce}
    )
    assert r.status_code == 403
    bad = TestClient(app, client=HOME_PC).get(f"{API}/local-access/proof", params={"user": 1, "nonce": "x"})
    assert bad.status_code == 422


def test_proof_refused_through_the_tunnel(state, alice):
    """Un faux serveur ne peut pas faire calculer la preuve par le vrai à travers Internet : derrière
    Cloudflare, la demande garde l'adresse publique de son auteur, même s'il prétend venir du réseau local."""
    config = uvicorn.Config(create_api_app(state), log_level="error")
    config.load()
    for forwarded in ("86.245.12.7", "192.168.1.50, 86.245.12.7"):
        via_tunnel = TestClient(
            config.loaded_app, client=("127.0.0.1", 40000), headers={"X-Forwarded-For": forwarded}
        )
        r = via_tunnel.get(f"{API}/local-access/proof", params={"user": alice.id, "nonce": "ab" * 16})
        assert r.status_code == 403


# --- client -----------------------------------------------------------------------------------------------


class Net:
    """Réseau simulé : l'adresse publique et l'adresse locale mènent chacune à un serveur de test, vu
    depuis l'adresse IP que l'on veut ; ``sent`` note les requêtes arrivées par chaque adresse."""

    def __init__(self, public_app, local_app=None):
        self.sent: dict[str, list[str]] = {PUBLIC: [], LOCAL: []}
        self.public = self._client(public_app, PUBLIC, INTERNET)
        self.local = self._client(local_app, LOCAL, HOME_PC) if local_app is not None else self._dead(LOCAL)

    def _client(self, app, base, peer) -> TestClient:
        client = TestClient(app, base_url=base, client=peer)
        original = client.request

        def request(method, url, **kwargs):
            self.sent[base].append(f"{method} {url}")
            return original(method, url, **kwargs)

        client.request = request
        return client

    def _dead(self, base) -> httpx.Client:
        def refuse(request):
            self.sent[base].append(f"{request.method} {request.url.path}")
            raise httpx.ConnectError("injoignable", request=request)

        return httpx.Client(base_url=base, transport=httpx.MockTransport(refuse))

    def factory(self, url: str):
        return self.local if url == LOCAL else self.public


def switch_for(net: Net, token: str, config: ClientConfig | None = None, clock=None):
    api = ApiClient(PUBLIC, token, http=net.public)
    config = config or ClientConfig(server=PUBLIC, token=token)
    saved = []
    lan = LanSwitch(
        lambda: config,
        lambda: saved.append(1),
        lambda: api,
        http_factory=net.factory,
        **({"clock": clock} if clock else {}),
    )
    return api, lan, config


def test_client_switches_to_the_local_network(state, alice):
    app = create_api_app(state)
    net = Net(app, app)
    api, lan, config = switch_for(net, token_for(state, alice))
    lan.tick()
    assert config.lan_urls == [LOCAL] and config.lan_user == alice.id and config.lan_key
    assert api.route.local and api.base_url == LOCAL and api.server_url == PUBLIC
    net.sent = {PUBLIC: [], LOCAL: []}
    api.call("POST", "/tasks", json={"title": "Pain"})
    assert net.sent[PUBLIC] == [] and net.sent[LOCAL] == ["POST /api/v1/tasks"]
    # Les copies de l'ApiClient (une par page) suivent la même route.
    assert api.with_headers({"X-Test": "1"}).base_url == LOCAL


def test_impostor_on_another_network_never_gets_the_token(state, alice, tmp_path):
    """Un autre réseau, une machine à la même adresse : elle ne connaît pas la clé, le client reste sur
    l'adresse publique et ne lui envoie que la demande de preuve (sans jeton)."""
    impostor = create_state(Settings(data_dir=tmp_path / "autre"))
    impostor_app = create_api_app(impostor)
    seen_headers = []
    impostor_app.middleware("http")(lambda request, call_next: _record(request, call_next, seen_headers))
    net = Net(create_api_app(state), impostor_app)
    api, lan, _ = switch_for(net, token_for(state, alice))
    lan.tick()
    assert not api.route.local and api.base_url == PUBLIC
    assert net.sent[LOCAL] and all("/local-access/proof" in r for r in net.sent[LOCAL])
    assert seen_headers and not any("authorization" in h for h in seen_headers)
    impostor.engine.dispose()


async def _record(request, call_next, seen):
    seen.append({k.lower() for k in request.headers})
    return await call_next(request)


def test_back_to_the_public_address_when_the_local_network_is_gone(state, alice):
    app = create_api_app(state)
    net = Net(app, app)
    api, lan, _ = switch_for(net, token_for(state, alice))
    lan.tick()
    assert api.route.local
    net.local = net._dead(LOCAL)  # départ de la maison
    api.route.http = net.local
    sv = state.services_for(alice)
    task = api.call(
        "POST", "/tasks", dict, json={"title": "Depuis le café"}
    )  # retentée par l'adresse publique
    assert task and not api.route.local and api.base_url == PUBLIC
    assert [t.title for t in sv.tasks.list()] == ["Depuis le café"]


def test_local_server_rechecked_before_use(state, alice):
    now = [1000.0]
    app = create_api_app(state)
    net = Net(app, app)
    api, lan, _ = switch_for(net, token_for(state, alice), clock=lambda: now[0])
    lan.tick()
    proofs = len([r for r in net.sent[LOCAL] if "proof" in r])
    api.call("GET", "/auth/me")
    assert len([r for r in net.sent[LOCAL] if "proof" in r]) == proofs  # preuve récente : pas revérifié
    now[0] += RECHECK_AFTER + 1
    api.call("GET", "/auth/me")
    assert len([r for r in net.sent[LOCAL] if "proof" in r]) == proofs + 1
    assert api.route.local


def test_local_network_disabled_or_unsupported(state, alice, tmp_path):
    app = create_api_app(state)
    net = Net(app, app)
    config = ClientConfig(server=PUBLIC, token=token_for(state, alice), lan_enabled=False)
    api, lan, _ = switch_for(net, config.token, config)
    lan.tick()
    assert not api.route.local and net.sent[LOCAL] == []

    # Serveur antérieur à cette fonction : rien à faire, sans erreur.
    from fastapi import FastAPI

    old = FastAPI()
    net_old = Net(old)
    api2, lan2, config2 = switch_for(net_old, "jeton")
    lan2.tick()
    assert lan2.unsupported and not api2.route.local and config2.lan_urls == []


def test_desktop_client_keeps_lan_info_and_forgets_key_on_logout(state, alice, tmp_path):
    from organizer.client.app import DesktopClient
    from organizer.client.config import ConfigStore

    app = create_api_app(state)
    net = Net(app, app)
    store = ConfigStore(tmp_path / "client")
    client = DesktopClient(store, http_factory=net.factory)
    client.login(PUBLIC, "alice", "motdepasse-12")
    client.lan.tick()
    assert client.api.route.local
    saved = store.load()
    assert saved.lan_urls == [LOCAL] and saved.lan_key and saved.lan_user == alice.id
    state.services_for(alice).tasks.create(TaskCreate(title="Vue du poste"))
    tasks = client.api.call("POST", "/tasks/query", list, json={})
    assert [t["title"] for t in tasks] == ["Vue du poste"]
    client.forget_token()
    saved = store.load()
    assert saved.lan_key == "" and saved.lan_user is None and saved.lan_urls == [LOCAL]
