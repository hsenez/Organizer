"""Adresses des liens vers une note, une tâche ou un événement (bibliothèque standard seulement : le lanceur
du client bureau l'utilise avant de savoir s'il doit démarrer).

- **Lien interne** (dans le texte) : ``note:5``, ``task:12``, ``event:8`` (``rules.parse_ref``).
- **Lien à partager** : ``https://<adresse publique>/open/note/5``. Cette page propose d'ouvrir l'élément
  dans le client bureau (``organizer://note/5``) ou de continuer dans le navigateur (page de l'élément) ;
  le choix peut être retenu par appareil, et un téléphone va directement au navigateur.
- **Lien du client bureau** : ``organizer://note/5`` (protocole déclaré au système par les installeurs ;
  le lanceur le transmet au client).
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

SCHEME = "organizer"
KINDS = ("task", "event", "note")
# Page web de chaque type d'élément (paramètre d'URL qui ouvre l'élément).
_PAGES = {"task": ("/tasks", "task"), "event": ("/calendar", "event"), "note": ("/notes", "note")}
_OPEN_PATH = re.compile(r"^/open/(task|event|note)/(\d+)/?$")
_SCHEME_URL = re.compile(r"^organizer:(?://+)?(task|event|note)[/:](\d+)/?$", re.IGNORECASE)


def ref(kind: str, item_id: int) -> str:
    return f"{kind}:{item_id}"


def split_ref(value: str) -> tuple[str, int] | None:
    match = re.match(r"^(task|event|note):(\d+)$", value.strip())
    return (match.group(1), int(match.group(2))) if match else None


def page_path(kind: str, item_id: int) -> str:
    """Page web qui ouvre l'élément : ``/notes?note=5``, ``/tasks?task=12``, ``/calendar?event=8``."""
    path, param = _PAGES[kind]
    return f"{path}?{param}={item_id}"


def open_path(kind: str, item_id: int) -> str:
    """Chemin du lien à partager (page « ouvrir dans… ») : ``/open/note/5``."""
    return f"/open/{kind}/{item_id}"


def scheme_url(kind: str, item_id: int) -> str:
    return f"{SCHEME}://{kind}/{item_id}"


def from_scheme_url(url: str) -> str | None:
    """``organizer://note/5`` (ou ``organizer:note/5``) → ``note:5`` ; None sinon."""
    match = _SCHEME_URL.match(url.strip())
    return ref(match.group(1).lower(), int(match.group(2))) if match else None


def from_url(url: str) -> str | None:
    """Lien interne désigné par une adresse d'Organizer collée ou cliquée : ``organizer://note/5``,
    ``https://…/open/note/5``, ``https://…/notes?note=5``, ``…/tasks?task=12``, ``…/calendar?event=8``
    (quelle que soit l'adresse du serveur) ; None sinon."""
    url = url.strip()
    found = from_scheme_url(url)
    if found is not None:
        return found
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https", "") or (parts.scheme and not parts.netloc):
        return None
    if not parts.scheme and not url.startswith("/"):
        return None
    match = _OPEN_PATH.match(parts.path)
    if match:
        return ref(match.group(1), int(match.group(2)))
    query = parse_qs(parts.query)
    for kind, (path, param) in _PAGES.items():
        values = query.get(param)
        if parts.path.rstrip("/") == path and values and values[0].isdigit() and len(query) == 1:
            return ref(kind, int(values[0]))
    return None
