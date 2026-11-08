"""Bus d'événements « données modifiées » (temps réel).

Chaque transaction qui modifie des données annulables (tâches, projets, tags, boards…), ainsi que chaque
annulation / rétablissement, publie un :class:`ChangeEvent` : la liste des **tables** touchées, l'auteur et
l'**origine** (identifiant de la page ou de l'appareil qui a fait la modification, pour qu'il ne se
rafraîchisse pas une seconde fois). Aucun contenu n'est diffusé : les écrans abonnés relisent eux-mêmes ce
qu'ils ont le droit de voir.

Abonnés : les pages web du serveur (directement) et les clients bureau (flux SSE ``/api/v1/events``).
La publication se fait dans le fil de la transaction ; les abonnés doivent rendre la main vite.
"""

from __future__ import annotations

import itertools
import logging
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass

log = logging.getLogger("organizer.events")

ORIGIN_HEADER = "X-Organizer-Origin"


@dataclass(frozen=True)
class ChangeEvent:
    tables: tuple[str, ...]
    user_id: int
    origin: str | None = None

    @classmethod
    def of(cls, tables: Iterable[str], user_id: int, origin: str | None) -> ChangeEvent:
        return cls(tuple(sorted(set(tables))), user_id, origin)

    def to_json(self) -> dict:
        return {"tables": list(self.tables), "user_id": self.user_id, "origin": self.origin}

    @classmethod
    def from_json(cls, data: dict) -> ChangeEvent:
        return cls(tuple(data.get("tables") or ()), int(data.get("user_id") or 0), data.get("origin"))


class EventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._subscribers: dict[int, Callable[[ChangeEvent], None]] = {}

    def subscribe(self, callback: Callable[[ChangeEvent], None]) -> Callable[[], None]:
        """Abonne ``callback`` ; renvoie la fonction de désabonnement."""
        with self._lock:
            key = next(self._ids)
            self._subscribers[key] = callback

        def unsubscribe() -> None:
            with self._lock:
                self._subscribers.pop(key, None)

        return unsubscribe

    def publish(self, event: ChangeEvent) -> None:
        with self._lock:
            callbacks = list(self._subscribers.values())
        for callback in callbacks:
            try:
                callback(event)
            except Exception:  # un abonné en erreur ne doit pas faire échouer la modification
                log.exception("Abonné aux événements en erreur")

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)
