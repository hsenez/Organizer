"""Accès direct par le réseau local pour le client bureau.

Le client se connecte par l'adresse publique (``https://organizer.blou.top``, à travers Cloudflare : ≈ 300 ms
par requête). À la maison, il peut joindre le Pi directement (≈ 20 ms). Pour cela :

1. il demande au serveur, par l'adresse publique et avec son jeton, les **adresses locales** du serveur et
   une **clé** propre à son compte (:func:`user_key`, dérivée de la clé secrète du serveur) ;
2. il essaie ces adresses ; le serveur qui y répond doit **prouver** qu'il connaît la clé
   (:func:`proof` d'un nombre tiré au hasard par le client) **avant** que le client ne lui envoie son jeton.

Une machine d'un autre réseau qui aurait la même adresse (café, hôtel…) ne connaît pas la clé. Elle ne peut
pas non plus faire calculer la preuve par le vrai serveur en la lui demandant par Internet : il ne répond
qu'aux machines de **son** réseau local (adresse de bouclage ou privée ; derrière Cloudflare, un visiteur
garde son adresse publique).

La clé secrète du serveur est dans ``<données>/instance.key`` (créée au premier démarrage, lisible par le
seul compte du serveur). La supprimer invalide les clés des clients (ils redemandent la leur).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import socket
from ipaddress import ip_address
from pathlib import Path

from organizer.config import Settings

KEY_FILE = "instance.key"
ENV_URLS = (
    "ORGANIZER_LOCAL_URLS"  # adresses locales imposées (séparées par des virgules), si la détection rate
)


def instance_key(data_dir: Path) -> bytes:
    """Clé secrète du serveur (créée si besoin)."""
    path = data_dir / KEY_FILE
    try:
        text = path.read_text(encoding="ascii").strip()
        if len(text) >= 64:
            return bytes.fromhex(text)
    except (OSError, ValueError):
        pass
    key = secrets.token_bytes(32)
    data_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(key.hex())
    return key


def user_key(key: bytes, user_id: int) -> str:
    """Clé d'un compte (hexadécimal) : un utilisateur ne peut pas en déduire celle d'un autre."""
    return hmac.new(key, f"organizer-lan:{user_id}".encode(), hashlib.sha256).hexdigest()


def proof(account_key: str, nonce: str) -> str:
    """Preuve qu'un serveur connaît ``account_key`` (le client fait le même calcul et compare)."""
    return hmac.new(bytes.fromhex(account_key), nonce.encode(), hashlib.sha256).hexdigest()


def _is_lan(address: str) -> bool:
    try:
        ip = ip_address(address)
    except ValueError:
        return False
    return ip.version == 4 and ip.is_private and not ip.is_loopback and not ip.is_link_local


def machine_addresses() -> list[str]:
    """Adresses IPv4 privées de cette machine (réseau local), la principale en premier."""
    found: list[str] = []
    try:  # adresse de sortie par défaut (aucun paquet n'est envoyé par un « connect » UDP)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        found += socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass
    result: list[str] = []
    for address in found:
        if _is_lan(address) and address not in result:
            result.append(address)
    return result


def local_urls(settings: Settings, addresses: list[str] | None = None) -> list[str]:
    """Adresses auxquelles un poste du réseau local peut joindre ce serveur (vide s'il n'écoute que sur le Pi
    lui-même, ``--host 127.0.0.1`` : tout passe alors par le tunnel)."""
    if forced := os.environ.get(ENV_URLS, "").strip():
        return [url.strip().rstrip("/") for url in forced.split(",") if url.strip()]
    host = settings.host.strip()
    if host in ("127.0.0.1", "localhost", "::1"):
        return []
    if host in ("0.0.0.0", "::", ""):
        hosts = addresses if addresses is not None else machine_addresses()
    else:
        hosts = [host] if _is_lan(host) else []
    scheme = "https" if settings.https else "http"
    return [f"{scheme}://{h}:{settings.port}" for h in hosts]
