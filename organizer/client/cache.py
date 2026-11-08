"""Mémoire du client bureau pour les données qui changent rarement (projets, tags, boards, utilisateurs,
préférences, état « annuler / rétablir »).

Chaque appel à l'API traverse le réseau : sur le réseau local ≈ 20 ms, mais par Internet (Cloudflare Tunnel)
≈ 300 ms. Relire ces listes à chaque clic coûtait plusieurs allers-retours (ouvrir l'éditeur : 5 requêtes).
Une entrée est oubliée :

- quand le temps réel signale une modification d'une table dont elle dépend (``on_change``), ou un
  événement inconnu (reconnexion : tout est oublié) ;
- quand ce poste modifie lui-même la ressource (``on_write`` : selon le chemin de la requête) ;
- au bout de ``ttl`` secondes (filet de sécurité, et seul critère pour ce qui ne publie pas d'événement :
  comptes, préférences).

Partagé par toutes les pages du client (il est rattaché à l'``ApiClient``).
"""

from __future__ import annotations

import copy
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, TypeVar

T = TypeVar("T")

EVERYTHING = "*"  # dépendance : toute modification (ex. état annuler / rétablir)

# Ressources modifiées par une requête d'écriture, selon le début de son chemin (après /api/v1).
WRITES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("/projects", ("projects",)),
    ("/tags", ("tags",)),
    ("/boards", ("boards",)),
    ("/columns", ("boards",)),
    ("/users/me/prefs/", ()),  # géré à part : la nouvelle valeur est connue (``put``)
    ("/users", ("me", "users")),
    ("/auth", ("me",)),
    # Annuler / rétablir peut faire revenir un projet, un tag, un board supprimé.
    ("/undo", ("projects", "tags", "boards")),
    ("/redo", ("projects", "tags", "boards")),
)


@dataclass
class _Entry:
    value: Any
    expires: float
    tables: frozenset[str]


class RemoteCache:
    def __init__(
        self, ttl: float = 300.0, short_ttl: float = 60.0, clock: Callable[[], float] = time.monotonic
    ):
        self.ttl = ttl
        self.short_ttl = short_ttl
        self.clock = clock
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()
        self.hits = 0  # pour les tests et le diagnostic
        self.misses = 0

    def get(self, key: str, load: Callable[[], T], tables: Iterable[str] = (), ttl: float | None = None) -> T:
        """Valeur en mémoire, sinon ``load()`` (gardée ``ttl`` secondes, oubliée si ``tables`` changent).

        Sans ``tables`` (donnée sans événement temps réel), la durée courte s'applique par défaut."""
        tables = frozenset(tables)
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.expires > self.clock():
                self.hits += 1
                return copy.copy(entry.value)  # une liste rendue peut être modifiée par l'appelant
            self.misses += 1
        value = load()
        self.put(key, value, tables, ttl)
        return copy.copy(value)

    def put(self, key: str, value: Any, tables: Iterable[str] = (), ttl: float | None = None) -> None:
        tables = frozenset(tables)
        duration = ttl if ttl is not None else (self.ttl if tables else self.short_ttl)
        with self._lock:
            self._entries[key] = _Entry(value, self.clock() + duration, tables)

    def drop(self, *prefixes: str) -> None:
        """Oublie les entrées dont la clé commence par l'un des préfixes."""
        with self._lock:
            for key in [k for k in self._entries if k.startswith(prefixes)]:
                del self._entries[key]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def on_change(self, tables: Iterable[str] | None) -> None:
        """Modification signalée par le serveur (``None`` : inconnue, tout oublier)."""
        if tables is None:
            self.clear()
            return
        changed = set(tables)
        with self._lock:
            for key in [k for k, e in self._entries.items() if EVERYTHING in e.tables or e.tables & changed]:
                del self._entries[key]

    def on_write(self, path: str) -> None:
        """Requête d'écriture de ce poste sur ``path`` : oublie ce qu'elle a pu changer. L'état « annuler /
        rétablir » change à chaque écriture (la réponse le redonne, voir ``ApiClient``)."""
        self.drop("undo")
        for prefix, keys in WRITES:
            if path.startswith(prefix):
                if keys:
                    self.drop(*keys)
                return
