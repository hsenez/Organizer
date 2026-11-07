"""Contexte d'une page ouverte : source de données, rafraîchissement, annuler / rétablir, erreurs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any, TypeVar

from nicegui import ui

from organizer.core.datasource import DataSource
from organizer.core.errors import OrganizerError, UndoConflict

T = TypeVar("T")


class UiContext:
    """Un par page ouverte (donc par onglet). Les composants s'y abonnent pour être rafraîchis après une
    modification (enregistrement, annulation…)."""

    def __init__(self, ds: DataSource, logout: Callable[[], None]):
        self.ds = ds
        self.logout = logout
        self._refreshers: list[Callable[[], Any]] = []
        self.editor: Any = None  # TaskEditor de la page (créé par le layout)

    @property
    def user(self):
        return self.ds.user

    def today(self) -> date:
        return date.today()

    # --- rafraîchissement ---

    def on_refresh(self, callback: Callable[[], Any]) -> None:
        self._refreshers.append(callback)

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
        if result is None:
            ui.notify(nothing, position="top", timeout=1500)
            return
        ui.notify(f"{done} : {result.label}", position="top", timeout=2500)
        self.refresh()
        if self.editor is not None:
            self.editor.reload()
