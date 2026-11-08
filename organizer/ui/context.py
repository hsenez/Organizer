"""Contexte d'une page ouverte : source de données, rafraîchissement, annuler / rétablir, erreurs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, TypeVar

from nicegui import ui

from organizer.core.datasource import DataSource
from organizer.core.errors import OrganizerError, UndoConflict

T = TypeVar("T")


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
        self.editor: Any = None  # TaskEditor de la page (créé par le layout)
        self.dark: Any = None  # ui.dark_mode de la page (créé par le layout)
        # Dépôt d'une carte dans une zone de la page : fonction (task_id, zone, index) fournie par la page.
        self.drop_handler: Callable[[int, str, int | None], None] | None = None
        # Onglets de réglages propres à la plateforme (bureau : 🔌 Connexion) : clé → (libellé, builder).
        self.extra_settings: dict[str, tuple[str, Callable[[UiContext], None]]] = {}
        # Client bureau : arrêter vraiment l'application (fermer la fenêtre ne fait que la cacher).
        self.quit: Callable[[], None] | None = None
        # Avertissements en haut des pages (bureau : mise à jour disponible). Le cadre y ajoute ceux qui
        # valent partout (mot de passe trop court).
        self.banners: list[Banner] = []
        self.banner_rows: dict[str, Any] = {}  # bandeaux affichés, par marqueur (pour en retirer un)
        # Temps réel (``ui/live.py``) : rafraîchissement quand les données changent ailleurs.
        self.live: Any = None
        self.dragging = False  # glisser-déposer en cours : le rafraîchissement attend la fin du geste

    @property
    def user(self):
        return self.ds.user

    def today(self) -> date:
        return date.today()

    # --- rafraîchissement ---

    def on_refresh(self, callback: Callable[[], Any]) -> None:
        self._refreshers.append(callback)

    def set_dragging(self, active: bool) -> None:
        self.dragging = active
        if not active and self.live is not None:
            self.live.resume()

    def refresh(self) -> None:
        for callback in list(self._refreshers):
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
