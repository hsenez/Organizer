"""Interactions avec le système du poste (client bureau) : ouvrir un fichier ou un lien, dossiers de
configuration et de cache. Linux, Windows (et macOS au passage)."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import webbrowser
from pathlib import Path
from urllib.parse import unquote, urlparse

from organizer.core.errors import NotFound

APP_DIR_NAME = "organizer"


def config_dir() -> Path:
    """Dossier de configuration du client (``ORGANIZER_CLIENT_DIR`` pour le changer)."""
    if custom := os.environ.get("ORGANIZER_CLIENT_DIR"):
        return Path(custom)
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Organizer"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Organizer"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / APP_DIR_NAME


def cache_dir() -> Path:
    """Dossier des pièces jointes téléchargées pour être ouvertes."""
    if custom := os.environ.get("ORGANIZER_CLIENT_DIR"):
        return Path(custom) / "cache"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or config_dir()) / "Organizer" / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "Organizer"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / APP_DIR_NAME


_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def cache_file(root: Path, attachment_id: str, filename: str) -> Path:
    """Emplacement local d'une pièce jointe : ``<cache>/<id>/<nom>`` (nom nettoyé, jamais hors du dossier)."""
    name = _UNSAFE.sub("_", filename).strip(" .") or "fichier"
    folder = root / _UNSAFE.sub("_", attachment_id)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / name


def filename_from_disposition(header: str) -> str:
    """Nom de fichier d'un en-tête ``Content-Disposition`` (``filename*=utf-8''…`` ou ``filename=``)."""
    if match := re.search(r"filename\*\s*=\s*[^']*'[^']*'([^;]+)", header, re.IGNORECASE):
        return unquote(match.group(1).strip().strip('"'))
    if match := re.search(r'filename\s*=\s*"?([^";]+)"?', header, re.IGNORECASE):
        return match.group(1).strip()
    return "fichier"


def resolve_local_path(target: str) -> Path:
    """Chemin local d'un lien (``~``, variables d'environnement, ``file://``) ; erreur s'il n'existe pas."""
    text = target.strip()
    if text.lower().startswith("file://"):
        parsed = urlparse(text)
        text = unquote(parsed.path)
        if parsed.netloc and parsed.netloc != "localhost":
            text = f"//{parsed.netloc}{text}"  # partage réseau
        if sys.platform == "win32" and re.match(r"^/[A-Za-z]:", text):
            text = text[1:]
    path = Path(os.path.expandvars(os.path.expanduser(text)))
    if not path.exists():
        raise NotFound(f"📁 Introuvable sur ce poste : {target}")
    return path


def open_path(path: str) -> None:
    """Ouvre un fichier ou un dossier avec l'application par défaut du système."""
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_url(url: str) -> None:
    """Ouvre une adresse dans le navigateur par défaut."""
    webbrowser.open(url)
