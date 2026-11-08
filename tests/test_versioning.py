"""Versions : comparaison client / serveur, route /version, avertissement du client bureau."""

from __future__ import annotations

import argparse

import pytest
from fastapi.testclient import TestClient

from organizer import API_VERSION, __version__, versioning
from organizer.client import install
from organizer.config import Settings
from organizer.server.state import create_state
from organizer.server.wiring import create_api_app


def test_parse():
    assert versioning.parse("0.7.0") == (0, 7, 0)
    assert versioning.parse("1.2") == (1, 2, 0)
    assert versioning.parse("0.8.0rc1") == (0, 8, 0)
    with pytest.raises(ValueError):
        versioning.parse("dev")


@pytest.mark.parametrize(
    ("server", "server_api", "kind", "blocking"),
    [
        ("0.7.0", 1, "ok", False),
        ("0.7.1", 1, "client_old", False),
        ("0.10.0", 1, "client_old", False),  # 10 > 9 : comparaison numérique, pas alphabétique
        ("0.8.0", 2, "client_old", True),
        ("0.6.3", 1, "server_old", False),
        ("0.6.0", 0, "server_old", True),
        (None, None, "server_old", False),
    ],
)
def test_check(server, server_api, kind, blocking):
    result = versioning.check(server, server_api, client_version="0.7.0", client_api=1)
    assert (result.kind, result.blocking) == (kind, blocking)


def test_messages():
    newer = versioning.check("0.8.0", 1, client_version="0.7.0", client_api=1)
    assert "Mettez à jour ce poste" in versioning.message(newer, "linux") and "install/linux/update.sh" in (
        versioning.message(newer, "linux")
    )
    assert r"install\windows\update.bat" in versioning.message(newer, "win32")
    older = versioning.check("0.6.0", 1, client_version="0.7.0", client_api=1)
    assert "deploy/update.sh" in versioning.message(older, "linux")
    assert versioning.message(versioning.check("0.7.0", 1, "0.7.0", 1), "linux") == ""


def test_restart_needed_when_code_updated_but_not_restarted():
    result = versioning.check("0.8.0", 1, client_version="0.7.0", client_api=1, installed="0.8.0")
    assert result.kind == "restart" and not result.blocking
    text = versioning.message(result, "linux")
    assert "Quitter Organizer" in text and "0.8.0" in text and "0.7.0" in text
    # Code sur le disque identique à celui qui tourne : comparaison normale avec le serveur.
    assert versioning.check("0.8.0", 1, "0.7.0", 1, installed="0.7.0").kind == "client_old"
    assert versioning.check("0.8.0", 1, "0.8.0", 1, installed="0.8.0").ok


def test_messages_name_who_must_update():
    old_client = versioning.message(versioning.check("0.8.0", 1, "0.7.0", 1), "linux")
    assert old_client.startswith("🔄 Ce poste est en retard")
    old_server = versioning.message(versioning.check("0.7.0", 1, "0.8.0", 1), "linux")
    assert "C'est le serveur qui est en retard" in old_server


def test_installed_version(tmp_path):
    assert versioning.installed_version() == __version__
    init = tmp_path / "__init__.py"
    init.write_text('"""doc"""\n__version__ = "9.1.0"\nAPI_VERSION = 1\n')
    assert versioning.installed_version(init) == "9.1.0"
    assert versioning.installed_version(tmp_path / "absent.py") is None


def test_version_route_needs_no_login(tmp_path):
    http = TestClient(create_api_app(create_state(Settings(data_dir=tmp_path))))
    assert http.get("/api/v1/version").json() == {"version": __version__, "api": API_VERSION}


def test_installer_remembers_options(tmp_path):
    first = argparse.Namespace(no_autostart=True, no_shortcuts=False, show_key="Meta+O", new_key="Meta+N")
    install.save_options(tmp_path, first)
    later = argparse.Namespace(no_autostart=False, no_shortcuts=False, show_key="Ctrl+Alt+O", new_key="x")
    install.reuse_options(tmp_path, later)
    assert vars(later) == vars(first)
    untouched = argparse.Namespace(no_autostart=False, no_shortcuts=True, show_key="A", new_key="B")
    install.reuse_options(tmp_path / "rien", untouched)
    assert untouched.show_key == "A"
