"""Recherche rapide (Ctrl+K, ou 🔍 dans l'en-tête) : résultats pendant la frappe, clic → éditeur."""

from __future__ import annotations

from urllib.parse import quote

from nicegui import ui

from organizer.core.schemas import TaskFilter, TaskSort
from organizer.ui.components.task_card import task_row
from organizer.ui.context import UiContext

MAX_RESULTS = 30


class SearchDialog:
    def __init__(self, ctx: UiContext):
        self.ctx = ctx
        with (
            ui.dialog().props("position=top") as self.dialog,
            ui.card().classes("w-[680px] max-w-[96vw] gap-2 mt-10").mark("search-dialog"),
        ):
            self.input = (
                ui.input(placeholder="🔍 Rechercher une tâche (titre, notes, tags, projet)…")
                .props("outlined autofocus clearable")
                .classes("w-full")
                .mark("search-input")
            )
            self.input.on("update:model-value", self._refresh, throttle=0.25, leading_events=False)
            self.input.on("keydown.enter", self._open_first)
            self.results = ui.column().classes("w-full gap-0 max-h-[60vh] overflow-y-auto")
            with ui.row().classes("w-full items-center"):
                ui.label("Entrée : ouvrir le premier résultat · Échap : fermer").classes(
                    "text-xs text-gray-500"
                )
                ui.space()
                ui.button("Recherche avancée →", on_click=self._full_page).props("flat no-caps dense")
        self._found: list = []

    def open(self) -> None:
        self.input.set_value("")
        self._refresh()
        self.dialog.open()
        self.input.run_method("focus")

    def _refresh(self) -> None:
        text = (self.input.value or "").strip()
        self.results.clear()
        self._found = []
        with self.results:
            if not text:
                ui.label(
                    "Tapez quelques lettres : la recherche ignore les accents et les majuscules."
                ).classes("text-sm text-gray-500 p-2")
                return
            found = self.ctx.ds.tasks.list(
                TaskFilter(text=text, include_subtasks=True), TaskSort(key="priority")
            )
            # Les tâches ouvertes d'abord, puis les terminées.
            found.sort(key=lambda t: t.status.is_closed)
            self._found = found
            if not found:
                ui.label("Aucun résultat.").classes("text-sm text-gray-500 p-2")
            for task in found[:MAX_RESULTS]:
                task_row(task, self.ctx, on_click=lambda t=task: self._open(t.id))
            if len(found) > MAX_RESULTS:
                ui.label(f"… et {len(found) - MAX_RESULTS} autres (recherche avancée)").classes(
                    "text-xs text-gray-500 p-2"
                )

    def _open(self, task_id: int) -> None:
        self.dialog.close()
        self.ctx.editor.open(task_id)

    def _open_first(self) -> None:
        self._refresh()
        if self._found:
            self._open(self._found[0].id)

    def _full_page(self) -> None:
        self.dialog.close()
        ui.navigate.to(f"/search?q={quote(self.input.value or '')}")
