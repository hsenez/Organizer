"""⚡ Temps réel côté client bureau : écoute le flux SSE ``/api/v1/events`` du serveur, dans un fil à part,
et transmet chaque modification aux pages ouvertes (``ui/live.py``).

- Reconnexion automatique (attente croissante jusqu'à 30 s) ; après une reconnexion, toutes les pages se
  rafraîchissent (des modifications ont pu être manquées pendant la coupure).
- Si le jeton change (déconnexion, autre compte), le flux est rouvert avec le nouveau.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Iterable, Iterator

import httpx

from organizer.client.api import API_PREFIX, ApiClient
from organizer.core.events import ChangeEvent

log = logging.getLogger("organizer.client")

READ_TIMEOUT = 60.0  # > battement de cœur du serveur (20 s) : une connexion morte finit par être détectée


def parse_sse(lines: Iterable[str]) -> Iterator[tuple[str, str]]:
    """Lignes d'un flux SSE → ``(événement, données)`` ; ignore commentaires et champs inconnus."""
    name, data = "message", []
    for line in lines:
        if line == "":
            if data or name != "message":
                yield name, "\n".join(data)
            name, data = "message", []
        elif line.startswith(":"):
            continue
        else:
            field, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if field == "event":
                name = value
            elif field == "data":
                data.append(value)


class EventListener:
    def __init__(
        self,
        get_api: Callable[[], ApiClient | None],
        on_change: Callable[[ChangeEvent | None], None],
        *,
        max_backoff: float = 30.0,
    ) -> None:
        """``on_change(event)`` ; ``event`` None : tout rafraîchir (reconnexion)."""
        self.get_api = get_api
        self.on_change = on_change
        self.max_backoff = max_backoff
        self.stop_event = threading.Event()
        self.connections = 0
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="organizer-events", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def _run(self) -> None:
        backoff = 1.0
        while not self.stop_event.is_set():
            api = self.get_api()
            if api is None:
                self.stop_event.wait(5)
                continue
            try:
                self._listen(api)
                backoff = 1.0
            except httpx.HTTPStatusError as exc:
                log.info("Flux temps réel refusé (%s)", exc.response.status_code)
                backoff = self.max_backoff
            except httpx.HTTPError as exc:
                log.info("Flux temps réel interrompu : %s", exc.__class__.__name__)
                api.route.use_server()  # réseau local perdu ? reconnexion par l'adresse configurée
            except Exception:
                log.exception("Erreur dans le flux temps réel")
            self.stop_event.wait(backoff)
            backoff = min(backoff * 2, self.max_backoff)

    def _listen(self, api: ApiClient) -> None:
        token = api.token
        headers = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}
        timeout = httpx.Timeout(10.0, read=READ_TIMEOUT)
        with api.http.stream("GET", f"{API_PREFIX}/events", headers=headers, timeout=timeout) as response:
            response.raise_for_status()
            for name, data in parse_sse(response.iter_lines()):
                if self.stop_event.is_set():
                    return
                current = self.get_api()
                if current is None or current.token != token:
                    return  # déconnexion ou autre compte : on rouvre avec le bon jeton
                if name == "hello":
                    if self.connections:
                        self.on_change(None)  # reconnexion : des modifications ont pu être manquées
                    self.connections += 1
                elif name == "changed":
                    try:
                        self.on_change(ChangeEvent.from_json(json.loads(data)))
                    except (ValueError, TypeError):
                        log.warning("Événement illisible : %r", data)
