"""Instance unique du client bureau et commandes à distance (« montre-toi », « nouvelle tâche », « quitte »).

Le client lancé écrit ``instance.json`` (port local, secret, pid) dans son dossier de configuration. Un
nouveau lancement (lanceur, raccourci clavier global…) transmet alors sa commande à l'instance en cours au
lieu d'en démarrer une seconde, puis s'arrête. Bibliothèque standard uniquement : ce chemin doit être rapide.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

FILENAME = "instance.json"
# Secret et port du lancement en cours, transmis au sous-processus de la fenêtre par l'environnement.
ENV_SECRET = "ORGANIZER_CLIENT_LAUNCH"
ENV_PORT = "ORGANIZER_CLIENT_PORT"
CONTROL_PATH = "/_organizer/control"
SECRET_HEADER = "X-Organizer-Secret"
ACTIONS = ("show", "new-task", "quit", "ping", "hidden")


def write(directory: Path, port: int, secret: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / FILENAME
    path.write_text(json.dumps({"port": port, "secret": secret, "pid": os.getpid()}), encoding="utf-8")
    if os.name == "posix":
        path.chmod(0o600)


def remove(directory: Path) -> None:
    path = directory / FILENAME
    try:
        if json.loads(path.read_text(encoding="utf-8")).get("pid") == os.getpid():
            path.unlink()
    except (OSError, ValueError):
        pass


def send(port: int, secret: str, action: str, timeout: float = 2.0) -> bool:
    """Envoie une commande à une instance ; True si elle l'a acceptée."""
    body = json.dumps({"activation_token": os.environ.get("XDG_ACTIVATION_TOKEN")}).encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{CONTROL_PATH}/{action}",
        data=body,
        method="POST",
        headers={SECRET_HEADER: secret, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def forward(directory: Path, action: str) -> bool:
    """Transmet ``action`` à l'instance déjà lancée ; False s'il n'y en a pas (ou plus)."""
    try:
        data = json.loads((directory / FILENAME).read_text(encoding="utf-8"))
        port, secret = int(data["port"]), str(data["secret"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if os.name == "nt":  # ce lancement (clic sur un raccourci) cède au client son droit au premier plan
        from organizer.client import winshell

        winshell.allow_foreground_for_others()
    return send(port, secret, action)
