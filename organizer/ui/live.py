"""⚡ Temps réel : rafraîchit une page quand les données changent ailleurs (autre onglet, autre appareil,
autre utilisateur).

Une :class:`LiveRefresh` par page ouverte. ``notify(event)`` peut être appelé depuis n'importe quel fil
(transaction du serveur, flux SSE du client bureau) ; la page se rafraîchit ensuite dans sa boucle :

- **pas** pour ses propres modifications (même ``origin`` : elle s'est déjà rafraîchie) ;
- avec un court délai, qui regroupe les modifications rapprochées (sauvegarde automatique…) ;
- jamais pendant un glisser-déposer (les cartes ne doivent pas changer sous le doigt) : le rafraîchissement
  attend la fin du geste.
"""

from __future__ import annotations

import asyncio

from nicegui import Client, core

from organizer.core.events import ChangeEvent
from organizer.ui.context import UiContext

DELAY = 0.4  # secondes


class LiveRefresh:
    def __init__(self, ctx: UiContext, client: Client, origin: str | None) -> None:
        self.ctx = ctx
        self.client = client
        self.origin = origin
        self.loop: asyncio.AbstractEventLoop | None = core.loop
        self._handle: asyncio.TimerHandle | None = None
        self._pending = False
        self.refreshes = 0  # pour les tests
        ctx.live = self

    @property
    def alive(self) -> bool:
        return self.client.id in Client.instances

    def notify(self, event: ChangeEvent | None = None) -> None:
        """Des données ont changé (``event`` None : on ne sait pas lesquelles, ex. après une reconnexion)."""
        if event is not None and self.origin is not None and event.origin == self.origin:
            return
        if self.loop is not None and self.alive:
            self.loop.call_soon_threadsafe(self._schedule)

    def resume(self) -> None:
        """Fin d'un glisser-déposer : applique le rafraîchissement mis en attente."""
        if self._pending:
            self._pending = False
            self._schedule()

    def _schedule(self) -> None:
        if self._handle is None and self.loop is not None:
            self._handle = self.loop.call_later(DELAY, self._run)

    def _run(self) -> None:
        self._handle = None
        if not self.alive:
            return
        if self.ctx.dragging:
            self._pending = True
            return
        self.refreshes += 1
        with self.client:
            self.ctx.refresh()
