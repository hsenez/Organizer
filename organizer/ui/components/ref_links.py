"""Liens internes dans un éditeur markdown : ``[texte](task:12)``, ``[texte](event:8)``, ``[texte](note:5)``.

- :class:`RefLinks` relie un :class:`MarkdownEditor` aux données : titres actuels des éléments cités
  (pastilles), ouverture d'un clic, recherche ouverte par « [[ » ou par un bouton (:class:`RefPicker`).
- :func:`open_ref` ouvre l'élément désigné : tâche / événement dans l'éditeur de la page, note dans la page
  Notes (``ctx.open_note`` quand on y est déjà).
"""

from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from organizer.core import rules
from organizer.core.enums import REF_EMOJI
from organizer.core.schemas import EventFilter, NoteFilter, TaskFilter, TaskSort
from organizer.ui import format as fmt
from organizer.ui.components.markdown_editor import MarkdownEditor
from organizer.ui.context import UiContext

PER_KIND = 8  # résultats par type dans la recherche


def open_ref(ctx: UiContext, target: str) -> bool:
    """Ouvre l'élément d'un lien interne ; False si ``target`` n'en est pas un."""
    found = rules.parse_ref(target)
    if found is None:
        return False
    kind, item_id = found
    if kind == "task":
        ctx.editor.open(item_id)
    elif kind == "event":
        ctx.editor.open_event(item_id)
    elif ctx.open_note is not None:
        ctx.open_note(item_id)
    else:
        ui.navigate.to(f"/notes?note={item_id}")
    return True


class RefLinks:
    """Liens internes d'un éditeur : pastilles à jour, ouverture, recherche « [[ »."""

    def __init__(self, ctx: UiContext, editor: MarkdownEditor, *, exclude: str | None = None):
        """``exclude`` : lien de l'élément édité lui-même (``note:5``), qu'on ne se propose pas de citer."""
        self.ctx = ctx
        self.editor = editor
        self.known: dict[str, dict] = {}
        self.picker = RefPicker(ctx, self._insert, exclude=exclude)
        self.update(editor.value or "")

    def update(self, text: str) -> None:
        """Résout les liens apparus dans ``text`` (une requête seulement s'il y en a de nouveaux)."""
        refs = rules.refs_in(text)
        missing = [ref for ref in refs if ref not in self.known]
        if missing:
            for found in self.ctx.ds.notes.resolve(missing):
                self.known[found.ref] = {
                    "title": found.title,
                    "emoji": found.emoji,
                    "available": found.available,
                }
        self.editor.set_refs({ref: self.known[ref] for ref in refs if ref in self.known})

    def reload(self) -> None:
        """Relit tous les titres (un élément cité a pu être renommé ou supprimé ailleurs)."""
        self.known.clear()
        self.update(self.editor.value or "")

    def pick(self) -> None:
        self.picker.open()

    def _insert(self, kind: str, item_id: int, title: str) -> None:
        self.editor.insert_ref(rules.ref_link(kind, item_id, title))


class RefPicker:
    """Recherche d'une note, d'une tâche ou d'un événement à citer (Entrée : le premier résultat)."""

    def __init__(
        self, ctx: UiContext, on_pick: Callable[[str, int, str], None], *, exclude: str | None = None
    ):
        self.ctx = ctx
        self.on_pick = on_pick
        self.exclude = exclude
        self._first: tuple[str, int, str] | None = None
        with (
            ui.dialog().props("position=top") as self.dialog,
            ui.card().classes("w-[620px] max-w-[96vw] gap-2 mt-10").mark("ref-picker"),
        ):
            ui.label("🔗 Lier à une note, une tâche ou un événement").classes("font-semibold")
            self.input = (
                ui.input(placeholder="Rechercher (titre, texte, tags, projet)…")
                .props("outlined dense autofocus clearable")
                .classes("w-full")
                .mark("ref-picker-input")
            )
            self.input.on("update:model-value", self._refresh, throttle=0.25, leading_events=False)
            self.input.on("keydown.enter", self._pick_first)
            self.results = ui.column().classes("w-full gap-0 max-h-[60vh] overflow-y-auto")
            ui.label("Entrée : le premier résultat · Échap : annuler").classes("text-xs text-gray-500")

    def open(self) -> None:
        self.input.set_value("")
        self._refresh()
        self.dialog.open()
        self.input.run_method("focus")

    def _found(self, text: str) -> list[tuple[str, int, str, str, str]]:
        """(type, id, titre, emoji, détail) : notes, puis tâches (ouvertes d'abord), puis événements."""
        ds = self.ctx.ds
        today = self.ctx.today()
        notes = ds.notes.list(NoteFilter(text=text))
        found = [("note", n.id, n.title, n.emoji, "") for n in notes]
        if text:
            tasks = ds.tasks.list(TaskFilter(text=text, include_subtasks=True), TaskSort(key="priority"))
            tasks.sort(key=lambda t: t.status.is_closed)
            for t in tasks:
                due = fmt.short_date(t.due_date, today) if t.due_date else ""
                found.append(("task", t.id, t.title, REF_EMOJI["task"], due))
            events = ds.agenda.list(EventFilter(text=text))
            events.sort(key=lambda e: e.start_date, reverse=True)
            for e in events:
                found.append(
                    ("event", e.id, e.title, REF_EMOJI["event"], fmt.short_date(e.start_date, today))
                )
        found = [f for f in found if f"{f[0]}:{f[1]}" != self.exclude]
        per_kind: dict[str, int] = {}
        kept = []
        for item in found:
            per_kind[item[0]] = per_kind.get(item[0], 0) + 1
            if per_kind[item[0]] <= PER_KIND:
                kept.append(item)
        return kept

    def _refresh(self) -> None:
        text = (self.input.value or "").strip()
        found = self._found(text)
        self._first = found[0][:3] if found else None
        self.results.clear()
        with self.results:
            if not found:
                ui.label("Aucun résultat." if text else "Tapez quelques lettres.").classes(
                    "text-sm text-gray-500 p-2"
                )
            for kind, item_id, title, emoji, detail in found:
                with (
                    ui.row()
                    .classes("task-row w-full items-center gap-2 px-2 py-1.5 rounded cursor-pointer no-wrap")
                    .on("click", lambda k=kind, i=item_id, t=title: self._pick(k, i, t))
                    .mark(f"ref-pick-{kind}-{item_id}")
                ):
                    ui.label(emoji).classes("text-lg")
                    ui.label(title).classes("flex-1 truncate")
                    if detail:
                        ui.label(detail).classes("text-xs text-gray-500")

    def _pick(self, kind: str, item_id: int, title: str) -> None:
        self.dialog.close()
        self.on_pick(kind, item_id, title)

    def _pick_first(self) -> None:
        self._refresh()
        if self._first is not None:
            self._pick(*self._first)
