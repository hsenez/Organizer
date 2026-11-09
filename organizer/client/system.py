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


def downloads_dir() -> Path:
    """Dossier « Téléchargements » de l'utilisateur (``XDG_DOWNLOAD_DIR`` sous Linux), créé au besoin."""
    if custom := os.environ.get("ORGANIZER_CLIENT_DIR"):
        folder = Path(custom) / "downloads"
    elif sys.platform == "win32" or sys.platform == "darwin":
        folder = Path.home() / "Downloads"
    else:
        folder = _xdg_user_dir("DOWNLOAD") or Path.home() / "Downloads"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _xdg_user_dir(name: str) -> Path | None:
    """Dossier utilisateur déclaré dans ``~/.config/user-dirs.dirs`` (``XDG_<NAME>_DIR="$HOME/…"``)."""
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "user-dirs.dirs"
    try:
        text = config.read_text(encoding="utf-8")
    except OSError:
        return None
    if match := re.search(rf'^XDG_{name}_DIR="([^"]+)"', text, re.MULTILINE):
        value = match.group(1).replace("$HOME", str(Path.home()))
        path = Path(value)
        if path.is_absolute() and path != Path.home():
            return path
    return None


_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def safe_filename(filename: str) -> str:
    """Nom de fichier utilisable sur tous les systèmes (ni chemin, ni caractère interdit sous Windows)."""
    return _UNSAFE.sub("_", filename).strip(" .") or "fichier"


def cache_file(root: Path, attachment_id: str, filename: str) -> Path:
    """Emplacement local d'une pièce jointe : ``<cache>/<id>/<nom>`` (nom nettoyé, jamais hors du dossier)."""
    name = safe_filename(filename)
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
    drive = re.match(r"^file:/*([A-Za-z]:[\\/].*)$", text, re.IGNORECASE)
    if drive:  # Windows : file:///C:/…, mais aussi les formes approximatives file://C:/… ou file://C:\…
        text = unquote(drive.group(1))
    elif text.lower().startswith("file://"):
        parsed = urlparse(text)
        text = unquote(parsed.path)
        if parsed.netloc and parsed.netloc != "localhost":
            text = f"//{parsed.netloc}{text}"  # partage réseau
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
