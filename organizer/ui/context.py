"""Contexte d'une page ouverte : source de données, rafraîchissement, annuler / rétablir, erreurs."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, TypeVar

from nicegui import ui

from organizer.core.datasource import DataSource
from organizer.core.errors import OrganizerError, UndoConflict

T = TypeVar("T")


@dataclass(frozen=True)
class Connection:
    """Par où passe la page : réseau local (``local``) ou Internet ; ``tooltip`` l'explique, ``target`` : page
    ouverte d'un clic sur l'indicateur (réglages de connexion du client bureau)."""

    local: bool
    tooltip: str
    target: str | None = None


@dataclass(frozen=True)
class Banner:
    """Avertissement affiché en haut des pages, avec un bouton qui mène où agir."""

    text: str
    tone: str = "info"  # "info" (bleu), "warning" (orange), "error" (rouge)
    action: str = "Détails"
    target: str = "/settings"
    mark: str = "banner"  # marqueur pour les tests


class UiContext:
    """Un par page ouverte (donc par onglet). Les composants s'y abonnent pour être rafraîchis après une
    modification (enregistrement, annulation…)."""

    def __init__(self, ds: DataSource, logout: Callable[[], None]):
        self.ds = ds
        self.logout = logout
        self._refreshers: list[Callable[[], Any]] = []
        self._light_refreshers: list[Callable[[], Any]] = []
        self.editor: Any = None  # Editor de la page (tâche / événement, créé par le layout)
        # Ouvre une note (page Notes : la sélectionne ; ailleurs, None : on navigue vers /notes?note=…).
        self.open_note: Callable[[int], None] | None = None
        self.dark: Any = None  # ui.dark_mode de la page (créé par le layout)
        # Dépôt d'une carte dans une zone de la page : fonction (task_id, zone, index) fournie par la page.
        self.drop_handler: Callable[[int, str, int | None], None] | None = None
        # Dépôt d'un événement (calendrier) : (identifiant de l'événement, zone, index).
        self.event_drop_handler: Callable[[int, str, int | None], None] | None = None
        # Onglets de réglages propres à la plateforme (bureau : 🔌 Connexion) : clé → (libellé, builder).
        self.extra_settings: dict[str, tuple[str, Callable[[UiContext], None]]] = {}
        # Client bureau : arrêter vraiment l'application (fermer la fenêtre ne fait que la cacher).
        self.quit: Callable[[], None] | None = None
        # Avertissements en haut des pages (bureau : mise à jour disponible). Le cadre y ajoute ceux qui
        # valent partout (mot de passe trop court).
        self.banners: list[Banner] = []
        # Indicateur « réseau local / Internet » (coin bas gauche) ; ``connection_live`` : peut changer
        # pendant que la page est ouverte (client bureau), à relire régulièrement.
        self.connection: Callable[[], Connection] | None = None
        self.connection_live = False
        self.banner_rows: dict[str, Any] = {}  # bandeaux affichés, par marqueur (pour en retirer un)
        # Temps réel (``ui/live.py``) : rafraîchissement quand les données changent ailleurs.
        self.live: Any = None
        self.dragging = False  # glisser-déposer en cours : le rafraîchissement attend la fin du geste

    @property
    def user(self):
        return self.ds.user

    def user_names(self) -> dict[int, str]:
        """Noms affichés des utilisateurs (pictogrammes de partage), gardés quelques secondes : une page en
        affiche beaucoup d'un coup."""
        cached = getattr(self, "_user_names", None)
        if cached is None or time.monotonic() - cached[0] > 30:
            names = {u.id: u.display_name or u.username for u in self.ds.users_public()}
            cached = (time.monotonic(), names)
            self._user_names = cached
        return cached[1]

    def today(self) -> date:
        return date.today()

    # --- rafraîchissement ---

    def on_refresh(self, callback: Callable[[], Any], light: bool = False) -> None:
        """``light`` : aussi appelé par un rafraîchissement léger (sans relecture de la page, ex. boutons
        annuler / rétablir)."""
        self._refreshers.append(callback)
        if light:
            self._light_refreshers.append(callback)

    def set_dragging(self, active: bool) -> None:
        self.dragging = active
        if not active and self.live is not None:
            self.live.resume()

    def refresh(self, light: bool = False) -> None:
        """Rafraîchit la page ; ``light`` : seulement ce qui ne la relit pas (boutons annuler / rétablir)."""
        for callback in list(self._light_refreshers if light else self._refreshers):
            callback()

    # --- appels protégés ---

    def call(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T | None:
        """Exécute une opération ; une erreur métier est affichée (toast rouge) au lieu de planter."""
        try:
            return fn(*args, **kwargs)
        except OrganizerError as exc:
            ui.notify(exc.message, type="negative", position="top")
            return None

    def attempt(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> bool:
        """Comme :meth:`call`, mais renvoie True si l'opération a réussi (pour celles qui renvoient None)."""
        try:
            fn(*args, **kwargs)
            return True
        except OrganizerError as exc:
            ui.notify(exc.message, type="negative", position="top")
            return False

    # --- glisser-déposer ---

    def handle_drop(self, args: dict) -> None:
        if args.get("kind") == "event":
            if self.event_drop_handler is not None:
                self.event_drop_handler(int(args["task"]), str(args["zone"]), args.get("index"))
            return
        if self.drop_handler is not None:
            self.drop_handler(int(args["task"]), str(args["zone"]), args.get("index"))

    def attach(self, args: dict) -> None:
        """Ctrl + dépôt sur une carte (ou maintien au doigt) : rattache la tâche comme sous-tâche."""
        task = self.call(self.ds.tasks.attach, int(args["task"]), int(args["parent"]))
        if task is not None:
            ui.notify(
                f"🌳 « {task.title} » → sous-tâche de « {task.parent_title} » (Ctrl+Z pour annuler)",
                position="top",
            )
            self.refresh()

    # --- annuler / rétablir ---

    def undo(self) -> None:
        self._undo_redo(self.ds.undo.undo, "↩️ Annulé", "Rien à annuler")

    def redo(self) -> None:
        self._undo_redo(self.ds.undo.redo, "↪️ Rétabli", "Rien à rétablir")

    def _undo_redo(self, action: Callable, done: str, nothing: str) -> None:
        try:
            result = action()
        except UndoConflict as exc:
            ui.notify(exc.message, type="warning", position="top", multi_line=True, timeout=8000)
            self.refresh()
            return
        except OrganizerError as exc:  # client bureau : serveur injoignable…
            ui.notify(exc.message, type="negative", position="top")
            return
        if result is None:
            ui.notify(nothing, position="top", timeout=1500)
            return
        ui.notify(f"{done} : {result.label}", position="top", timeout=2500)
        self.refresh()
        if self.editor is not None:
            self.editor.reload()
