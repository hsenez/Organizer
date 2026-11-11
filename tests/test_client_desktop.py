"""Client bureau : instance unique et commandes à distance, ligne de commande, intégration au bureau Linux."""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from organizer.client import install, instance, launcher
from organizer.client.app import DesktopClient, LaunchGuard
from organizer.client.config import ConfigStore

# --- ligne de commande -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], "show"),
        (["--new-task"], "new-task"),
        (["--quit"], "quit"),
        (["--hidden"], "ping"),
        (["organizer://note/5"], "open"),
        (["organizer://n'importe-quoi"], "show"),
    ],
)
def test_launcher_command(argv, expected):
    assert launcher.command(launcher.parse_args(argv)) == expected


def test_launcher_link_ref():
    assert launcher.link_ref(launcher.parse_args(["organizer://task/12"])) == "task:12"
    assert launcher.link_ref(launcher.parse_args(["organizer:event/8/"])) == "event:8"
    assert launcher.link_ref(launcher.parse_args([])) is None


def test_launcher_rejects_two_actions():
    with pytest.raises(SystemExit):
        launcher.parse_args(["--quit", "--new-task"])


# --- instance unique ---------------------------------------------------------------------------------------


@pytest.fixture
def fake_instance():
    """Petit serveur HTTP qui joue l'instance déjà lancée (port, secret « s3cret »)."""
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            ok = self.headers.get(instance.SECRET_HEADER) == "s3cret"
            if ok:
                received.append((self.path, body))
            self.send_response(200 if ok else 403)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1], received
    server.shutdown()


def test_forward_to_running_instance(tmp_path, fake_instance, monkeypatch):
    port, received = fake_instance
    assert not instance.forward(tmp_path, "show")  # aucune instance
    monkeypatch.setenv("XDG_ACTIVATION_TOKEN", "jeton-kde")
    instance.write(tmp_path, port, "s3cret")
    assert instance.forward(tmp_path, "new-task")
    assert received == [(f"{instance.CONTROL_PATH}/new-task", {"activation_token": "jeton-kde"})]
    assert instance.forward(tmp_path, "open", {"ref": "note:5"})
    assert received[-1] == (
        f"{instance.CONTROL_PATH}/open",
        {"ref": "note:5", "activation_token": "jeton-kde"},
    )
    instance.write(tmp_path, port, "mauvais")
    assert not instance.forward(tmp_path, "show")  # secret refusé
    instance.write(tmp_path, 9, "s3cret")
    assert not instance.forward(tmp_path, "show")  # instance disparue (fichier périmé)
    instance.remove(tmp_path)
    assert not (tmp_path / instance.FILENAME).exists()


def test_control_endpoint(tmp_path):
    client = DesktopClient(ConfigStore(tmp_path), launch_secret="s3cret", port=1234)
    calls = []
    client.show_window = lambda token=None: calls.append(("show", token))
    client.new_task = lambda token=None: calls.append(("new-task", token))
    client.quit = lambda: calls.append(("quit", None))
    client.open_item = lambda kind, item_id, activation_token=None: calls.append(
        ("open", f"{kind}:{item_id}")
    )
    api = FastAPI()
    api.add_api_route(f"{instance.CONTROL_PATH}/{{action}}", client.control, methods=["POST"])
    api.add_middleware(LaunchGuard, secret="s3cret")
    http = TestClient(api)
    headers = {instance.SECRET_HEADER: "s3cret"}
    url = f"{instance.CONTROL_PATH}"
    assert http.post(f"{url}/show", json={"activation_token": "t"}, headers=headers).json() == {"ok": True}
    assert http.post(f"{url}/new-task", json={}, headers=headers).status_code == 200
    assert http.post(f"{url}/quit", json={}, headers=headers).status_code == 200
    assert http.post(f"{url}/ping", json={}, headers=headers).status_code == 200
    assert http.post(f"{url}/open", json={"ref": "note:5"}, headers=headers).status_code == 200
    assert http.post(f"{url}/open", json={"ref": "rien"}, headers=headers).status_code == 400
    assert http.post(f"{url}/inconnue", json={}, headers=headers).status_code == 404
    assert http.post(f"{url}/show", json={}, headers={instance.SECRET_HEADER: "non"}).status_code == 403
    assert calls == [("show", "t"), ("new-task", None), ("quit", None), ("open", "note:5")]


