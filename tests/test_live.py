"""⚡ Temps réel : événements publiés par les services, flux SSE, écouteur du client bureau."""

from __future__ import annotations

import socket
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient

from organizer.client.api import ApiClient
from organizer.client.live import EventListener, parse_sse
from organizer.config import Settings
from organizer.core.events import ORIGIN_HEADER, ChangeEvent, EventBus
from organizer.core.schemas import ProjectIn, TaskCreate
from organizer.core.services import Services
from organizer.server.state import create_state
from organizer.server.wiring import create_api_app


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def received(bus):
    events: list[ChangeEvent] = []
    bus.subscribe(events.append)
    return events


def test_services_publish_changes(engine, users, settings, bus, received):
    user = users.create_user("alice", "motdepasse-12", "Alice")
    sv = Services.for_user(engine, user.id, settings=settings, events=bus, origin="page-1")
    task = sv.tasks.create(TaskCreate(title="T"))
    assert received == [ChangeEvent(("task",), user.id, "page-1")]
    sv.tasks.get(task.id)
    sv.tasks.list()
    assert len(received) == 1  # les lectures ne publient rien
    sv.users.set_pref(user.id, "view:tasks", {})  # préférence d'affichage : pas une donnée partagée
    assert len(received) == 1
    sv.projects.create(ProjectIn(name="P"))
    sv.undo.undo()
    assert [e.tables for e in received[1:]] == [("project",), ("project",)]


def test_unsubscribe_and_failing_subscriber(bus):
    def boom(_event):
        raise RuntimeError("abonné cassé")

    got = []
    bus.subscribe(boom)
    unsubscribe = bus.subscribe(got.append)
    bus.publish(ChangeEvent(("task",), 1))
    unsubscribe()
    bus.publish(ChangeEvent(("task",), 1))
    assert len(got) == 1 and bus.subscriber_count == 1


def test_api_passes_origin(tmp_path):
    state = create_state(Settings(data_dir=tmp_path))
    http = TestClient(create_api_app(state))
    token = http.post("/api/v1/setup", json={"username": "alice", "password": "motdepasse-12"}).json()[
        "token"
    ]
    events: list[ChangeEvent] = []
    state.events.subscribe(events.append)
    headers = {"Authorization": f"Bearer {token}", ORIGIN_HEADER: "fenetre-42"}
    http.post("/api/v1/tasks", json={"title": "Depuis le bureau"}, headers=headers)
    assert events[-1].origin == "fenetre-42" and events[-1].tables == ("task",)


def test_parse_sse():
    lines = [
        "retry: 3000",
        "event: hello",
        "data: {}",
        "",
        ": ping",
        "",
        "event: changed",
        "data: {",
        "data: }",
        "",
    ]
    assert list(parse_sse(lines)) == [("hello", "{}"), ("changed", "{\n}")]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def live_server(tmp_path, monkeypatch):
    """Vrai serveur HTTP (uvicorn) dans un fil : le flux SSE doit traverser une vraie connexion."""
    from organizer.server.api import events as events_route

    monkeypatch.setattr(events_route, "HEARTBEAT", 0.2)
    state = create_state(Settings(data_dir=tmp_path))
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_api_app(state), host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield state, f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)
    state.engine.dispose()


def _wait(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_desktop_listener_receives_changes(live_server):
    state, url = live_server
    alice = state.users.create_user("alice", "motdepasse-12", "Alice")
    token, _ = state.auth.create_session(alice.id, kind="api", label="test")
    api = ApiClient(url, token)
    got: list[ChangeEvent | None] = []
    listener = EventListener(lambda: api, got.append, max_backoff=0.2)
    listener.start()
    try:
        assert _wait(lambda: listener.connections == 1)
        state.services_for(alice, origin="ailleurs").tasks.create(TaskCreate(title="Nouvelle"))
        assert _wait(lambda: got), "aucun événement reçu"
        assert got[0] == ChangeEvent(("task",), alice.id, "ailleurs")
    finally:
        listener.stop()
        api.close()
