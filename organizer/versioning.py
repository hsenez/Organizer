"""Comparaison des versions du client bureau et du serveur (avertissement « mise à jour disponible »)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from organizer import API_VERSION, __version__


def parse(version: str) -> tuple[int, int, int]:
    """« 0.7.0 » → (0, 7, 0) ; tolère un suffixe (« 0.8.0rc1 », « 1.2 »)."""
    numbers = [int(n) for n in re.findall(r"\d+", version.split("+")[0])[:3]]
    if not numbers:
        raise ValueError(f"Version illisible : {version!r}")
    return (*numbers, 0, 0)[:3]  # type: ignore[return-value]


@dataclass(frozen=True)
class VersionCheck:
    """``kind`` : ok | client_old | server_old ; ``blocking`` : API incompatible."""

    kind: str
    client: str
    server: str | None
    blocking: bool = False

    @property
    def ok(self) -> bool:
        return self.kind == "ok"


def check(
    server_version: str | None,
    server_api: int | None,
    client_version: str = __version__,
    client_api: int = API_VERSION,
) -> VersionCheck:
    """Compare ce poste au serveur. ``server_version`` None : serveur trop ancien pour l'indiquer."""
    if server_version is None or server_api is None:
        return VersionCheck("server_old", client_version, None, blocking=False)
    blocking = server_api != client_api
    mine, theirs = parse(client_version), parse(server_version)
    if theirs > mine or server_api > client_api:
        return VersionCheck("client_old", client_version, server_version, blocking)
    if mine > theirs or client_api > server_api:
        return VersionCheck("server_old", client_version, server_version, blocking)
    return VersionCheck("ok", client_version, server_version)


def update_command(platform: str) -> str:
    """Commande de mise à jour du client bureau (dans le dossier d'Organizer)."""
    return r"install\windows\update.bat" if platform == "win32" else "install/linux/update.sh"


def message(result: VersionCheck, platform: str) -> str:
    """Texte de l'avertissement affiché en haut des pages du client bureau."""
    server = result.server or "ancienne version"
    if result.kind == "client_old":
        if result.blocking:
            return (
                f"⚠️ Ce poste est trop ancien pour le serveur (poste {result.client}, serveur {server}) : "
                f"certaines actions vont échouer. Mettez-le à jour : {update_command(platform)}"
            )
        return (
            f"🔄 Une mise à jour d'Organizer est disponible (poste {result.client}, serveur {server}) : "
            f"{update_command(platform)}"
        )
    if result.kind == "server_old":
        prefix = "⚠️" if result.blocking or result.server is None else "ℹ️"
        return (
            f"{prefix} Le serveur ({server}) est plus ancien que ce poste ({result.client}) : "
            "mettez-le à jour sur le Raspberry Pi avec deploy/update.sh."
        )
    return ""
