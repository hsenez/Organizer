"""Appels à l'API REST du serveur (``/api/v1``) avec un jeton Bearer.

Les erreurs HTTP redeviennent les erreurs métier de :mod:`organizer.core.errors` (même message en français
que sur le serveur) : l'interface les affiche comme en local. Un serveur injoignable lève
:class:`ServerUnreachable`, un jeton refusé :class:`NotAuthenticated`.
"""

from __future__ import annotations

import contextlib
import copy
import json as jsonlib
import os
from functools import cache
from pathlib import Path
from typing import Any

import httpx
from pydantic import TypeAdapter

from organizer.client import system
from organizer.client.cache import EVERYTHING, RemoteCache
from organizer.core.errors import (
    Forbidden,
    InvalidOperation,
    NotAuthenticated,
    NotFound,
    OrganizerError,
    ServerUnreachable,
    UndoConflict,
)
from organizer.core.events import UNDO_HEADER
from organizer.core.schemas import UndoStatus

API_PREFIX = "/api/v1"
USER_AGENT = "Organizer-Bureau"
NO_BODY: Any = object()  # pas de corps (distinct de ``None``, envoyé comme ``null``)
UNDO_KEY = "undo"  # clé de l'état « annuler / rétablir » dans le cache

_ERRORS: dict[int, type[OrganizerError]] = {
    401: NotAuthenticated,
    403: Forbidden,
    404: NotFound,
    409: UndoConflict,
    422: InvalidOperation,
    429: InvalidOperation,
}


@cache
def _adapter(out: Any) -> TypeAdapter:
    return TypeAdapter(out)


def error_from(response: httpx.Response) -> OrganizerError:
    """Traduit une réponse d'erreur de l'API en erreur métier."""
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, list):  # erreur de validation FastAPI
        fields = ", ".join(str(err.get("loc", ["?"])[-1]) for err in detail if isinstance(err, dict))
        detail = f"Données refusées par le serveur : {fields or 'champ invalide'}."
    cls = _ERRORS.get(response.status_code, OrganizerError)
    return cls(detail or f"Erreur du serveur (code {response.status_code}).")


class ApiClient:
    """Client HTTP synchrone vers un serveur Organizer.

    ``http`` : client httpx à utiliser (les tests passent un ``TestClient`` FastAPI, qui en est un).
    """

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        http: httpx.Client | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.extra_headers: dict[str, str] = {}
        # Partagé par les copies (``with_headers``) : toutes les pages du client profitent de la même mémoire.
        self.cache = RemoteCache()
        self.http = http or httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout, connect=4.0),
            headers={"User-Agent": USER_AGENT},
            # Serveur en HTTPS avec un certificat d'une autorité locale (mkcert…) : son certificat racine.
            verify=os.environ.get("ORGANIZER_CA_FILE") or True,
        )

    def with_headers(self, headers: dict[str, str]) -> ApiClient:
        """Même connexion, avec des en-têtes en plus sur chaque requête (ex. origine de la page)."""
        clone = copy.copy(self)
        clone.extra_headers = {**self.extra_headers, **headers}
        return clone

    def close(self) -> None:
        self.http.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = NO_BODY,
        params: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> httpx.Response:
        headers = dict(self.extra_headers)
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        kwargs: dict[str, Any] = {"params": params, "headers": headers}
        if files is not None:
            kwargs["files"] = files
        elif json is not NO_BODY:
            kwargs["content"] = jsonlib.dumps(json, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json"
        try:
            response = self.http.request(method, API_PREFIX + path, **kwargs)
        except httpx.TimeoutException as exc:
            raise ServerUnreachable(f"⏱️ Le serveur {self.base_url} ne répond pas.") from exc
        except httpx.HTTPError as exc:
            raise ServerUnreachable(
                f"🔌 Serveur injoignable ({self.base_url}) : vérifiez qu'il est démarré et que vous êtes sur "
                "le même réseau."
            ) from exc
        if method != "GET":
            self.cache.on_write(path)
        undo = response.headers.get(UNDO_HEADER)
        if undo:
            with contextlib.suppress(ValueError):
                self.cache.put(UNDO_KEY, UndoStatus.model_validate(jsonlib.loads(undo)), [EVERYTHING])
        if response.status_code >= 400:
            raise error_from(response)
        return response

    def save(self, path: str, folder: Path, params: dict[str, Any] | None = None) -> Path:
        """Télécharge ``GET path`` dans ``folder`` **au fil de l'eau** (gros fichiers), sous le nom donné par
        le serveur (``Content-Disposition``) ; renvoie le chemin du fichier."""
        headers = dict(self.extra_headers)
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        partial: Path | None = None
        try:
            with self.http.stream("GET", API_PREFIX + path, params=params, headers=headers) as response:
                if response.status_code >= 400:
                    response.read()
                    raise error_from(response)
                name = system.filename_from_disposition(response.headers.get("content-disposition", ""))
                final = folder / system.safe_filename(name)
                partial = final.with_name(final.name + ".part")
                with partial.open("wb") as out:
                    for chunk in response.iter_bytes():
                        out.write(chunk)
            partial.replace(final)
            partial = None
            return final
        except httpx.TimeoutException as exc:
            raise ServerUnreachable(f"⏱️ Le serveur {self.base_url} ne répond pas.") from exc
        except httpx.HTTPError as exc:
            raise ServerUnreachable(f"🔌 Téléchargement interrompu ({self.base_url}).") from exc
        finally:
            if partial is not None:
                partial.unlink(missing_ok=True)

    def call(self, method: str, path: str, out: Any = None, **kwargs: Any) -> Any:
        """Requête JSON ; ``out`` : type attendu (modèle, ``list[...]``…), None si pas de résultat."""
        response = self.request(method, path, **kwargs)
        if out is None or response.status_code == 204:
            return None
        data = response.json()
        if data is None:
            return None
        return _adapter(out).validate_python(data)
