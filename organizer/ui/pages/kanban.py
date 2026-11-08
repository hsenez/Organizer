"""📊 Kanbans : boards prédéfinis (statut, échéance, type, projet) et boards personnalisés.

Déplacer une carte d'une colonne à l'autre (glisser-déposer) modifie l'attribut correspondant sur un board
prédéfini, ou range la carte sur un board personnalisé. Board courant : ``?board=<clé>`` (status, due, kind,
project ou id).
Sur un board prédéfini, les colonnes sont triées par urgence puis par rang manuel : la position où l'on
dépose une carte ajuste son urgence et son rang (``TaskService.move``). Sur un board personnalisé, l'ordre
est libre.
Colonnes repliables et redimensionnables. Filtres, option « masquer les terminées », colonnes repliées et
largeurs mémorisés par board (préférence ``board:<clé>``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from fastapi import Request
from fastapi.responses import Response
from nicegui import ui

from organizer.core import rules
from organizer.core.enums import DueBucket, Status, TaskKind
from organizer.core.schemas import (
    BoardIn,
    BoardPatch,
    ColumnIn,
    ColumnPatch,
    TaskFilter,
    TaskOut,
    TaskPatch,
    TaskSort,
)
from organizer.ui.components.dnd import drop_zone
from organizer.ui.components.filter_bar import FilterBar
from organizer.ui.components.resizer import Resizer, resizable, resize_handle
from organizer.ui.components.task_card import task_card
from organizer.ui.context import UiContext
from organizer.ui.layout import app_frame

PRESETS = {
    "status": ("📊", "Par statut", "Déplacer une carte change son statut"),
    "due": ("📅", "Par échéance", "Déplacer une carte change son échéance"),
    "kind": ("🗂️", "Par type", "Déplacer une carte change son type (à faire / suivi)"),
    "project": ("📁", "Par projet", "Déplacer une carte change son projet"),
}
HIDE_DONE = {
    0: "✅ Afficher toutes les tâches terminées",
    1: "🙈 Masquer les terminées depuis plus d'un jour",
    3: "🙈 Masquer les terminées depuis plus de 3 jours",
    7: "🙈 Masquer les terminées depuis plus d'une semaine",
    30: "🙈 Masquer les terminées depuis plus d'un mois",
    -1: "🙈 Masquer toutes les tâches terminées",
}
EMOJIS = "📊 🏖️ 🏠 💼 🛒 🎓 🚀 🧪 🎨 🛠️ 📚 🎉 ❤️ 🌱".split()
MIN_WIDTH, MAX_WIDTH = 200, 720


@dataclass
class Column:
    key: str  # zone de dépôt
    emoji: str
    title: str
    color: str
    tasks: list[TaskOut] = field(default_factory=list)
    tooltip: str = ""
    accept: bool = True
    denied: str = ""
    column_id: int | None = None  # boards personnalisés


def page(make_context):
    def kanban_page(request: Request):
        ctx = make_context(request)
        if isinstance(ctx, Response):
            return ctx
        boards = ctx.ds.boards.list()
        board_keys = {"status", "due", "kind", "project", *(str(b.id) for b in boards)}
        last = ctx.ds.account.get_pref("kanban:last", "status")
        key = request.query_params.get("board") or last
        if key not in board_keys:
            key = "status"
        if key != last:  # une écriture de moins à chaque visite
            ctx.ds.account.set_pref("kanban:last", key)
        with app_frame(ctx, "/kanban", "Kanbans", open_task=request.query_params.get("task"), wide=True):
            KanbanView(ctx, key, boards)
        return None

    return kanban_page


class KanbanView:
    def __init__(self, ctx: UiContext, key: str, boards):
        self.ctx = ctx
        self.key = key
        self.board = next((b for b in boards if str(b.id) == key), None)
        prefs = ctx.ds.account.get_pref(f"board:{key}") or {}
        try:
            self.flt = TaskFilter.model_validate(prefs.get("filter") or {})
        except ValueError:
            self.flt = TaskFilter()
        self.hide_done = prefs.get("hide_done", 7) if prefs.get("hide_done", 7) in HIDE_DONE else 7
        collapsed, widths = prefs.get("collapsed"), prefs.get("widths")
        self.collapsed: set[str] = {str(k) for k in collapsed} if isinstance(collapsed, list) else set()
        self.widths: dict[str, int] = (
            {str(k): int(v) for k, v in widths.items() if isinstance(v, int | float)}
            if isinstance(widths, dict)
            else {}
        )
        self.order: dict[str, list[int]] = {}  # ordre affiché des cartes, par colonne
        self.zones: dict[str, ui.element] = {}

        self._header(boards)
        with ui.row().classes("w-full items-center gap-2"):
            ui.select(HIDE_DONE, value=self.hide_done, on_change=self._hide_changed).props(
                "outlined dense options-dense"
            ).classes("w-[440px] max-w-full").mark("kanban-hide-done")
            ui.space()
            ui.label(
                "Glisser une carte pour la déplacer"
                + (" ou la reclasser (sa position règle son urgence)" if self.board is None else "")
                + " · Ctrl + déposer sur une carte : sous-tâche"
            ).classes("text-xs text-gray-500 hidden md:block")
        FilterBar(ctx, self.flt, self._filter_changed)
        self.body = ui.refreshable(self._columns)
        self.body()
        ctx.on_refresh(self.body.refresh)
        ctx.drop_handler = self._dropped
        Resizer(self._resized, min=MIN_WIDTH, max=MAX_WIDTH).mark("resizer")

    # ==================================================================================================
    # En-tête : choix du board
    # ==================================================================================================

    def _header(self, boards) -> None:
        with ui.row().classes("w-full items-center gap-2"):
            ui.label("📊").classes("text-2xl")
            ui.label("Kanbans").classes("text-2xl font-bold mr-2")
            for key, (emoji, label, tooltip) in PRESETS.items():
                self._board_button(key, f"{emoji} {label}", tooltip)
            for board in boards:
                shared = " 👥" if board.shared_with or not board.can_manage else ""
                self._board_button(str(board.id), f"{board.emoji} {board.name}{shared}", "Board personnalisé")
            ui.button("➕ Nouveau board", on_click=self._new_board_dialog).props("flat no-caps").mark(
                "new-board"
            )
        if self.board is not None:
            with ui.row().classes("w-full items-center gap-2"):
                ui.button("➕ Ajouter des tâches", on_click=self._add_tasks_dialog).props(
                    "unelevated no-caps"
                ).mark("board-add-tasks")
                if self.board.can_manage:
                    ui.button("➕ Colonne", on_click=lambda: self._column_dialog(None)).props(
                        "outline no-caps"
                    ).mark("board-add-column")
                    with ui.button("⚙️ Board").props("flat no-caps"):
                        with ui.menu().mark("board-menu"):
                            ui.menu_item("✏️ Renommer", on_click=self._rename_dialog)
                            ui.menu_item("👥 Partager…", on_click=self._share_dialog)
                            ui.menu_item("🗑️ Supprimer le board", on_click=self._delete_board).mark(
                                "board-delete"
                            )
                else:
                    ui.label("👥 Board partagé avec vous").classes("chip")

    def _board_button(self, key: str, text: str, tooltip: str) -> None:
        active = key == self.key
        ui.button(text, on_click=lambda: ui.navigate.to(f"/kanban?board={key}")).props(
            f"{'unelevated' if active else 'flat'} no-caps rounded dense"
        ).classes("px-3").tooltip(tooltip).mark(f"board-tab-{key}")

    # ==================================================================================================
    # Colonnes
    # ==================================================================================================

    def _visible(self, tasks: list[TaskOut]) -> list[TaskOut]:
        if self.hide_done == 0:
            return tasks
        if self.hide_done < 0:
            return [t for t in tasks if not t.status.is_closed]
        limit = datetime.now(UTC) - timedelta(days=self.hide_done)
        return [t for t in tasks if not t.status.is_closed or (t.completed_at or t.updated_at) >= limit]

    def _build_columns(self) -> list[Column]:
        ds, today = self.ctx.ds, self.ctx.today()
        if self.board is not None:
            content = ds.boards.content(self.board.id, self.flt)
            return [
                Column(
                    f"col:{c.id}",
                    c.emoji,
                    c.name,
                    c.color,
                    self._visible(content.columns.get(c.id, [])),
                    column_id=c.id,
                )
                for c in content.board.columns
            ]
        tasks = self._visible(ds.tasks.list(self.flt, TaskSort(key="urgency")))
        if self.key == "status":
            return [
                Column(
                    f"status:{s.value}",
                    s.meta.emoji,
                    s.meta.label,
                    s.meta.color,
                    [t for t in tasks if t.status is s],
                    s.meta.tooltip,
                )
                for s in Status
            ]
        if self.key == "kind":
            return [
                Column(
                    f"kind:{k.value}",
                    k.meta.emoji,
                    k.meta.label,
                    k.meta.color,
                    [t for t in tasks if t.kind is k],
                    k.meta.tooltip,
                )
                for k in TaskKind
            ]
        if self.key == "due":
            columns = []
            for bucket in DueBucket:
                accept = rules.bucket_accepts_drop(bucket, today)
                denied = (
                    "⚠️ Impossible de mettre une échéance dans le passé"
                    if bucket is DueBucket.OVERDUE
                    else "Il ne reste plus de jour après demain cette semaine"
                )
                columns.append(
                    Column(
                        f"due:{bucket.value}",
                        bucket.meta.emoji,
                        bucket.meta.label,
                        bucket.meta.color,
                        [t for t in tasks if rules.due_bucket(t.due_date, today) is bucket],
                        bucket.meta.tooltip,
                        accept,
                        denied,
                    )
                )
            return columns
        projects = ds.projects.list()
        known = {p.id for p in projects}
        columns = [
            Column(
                f"project:{p.id}",
                p.emoji,
                p.name,
                p.color,
                [t for t in tasks if t.project and t.project.id == p.id],
                p.description,
            )
            for p in projects
        ]
        columns.append(
            Column(
                "project:0",
                "∅",
                "Sans projet",
                "#adb5bd",
                [t for t in tasks if not t.project or t.project.id not in known],
            )
        )
        return columns

    def _columns(self) -> None:
        columns = self._build_columns()
        self.order = {c.key: [t.id for t in c.tasks] for c in columns}
        self.zones = {}
        with ui.row().classes("kanban page-fill-grow w-full gap-3 no-wrap overflow-x-auto pb-2 snap-x"):
            for index, column in enumerate(columns):
                if column.key in self.collapsed:
                    self._collapsed_column(column)
                else:
                    self._column(column, index, columns)

    def _column(self, column: Column, index: int, columns: list[Column]) -> None:
        zone = (
            ui.column()
            .classes("kanban-col shrink-0 snap-start rounded-xl p-2 gap-2")
            .style(f"border-top: 4px solid {column.color}")
        )
        if column.key in self.widths:
            zone.style(f"width: {self.widths[column.key]}px")
        drop_zone(zone, column.key, accept=column.accept, denied=column.denied, ordered=True).mark(
            f"zone-{column.key}"
        )
        resizable(zone, column.key)
        self.zones[column.key] = zone
        with zone:
            with ui.row().classes("w-full items-center gap-1 pl-1 no-wrap"):
                ui.label(column.emoji).classes("text-lg")
                ui.label(column.title).classes("font-semibold flex-1 truncate").tooltip(
                    column.tooltip or column.title
                )
                ui.badge(str(len(column.tasks))).props("rounded color=grey-5 text-color=black")
                if column.column_id is not None and self.board.can_manage:
                    self._column_menu(column, index, columns)
                ui.button(icon="first_page", on_click=lambda: self._toggle(column.key)).props(
                    "flat round dense size=sm color=grey-7"
                ).tooltip("Replier la colonne").mark(f"collapse-{column.key}")
            for task in column.tasks:
                extra = None
                if self.board is not None:

                    def extra(t=task):
                        ui.menu_item("➖ Retirer du board", on_click=lambda: self._remove(t))

                task_card(task, self.ctx, menu_extra=extra)
            if not column.tasks:
                ui.label("Déposez une carte ici" if column.accept else "—").classes(
                    "w-full text-center text-xs text-gray-400 py-6"
                )
            resize_handle()

    def _collapsed_column(self, column: Column) -> None:
        """Colonne repliée : une bande étroite (titre vertical), qui reste une zone de dépôt."""
        zone = (
            ui.column()
            .classes("kanban-col kanban-col-collapsed shrink-0 rounded-xl gap-2")
            .style(f"border-top: 4px solid {column.color}")
            .tooltip(f"{column.title} — cliquer pour déplier")
            .on("click", lambda: self._toggle(column.key))
        )
        drop_zone(zone, column.key, accept=column.accept, denied=column.denied).mark(
            f"zone-{column.key}", f"expand-{column.key}"
        )
        with zone:
            # Pas de on_click ici : le clic remonte à la bande entière (sinon double bascule).
            ui.button(icon="last_page").props("flat round dense size=sm color=grey-7")
            ui.badge(str(len(column.tasks))).props("rounded color=grey-5 text-color=black")
            ui.label(column.emoji).classes("text-lg")
            ui.label(column.title).classes("kanban-vtitle")

    def _toggle(self, key: str) -> None:
        self.collapsed ^= {key}
        self._save()
        self.body.refresh()

    def _resized(self, key: str, width: int | None) -> None:
        if width is None:
            self.widths.pop(key, None)
        else:
            self.widths[key] = max(MIN_WIDTH, min(MAX_WIDTH, int(width)))
        zone = self.zones.get(key)
        if zone is not None:  # garde l'élément d'accord avec le navigateur
            zone._style.pop("width", None)
            if width is not None:
                zone.style(f"width: {self.widths[key]}px")
            else:
                zone.update()
        self._save()

    def _column_menu(self, column: Column, index: int, columns: list[Column]) -> None:
        ids = [c.column_id for c in columns]

        def move(delta: int) -> None:
            target = index + delta
            if 0 <= target < len(ids):
                ids[index], ids[target] = ids[target], ids[index]
                if self.ctx.call(self.ctx.ds.boards.reorder_columns, self.board.id, ids):
                    self.ctx.refresh()

        def delete() -> None:
            if self.ctx.call(self.ctx.ds.boards.delete_column, column.column_id):
                ui.notify(f"🗑️ Colonne « {column.title} » supprimée — Ctrl+Z pour annuler", position="top")
                self.ctx.refresh()

        with ui.button(icon="more_vert").props("flat round dense size=sm"):
            with ui.menu():
                ui.menu_item("✏️ Modifier", on_click=lambda: self._column_dialog(column))
                ui.menu_item("⬅️ Déplacer à gauche", on_click=lambda: move(-1))
                ui.menu_item("➡️ Déplacer à droite", on_click=lambda: move(1))
                ui.menu_item("🗑️ Supprimer (cartes → 1re colonne)", on_click=delete)

    # ==================================================================================================
    # Dépôt d'une carte
    # ==================================================================================================

    def _dropped(self, task_id: int, zone: str, index: int | None) -> None:
        ds = self.ctx.ds
        kind, _, value = zone.partition(":")
        if zone in self.collapsed:
            index = None  # colonne repliée : on ne voit pas où l'on dépose
        if kind == "col":
            ok = self.ctx.attempt(ds.boards.place, self.board.id, task_id, int(value), index)
        else:
            task = self.ctx.call(ds.tasks.get, task_id)
            if task is None:
                return
            current = self.order.get(zone, [])
            # Dans sa propre colonne, on ne fait que reclasser.
            patch = None if task_id in current else self._patch_for(task, kind, value)
            order = None
            if index is not None:
                order = [i for i in current if i != task_id]
                order.insert(max(0, min(int(index), len(order))), task_id)
                if patch is None and order == current:
                    return
            if patch is None and order is None:
                return
            ok = self.ctx.call(ds.tasks.move, task_id, patch, order) is not None
        if ok:
            self.ctx.refresh()

    def _patch_for(self, task: TaskOut, kind: str, value: str) -> TaskPatch | None:
        if kind == "status" and task.status.value != value:
            return TaskPatch(status=Status(value))
        if kind == "kind" and task.kind.value != value:
            return TaskPatch(kind=TaskKind(value))
        if kind == "project":
            project_id = int(value) or None
            if (task.project.id if task.project else None) != project_id:
                return TaskPatch(project_id=project_id)
        if kind == "due":
            new_due = self.ctx.call(
                rules.due_for_bucket_drop, DueBucket(value), self.ctx.today(), task.due_date
            )
            if new_due != task.due_date and not (new_due is None and value != DueBucket.NONE.value):
                return TaskPatch(due_date=new_due)
        return None

    # ==================================================================================================
    # Préférences
    # ==================================================================================================

    def _save(self) -> None:
        self.ctx.ds.account.set_pref(
            f"board:{self.key}",
            {
                "filter": self.flt.model_dump(mode="json"),
                "hide_done": self.hide_done,
                "collapsed": sorted(self.collapsed),
                "widths": self.widths,
            },
        )

    def _filter_changed(self, flt: TaskFilter) -> None:
        self.flt = flt
        self._save()
        self.body.refresh()

    def _hide_changed(self, e) -> None:
        self.hide_done = e.value
        self._save()
        self.body.refresh()

    # ==================================================================================================
    # Boards personnalisés : dialogues
    # ==================================================================================================

    def _remove(self, task: TaskOut) -> None:
        if self.ctx.attempt(self.ctx.ds.boards.remove, self.board.id, task.id):
            ui.notify(f"➖ « {task.title} » retirée du board (la tâche existe toujours)", position="top")
            self.ctx.refresh()

    def _new_board_dialog(self) -> None:
        def create(name: str, emoji: str) -> None:
            board = self.ctx.call(self.ctx.ds.boards.create, BoardIn(name=name, emoji=emoji))
            if board is not None:
                ui.navigate.to(f"/kanban?board={board.id}")

        _name_dialog(
            "➕ Nouveau board",
            "",
            "📊",
            create,
            hint="Colonnes de départ : 📥 À faire · 🚧 En cours · ✅ Fait",
        )

    def _rename_dialog(self) -> None:
        def save(name: str, emoji: str) -> None:
            if self.ctx.call(self.ctx.ds.boards.update, self.board.id, BoardPatch(name=name, emoji=emoji)):
                ui.navigate.to(f"/kanban?board={self.board.id}")

        _name_dialog("✏️ Renommer le board", self.board.name, self.board.emoji, save)

    def _delete_board(self) -> None:
        if self.ctx.attempt(self.ctx.ds.boards.delete, self.board.id):
            ui.notify(f"🗑️ Board « {self.board.name} » supprimé — Ctrl+Z pour annuler", position="top")
            ui.navigate.to("/kanban?board=status")

    def _share_dialog(self) -> None:
        users = {u.id: f"👤 {u.display_name}" for u in self.ctx.ds.users_public() if u.id != self.ctx.user.id}
        with ui.dialog() as dialog, ui.card().classes("w-[480px] max-w-[95vw] gap-3"):
            ui.label(f"👥 Partager « {self.board.name} »").classes("text-lg font-semibold")
            ui.label("Les membres voient les tâches posées sur ce board et peuvent les déplacer.").classes(
                "text-sm"
            )
            select = (
                ui.select(users, value=self.board.shared_with, multiple=True, label="Membres")
                .props("outlined dense use-chips")
                .classes("w-full")
            )

            def save() -> None:
                if self.ctx.call(self.ctx.ds.boards.set_shares, self.board.id, list(select.value or [])):
                    dialog.close()
                    ui.notify("✔ Partage enregistré", position="top")

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Annuler", on_click=dialog.close).props("flat")
                ui.button("Enregistrer", on_click=save).props("unelevated")
        dialog.open()

    def _column_dialog(self, column: Column | None) -> None:
        with ui.dialog() as dialog, ui.card().classes("w-[440px] max-w-[95vw] gap-3").mark("column-dialog"):
            ui.label("✏️ Modifier la colonne" if column else "➕ Nouvelle colonne").classes(
                "text-lg font-semibold"
            )
            name = (
                ui.input("Nom", value=column.title if column else "")
                .props("outlined dense autofocus")
                .classes("w-full")
            )
            emoji = (
                ui.input("Emoji", value=column.emoji if column else "")
                .props("outlined dense")
                .classes("w-28")
            )
            color = ui.color_input(
                "Couleur", value=column.color if column else "#868e96", preview=True
            ).props("outlined dense")

            def save() -> None:
                title = (name.value or "").strip()
                if not title:
                    ui.notify("Le nom est obligatoire.", type="negative", position="top")
                    return
                ds = self.ctx.ds
                if column:
                    patch = ColumnPatch(name=title, emoji=emoji.value or "", color=color.value or "#868e96")
                    ok = self.ctx.call(ds.boards.update_column, column.column_id, patch)
                else:
                    data = ColumnIn(name=title, emoji=emoji.value or "", color=color.value or "#868e96")
                    ok = self.ctx.call(ds.boards.add_column, self.board.id, data)
                if ok:
                    dialog.close()
                    self.ctx.refresh()

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Annuler", on_click=dialog.close).props("flat")
                ui.button("Enregistrer", on_click=save).props("unelevated").mark("column-save")
        dialog.open()

    def _add_tasks_dialog(self) -> None:
        board = self.ctx.ds.boards.get(self.board.id)
        if not board.columns:
            ui.notify("Ajoutez d'abord une colonne.", type="warning", position="top")
            return
        on_board = {t.id for tasks in self.ctx.ds.boards.content(board.id).columns.values() for t in tasks}
        with (
            ui.dialog() as dialog,
            ui.card().classes("w-[600px] max-w-[96vw] gap-3").mark("add-tasks-dialog"),
        ):
            ui.label(f"➕ Ajouter des tâches à « {board.name} »").classes("text-lg font-semibold")
            with ui.row().classes("w-full gap-2 no-wrap"):
                text = (
                    ui.input(placeholder="🔍 Filtrer…")
                    .props("outlined dense clearable autofocus")
                    .classes("flex-1")
                )
                column = (
                    ui.select(
                        {c.id: f"{c.emoji} {c.name}".strip() for c in board.columns},
                        value=board.columns[0].id,
                        label="Dans la colonne",
                    )
                    .props("outlined dense")
                    .classes("w-48")
                )
            chosen: set[int] = set()
            results = ui.column().classes("w-full gap-0 max-h-[50vh] overflow-y-auto")

            def refresh() -> None:
                results.clear()
                found = self.ctx.ds.tasks.list(
                    TaskFilter(text=text.value or "", include_subtasks=True), TaskSort(key="priority")
                )
                found = [t for t in found if t.id not in on_board and not t.status.is_closed][:60]
                with results:
                    if not found:
                        ui.label("Aucune tâche à ajouter.").classes("text-sm text-gray-500 p-2")
                    for task in found:
                        with ui.row().classes("w-full items-center gap-2 no-wrap"):
                            ui.checkbox(
                                value=task.id in chosen,
                                on_change=lambda e, t=task: (
                                    chosen.add(t.id) if e.value else chosen.discard(t.id)
                                ),
                            ).props("dense").mark(f"add-task-{task.id}")
                            ui.label(f"{task.importance.meta.emoji} {task.title}").classes("truncate")

            def add() -> None:
                for task_id in list(chosen):
                    self.ctx.attempt(self.ctx.ds.boards.place, board.id, task_id, column.value)
                dialog.close()
                ui.notify(f"➕ {len(chosen)} tâche(s) ajoutée(s)", position="top")
                self.ctx.refresh()

            text.on("update:model-value", refresh, throttle=0.3, leading_events=False)
            refresh()
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Annuler", on_click=dialog.close).props("flat")
                ui.button("Ajouter", on_click=add).props("unelevated").mark("add-tasks-save")
        dialog.open()


def _name_dialog(title: str, name: str, emoji: str, on_save, hint: str = "") -> None:
    with ui.dialog() as dialog, ui.card().classes("w-[460px] max-w-[95vw] gap-3").mark("board-dialog"):
        ui.label(title).classes("text-lg font-semibold")
        name_input = ui.input("Nom", value=name).props("outlined dense autofocus").classes("w-full")
        emoji_input = ui.input("Emoji", value=emoji).props("outlined dense").classes("w-28")
        with ui.row().classes("gap-0 flex-wrap"):
            for e in EMOJIS:
                ui.button(e, on_click=lambda e=e: emoji_input.set_value(e)).props("flat dense").classes(
                    "text-lg px-1"
                )
        if hint:
            ui.label(hint).classes("text-xs text-gray-500")

        def save() -> None:
            value = (name_input.value or "").strip()
            if not value:
                ui.notify("Le nom est obligatoire.", type="negative", position="top")
                return
            dialog.close()
            on_save(value, emoji_input.value or "📊")

        name_input.on("keydown.enter", save)
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Annuler", on_click=dialog.close).props("flat")
            ui.button("Enregistrer", on_click=save).props("unelevated").mark("board-save")
    dialog.open()
