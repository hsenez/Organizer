"""Comparaison des versions du client bureau et du serveur (avertissement « mise à jour disponible »)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from organizer import API_VERSION, __version__


def parse(version: str) -> tuple[int, int, int]:
    """« 0.7.0 » → (0, 7, 0) ; tolère un suffixe (« 0.8.0rc1 », « 1.2 »)."""
    numbers = [int(n) for n in re.findall(r"\d+", version.split("+")[0])[:3]]
    if not numbers:
        raise ValueError(f"Version illisible : {version!r}")
    return (*numbers, 0, 0)[:3]  # type: ignore[return-value]


VERSION_FILE = Path(__file__).parent / "__init__.py"


def installed_version(path: Path = VERSION_FILE) -> str | None:
    """Version écrite **sur le disque** (peut différer de celle en mémoire si le code a été mis à jour
    depuis le lancement du client, sans redémarrage)."""
    try:
        text = path.read_text(encoding="utf-8")
        match = re.search(r"""^__version__\s*=\s*["']([^"']+)["']""", text, re.MULTILINE)
    except OSError:
        return None
    return match.group(1) if match else None


@dataclass(frozen=True)
class VersionCheck:
    """``kind`` : ok | restart | client_old | server_old ; ``blocking`` : API incompatible.

    ``restart`` : le code de ce poste a été mis à jour mais le client tourne encore avec l'ancien (il faut
    le quitter et le relancer) ; ``installed`` : la version sur le disque."""

    kind: str
    client: str
    server: str | None
    blocking: bool = False
    installed: str | None = None

    @property
    def ok(self) -> bool:
        return self.kind == "ok"


def check(
    server_version: str | None,
    server_api: int | None,
    client_version: str = __version__,
    client_api: int = API_VERSION,
    installed: str | None = None,
) -> VersionCheck:
    """Compare ce poste au serveur. ``server_version`` None : serveur trop ancien pour l'indiquer.
    ``installed`` : version sur le disque ; plus récente que celle qui tourne → redémarrer le client."""
    try:
        if installed is not None and parse(installed) > parse(client_version):
            return VersionCheck("restart", client_version, server_version, installed=installed)
    except ValueError:
        pass
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
    if platform == "win32":
        return r"install\windows\update.bat"
    return "install/macos/update.sh" if platform == "darwin" else "install/linux/update.sh"


def message(result: VersionCheck, platform: str) -> str:
    """Texte de l'avertissement affiché en haut des pages du client bureau."""
    server = result.server or "une ancienne version"
    if result.kind == "restart":
        return (
            f"🔁 Organizer a été mis à jour sur ce poste ({result.installed}) mais tourne encore avec "
            f"l'ancienne version ({result.client}) : quittez-le (menu du compte → ⏻ Quitter Organizer) "
            "puis relancez-le."
        )
    if result.kind == "client_old":
        if result.blocking:
            return (
                f"⚠️ Ce poste est trop ancien pour le serveur (ce poste : {result.client}, "
                f"serveur : {server}) : certaines actions vont échouer. "
                f"Mettez à jour ce poste : {update_command(platform)}"
            )
        return (
            f"🔄 Ce poste est en retard (ce poste : {result.client}, serveur : {server}). "
            f"Mettez à jour ce poste : {update_command(platform)}"
        )
    if result.kind == "server_old":
        prefix = "⚠️" if result.blocking or result.server is None else "ℹ️"
        return (
            f"{prefix} C'est le serveur qui est en retard (serveur : {server}, ce poste : {result.client}). "
            "Mettez à jour le serveur, sur le Raspberry Pi : deploy/update.sh"
        )
    return ""
