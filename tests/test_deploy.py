"""Installation du serveur (deploy/install.sh) : utilisateur du service, options, fichier systemd généré.

``--print-service`` n'installe rien ; ``ORG_EUID`` simule un lancement avec sudo."""

from __future__ import annotations

import getpass
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash requis")


def run(*args: str, **env: str) -> subprocess.CompletedProcess:
    clean = {k: v for k, v in os.environ.items() if k not in ("SUDO_USER", "ORG_EUID")}
    return subprocess.run(
        ["bash", str(ROOT / "deploy" / "install.sh"), *args],
        capture_output=True,
        text=True,
        env={**clean, **env},
        cwd=ROOT,
        check=False,
    )


def unit(*args: str, **env: str) -> str:
    result = run("--print-service", *args, **env)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_service_runs_as_the_calling_user():
    me = getpass.getuser()
    text = unit()
    assert f"User={me}\n" in text and f"WorkingDirectory={ROOT}\n" in text
    assert f'ExecStart="{ROOT}/.venv/bin/python" "{ROOT}/run_server.py"' in text
    assert "Restart=always" in text and "WantedBy=multi-user.target" in text
    assert f'Environment="ORGANIZER_DATA_DIR={ROOT}/data"' in text and 'ORGANIZER_PORT=2603"' in text
    assert 'Environment="ORGANIZER_HOST=0.0.0.0"' in text  # écoute sur tout le réseau par défaut
    assert 'Environment="PYTHONUTF8=1"' in text  # journal en UTF-8 même si le Pi est réglé en Latin-1
    assert "ORGANIZER_SSL" not in text


def test_with_sudo_the_service_still_runs_as_the_user():
    me = getpass.getuser()
    assert f"User={me}\n" in unit(ORG_EUID="0", SUDO_USER=me)


def test_refuses_plain_root():
    for env in ({"ORG_EUID": "0"}, {"ORG_EUID": "0", "SUDO_USER": "root"}):
        result = run("--print-service", **env)
        assert result.returncode != 0 and "pas directement en root" in result.stderr


def test_options():
    text = unit("--port", "2700", "--data-dir", "/srv/organizer", "--ssl-cert", "c.pem", "--ssl-key", "k.pem")
    assert 'ORGANIZER_PORT=2700"' in text and 'ORGANIZER_DATA_DIR=/srv/organizer"' in text
    assert f'ORGANIZER_SSL_CERT={ROOT}/c.pem"' in text and f'ORGANIZER_SSL_KEY={ROOT}/k.pem"' in text
    assert run("--print-service", "--ssl-cert", "c.pem").returncode != 0  # clé manquante
    assert run("--print-service", "--port", "abc").returncode != 0
    assert 'ORGANIZER_HOST=127.0.0.1"' in unit("--host", "127.0.0.1")
    assert run("--print-service", "--host", "0.0.0.0; rm -rf /").returncode != 0
    assert run("--inconnue").returncode != 0


def test_reuse_saved_options(tmp_path):
    conf = ROOT / "deploy" / "server.conf"
    backup = conf.read_text() if conf.exists() else None
    try:
        conf.write_text(
            "SAVED_PORT=2800\nSAVED_HOST=127.0.0.1\nSAVED_DATA_DIR=/srv/o\nSAVED_SSL_CERT=/c.pem\n"
            "SAVED_SSL_KEY=/k.pem\n"
        )
        text = unit("--reuse")
        assert 'ORGANIZER_PORT=2800"' in text and 'ORGANIZER_SSL_CERT=/c.pem"' in text
        assert 'ORGANIZER_HOST=127.0.0.1"' in text
        assert 'ORGANIZER_HOST=0.0.0.0"' in unit("--reuse", "--host", "0.0.0.0")
        assert 'ORGANIZER_PORT=2900"' in unit("--reuse", "--port", "2900")  # la ligne de commande gagne
        assert "ORGANIZER_SSL" not in unit("--reuse", "--no-https")
        assert "ORGANIZER_SSL" not in unit()  # sans --reuse : valeurs par défaut
    finally:
        if backup is None:
            conf.unlink(missing_ok=True)
        else:
            conf.write_text(backup)