def test_launch_guard_keeps_other_parameters():
    api = FastAPI()
    api.add_middleware(LaunchGuard, secret="s3cret")
    response = TestClient(api).get("/?launch=s3cret&task=new", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/?task=new"


# --- intégration au bureau Linux ---------------------------------------------------------------------------


def test_keycodes():
    assert install.qt_keycode("Ctrl+Alt+O") == 0x04000000 | 0x08000000 | ord("O")
    assert install.qt_keycode("meta+shift+F12") == 0x10000000 | 0x02000000 | 0x0100003B
    assert install.gnome_binding("Ctrl+Alt+N") == "<Control><Alt>n"
    for bad in ("O", "Ctrl+", "Hyper+O", "Ctrl+Échap"):
        with pytest.raises(ValueError):
            install.qt_keycode(bad)


def test_exec_quoting():
    assert install.exec_arg("/usr/bin/python") == "/usr/bin/python"
    assert install.exec_arg("/home/a b/run.py") == '"/home/a b/run.py"'
    assert install.exec_arg('/x/"$y"') == '"/x/\\"\\$y\\""'


@pytest.mark.skipif(sys.platform == "win32", reason="fichiers .desktop : Linux seulement (chemins à « / »)")
def test_desktop_files(tmp_path, monkeypatch):
    paths = install.Paths(tmp_path / "share", tmp_path / "config")
    root = tmp_path / "Mes outils" / "Organizer"
    written = install.install_files(paths, "/venv/bin/python", root, autostart=True)
    launcher_file = paths.applications / "organizer.desktop"
    text = launcher_file.read_text()
    assert f'Exec=/venv/bin/python "{root}/run_client.py" %u\n' in text
    assert "MimeType=x-scheme-handler/organizer;" in text
    assert f'Exec=/venv/bin/python "{root}/run_client.py" --new-task' in text
    assert "Actions=new-task;quit;" in text and "Icon=organizer" in text
    autostart = (paths.autostart / "organizer.desktop").read_text()
    assert "--hidden" in autostart and "Actions=" not in autostart
    assert (paths.icons / "48x48" / "apps" / "organizer.png") in written
    install.install_files(paths, "/venv/bin/python", root, autostart=False)
    assert not (paths.autostart / "organizer.desktop").exists()
    install.remove_files(paths)
    assert not launcher_file.exists() and not (paths.icons / "48x48" / "apps" / "organizer.png").exists()


@pytest.mark.parametrize(
    ("value", "kind"), [("KDE", "kde"), ("ubuntu:GNOME", "gnome"), ("XFCE", "other"), ("", "other")]
)
def test_desktop_kind(monkeypatch, value, kind):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", value)
    assert install.desktop_kind() == kind


def test_windows_hotkey_parsing():
    from organizer.client.winshell import MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, parse_hotkey

    assert parse_hotkey("Ctrl+Alt+O") == (MOD_CONTROL | MOD_ALT, ord("O"))
    assert parse_hotkey("ctrl + shift + n") == (MOD_CONTROL | MOD_SHIFT, ord("N"))
    assert parse_hotkey("Win+Alt+F12") == (MOD_WIN | MOD_ALT, 0x7B)
    assert parse_hotkey("Ctrl+Alt+7") == (MOD_CONTROL | MOD_ALT, ord("7"))
    assert parse_hotkey("O") is None and parse_hotkey("Hyper+O") is None and parse_hotkey("Ctrl+É") is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows seulement")
def test_windows_shell_hotkey_and_tray():
    """Vrai raccourci global (appui simulé) et icône de la zone de notification."""
    import ctypes
    import time

    from organizer import ASSETS_DIR
    from organizer.client import winshell

    hits: list[str] = []
    shell = winshell.Shell(
        {"show": "Ctrl+Alt+Shift+F11"},
        {"show": lambda: hits.append("show")},
        ASSETS_DIR / "organizer.ico",
        tooltip="Organizer (test)",
    )
    shell.start()
    try:
        assert shell.hwnd and shell.registered == {1: "show"}
        keyboard = ctypes.windll.user32.keybd_event
        for vk in (0x11, 0x12, 0x10, 0x7A):  # Ctrl, Alt, Maj, F11
            keyboard(vk, 0, 0, 0)
        for vk in (0x7A, 0x10, 0x12, 0x11):
            keyboard(vk, 0, 2, 0)
        for _ in range(50):
            if hits:
                break
            time.sleep(0.02)
        assert hits == ["show"]
    finally:
        shell.stop()
    assert shell.hwnd == 0
