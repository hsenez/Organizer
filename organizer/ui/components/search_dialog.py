"""Recherche rapide (Ctrl+K, ou 🔍 dans l'en-tête) : résultats pendant la frappe (quelques notes, puis les
tâches) ; ↑ ↓ pour choisir, Entrée ou clic → éditeur (tâche) ou page Notes (note)."""

from __future__ import annotations

from urllib.parse import quote

from nicegui import ui

from organizer.core.schemas import NoteFilter, TaskFilter, TaskSort
from organizer.ui.components.task_card import task_row
from organizer.ui.context import UiContext

MAX_RESULTS = 30
MAX_NOTES = 5


class SearchDialog:
    def __init__(self, ctx: UiContext):
        self.ctx = ctx
        with (
            ui.dialog().props("position=top") as self.dialog,
            ui.card().classes("w-[680px] max-w-[96vw] gap-2 mt-10").mark("search-dialog"),
        ):
            self.input = (
                ui.input(placeholder="🔍 Rechercher une tâche ou une note (titre, texte, tags, projet)…")
                .props("outlined autofocus clearable")
                .classes("w-full")
                .mark("search-input")
            )
            self.input.on("update:model-value", self._refresh, throttle=0.25, leading_events=False)
            self.input.on("keydown.enter", self._open_selected)
            self.input.on("keydown.down", lambda: self._move(1))
            self.input.on("keydown.up", lambda: self._move(-1))
            self.results = ui.column().classes("w-full gap-0 max-h-[60vh] overflow-y-auto")
            with ui.row().classes("w-full items-center"):
                ui.label("↑ ↓ : choisir · Entrée : ouvrir · Échap : fermer").classes("text-xs text-gray-500")
                ui.space()
                ui.button("Recherche avancée →", on_click=self._full_page).props("flat no-caps dense")
        self._found: list = []
        self._rows: list[ui.row] = []
        self._selected = 0
        self._searched = ""

    def open(self) -> None:
        self.input.set_value("")
        self._refresh()
        self.dialog.open()
        self.input.run_method("focus")

    def _refresh(self) -> None:
        text = (self.input.value or "").strip()
        self.results.clear()
        self._found, self._rows, self._selected, self._searched = [], [], 0, text
        with self.results:
            if not text:
                ui.label(
                    "Tapez quelques lettres : la recherche ignore les accents et les majuscules."
                ).classes("text-sm text-gray-500 p-2")
                return
            notes = self.ctx.ds.notes.list(NoteFilter(text=text))[:MAX_NOTES]
            found = self.ctx.ds.tasks.list(
                TaskFilter(text=text, include_subtasks=True), TaskSort(key="priority")
            )
            # Les tâches ouvertes d'abord, puis les terminées.
            found.sort(key=lambda t: t.status.is_closed)
            self._found = [lambda n=n: self._open_note(n.id) for n in notes]
            self._found += [lambda t=t: self._open(t.id) for t in found]
            if not notes and not found:
                ui.label("Aucun résultat.").classes("text-sm text-gray-500 p-2")
            for index, note in enumerate(notes):
                with (
                    ui.row()
                    .classes("task-row w-full items-center gap-2 px-2 py-1.5 rounded cursor-pointer no-wrap")
                    .on("click", lambda n=note: self._open_note(n.id))
                    .mark(f"search-result-{index}", f"search-note-{note.id}") as row
                ):
                    ui.label(note.emoji).classes("text-lg")
                    ui.label(note.title).classes("flex-1 truncate font-medium")
                    ui.label("📝 Note").classes("text-xs text-gray-500")
                self._rows.append(row)
            for index, task in enumerate(found[:MAX_RESULTS], start=len(notes)):
                row = task_row(task, self.ctx, on_click=lambda t=task: self._open(t.id)).mark(
                    f"search-result-{index}"
                )
                self._rows.append(row)
            self._highlight()
            if len(found) > MAX_RESULTS:
                ui.label(f"… et {len(found) - MAX_RESULTS} autres (recherche avancée)").classes(
                    "text-xs text-gray-500 p-2"
                )

    def _open(self, task_id: int) -> None:
        self.dialog.close()
        self.ctx.editor.open(task_id)

    def _open_note(self, note_id: int) -> None:
        self.dialog.close()
        if self.ctx.open_note is not None:
            self.ctx.open_note(note_id)
        else:
            ui.navigate.to(f"/notes?note={note_id}")

    def _highlight(self) -> None:
        for index, row in enumerate(self._rows):
            if index == self._selected:
                row.classes(add="search-selected")
            else:
                row.classes(remove="search-selected")

    def _move(self, delta: int) -> None:
        if (self.input.value or "").strip() != self._searched:
            self._refresh()
        if not self._rows:
            return
        self._selected = (self._selected + delta) % len(self._rows)
        self._highlight()
        ui.run_javascript(
            f"getHtmlElement({self._rows[self._selected].id})?.scrollIntoView({{block: 'nearest'}})"
        )

    def _open_selected(self) -> None:
        if (self.input.value or "").strip() != self._searched:
            self._refresh()  # la frappe n'a pas encore été prise en compte
        if self._found:
            self._found[min(self._selected, len(self._found) - 1)]()

    def _full_page(self) -> None:
        self.dialog.close()
        ui.navigate.to(f"/search?q={quote(self.input.value or '')}")
