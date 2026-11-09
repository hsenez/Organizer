"""Configuration du client bureau : adresse du serveur, identifiant, **jeton** API (jamais le mot de passe).

Fichier ``client.json`` dans le dossier de configuration de l'utilisateur (``system.config_dir()``),
lisible par lui seul. Les rappels déjà notifiés sont dans ``notified.json``.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field, fields
from ipaddress import ip_address
from pathlib import Path

DEFAULT_PORT = 2603


@dataclass
class ClientConfig:
    server: str = ""  # ex. http://192.168.1.20:2603
    username: str = ""
    token: str | None = None
    # Raccourcis clavier globaux enregistrés par l'installeur (pour les afficher) : show, new_task.
    shortcuts: dict[str, str] = field(default_factory=dict)
    # Accès direct par le réseau local (voir ``lan.py``) : permis ou non, et ce que le serveur a indiqué
    # (adresses, clé du compte pour vérifier son identité ; secrète comme le jeton).
    lan_enabled: bool = True
    lan_urls: list[str] = field(default_factory=list)
    lan_key: str = ""
    lan_user: int | None = None


LOCAL_SUFFIXES = (".local", ".lan", ".home", ".internal")


def is_local_host(host: str) -> bool:
    """Nom ou adresse d'une machine du réseau local (IP privée, ``raspberrypi.local``, ``localhost``…) ?"""
    host = host.lower().strip("[]")
    if host == "localhost" or host.endswith(LOCAL_SUFFIXES):
        return True
    try:
        address = ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback


def _is_domain_name(host: str) -> bool:
    """Nom de domaine public (``organizer.blou.top``) : avec un point, ni adresse IP ni nom local."""
    if "." not in host or is_local_host(host):
        return False
    try:
        ip_address(host.strip("[]"))
    except ValueError:
        return True
    return False


def normalize_server_url(text: str) -> str:
    """Adresse saisie → URL du serveur.

    Sans protocole : ``organizer.blou.top`` (nom de domaine public, sans port) → ``https://organizer.blou.top``
    (serveur derrière un proxy comme Cloudflare, qui ne sert pas le port 2603) ; sinon http, réseau local :
    ``raspberrypi.local`` → ``http://raspberrypi.local:2603``. En http, le port 2603 est ajouté s'il manque.
    """
    url = text.strip().rstrip("/")
    if not url:
        raise ValueError("Indiquez l'adresse du serveur.")
    if not re.match(r"^https?://", url, re.IGNORECASE):
        host = url.split("/", 1)[0]
        public = re.search(r":\d+$", host) is None and _is_domain_name(host)
        url = f"https://{url}" if public else f"http://{url}"
    scheme, rest = url.split("://", 1)
    host, _, path = rest.partition("/")
    if not host:
        raise ValueError("Adresse du serveur invalide.")
    has_port = re.search(r":\d+$", host) is not None
    if not has_port and scheme.lower() == "http":
        host = f"{host}:{DEFAULT_PORT}"
    return f"{scheme.lower()}://{host}" + (f"/{path}" if path else "")


class ConfigStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.path = directory / "client.json"

    def load(self) -> ClientConfig:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ClientConfig()
        known = {f.name for f in fields(ClientConfig)}
        return ClientConfig(**{k: v for k, v in data.items() if k in known})

    def save(self, config: ClientConfig) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")
        if os.name == "posix":
            tmp.chmod(0o600)  # le jeton donne accès au compte
        tmp.replace(self.path)
