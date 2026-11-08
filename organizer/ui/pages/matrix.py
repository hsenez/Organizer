"""🎯 Matrice d'Eisenhower : un « kanban en 2D ».

- Vue 2×2 : déposer une carte dans un quadrant ajuste importance / urgence au minimum nécessaire
  (``rules.matrix_drop``).
- Vue 4×4 : une case par combinaison exacte (importance × urgence) ; le dépôt fixe les deux valeurs.
Vue et filtres mémorisés (préférence ``view:matrix``). Par défaut, les tâches finies / annulées sont masquées.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import Response
from nicegui import ui

from organizer.core import rules
from organizer.core.enums import Importance, Quadrant, Status, Urgency
from organizer.core.schemas import TaskFilter, TaskOut, TaskPatch, TaskSort
from organizer.ui.components.dnd import drop_zone
from organizer.ui.components.filter_bar import FilterBar
from organizer.ui.components.task_card import task_card, task_row
from organizer.ui.context import UiContext
from organizer.ui.layout import app_frame
from organizer.ui.theme import hex_to_rgba

OPEN_STATUSES = [Status.NOT_STARTED, Status.IN_PROGRESS, Status.PAUSED]
DEFAULT_FILTER = TaskFilter(status=OPEN_STATUSES)
# Disposition classique : urgent à gauche, important en haut.
LAYOUT = [[Quadrant.DO, Quadrant.PLAN], [Quadrant.DELEGATE, Quadrant.ELIMINATE]]


def page(make_context):
    def matrix_page(request: Request):
        ctx = make_context(request)
        if isinstance(ctx, Response):
            return ctx
        with app_frame(ctx, "/matrix", "Matrice", open_task=request.query_params.get("task")):
            MatrixView(ctx)
        return None

    return matrix_page


class MatrixView:
    def __init__(self, ctx: UiContext):
        self.ctx = ctx
        prefs = ctx.ds.account.get_pref("view:matrix") or {}
        try:
            self.flt = TaskFilter.model_validate(prefs["filter"]) if prefs.get("filter") else DEFAULT_FILTER
        except ValueError:
            self.flt = DEFAULT_FILTER
        self.mode = prefs.get("mode", "2x2") if prefs.get("mode") in ("2x2", "4x4") else "2x2"

        with ui.row().classes("w-full items-center gap-2"):
            ui.label("🎯").classes("text-2xl")
            ui.label("Matrice d'Eisenhower").classes("text-2xl font-bold")
            ui.space()
            ui.toggle(
                {"2x2": "▦ 2×2", "4x4": "▦ 4×4 détaillée"}, value=self.mode, on_change=self._mode_changed
            ).props("no-caps unelevated dense").mark("matrix-mode")
        ui.label(
            "Important = importance 🟠 ou 🔴 · Urgent = urgence ⏰ ou 🔥. Glissez une carte d'une case à "
            "l'autre pour changer son importance et son urgence."
        ).classes("text-sm text-gray-500 -mt-3")
        FilterBar(ctx, self.flt, self._filter_changed, default=DEFAULT_FILTER)
        self.body = ui.refreshable(self._grid)
        self.body()
        ctx.on_refresh(self.body.refresh)
        ctx.drop_handler = self._dropped

    def _tasks(self) -> list[TaskOut]:
        return self.ctx.ds.tasks.list(self.flt, TaskSort(key="priority"))

    def _grid(self) -> None:
        tasks = self._tasks()
        if self.mode == "4x4":
            self._grid_4x4(tasks)
        else:
            self._grid_2x2(tasks)

    # --- 2×2 ---

    def _grid_2x2(self, tasks: list[TaskOut]) -> None:
        with ui.element("div").classes("matrix-2x2 w-full"):
            ui.element("div")
            for text in ("🔥 Urgent", "🐢 Pas urgent"):
                ui.label(text).classes("matrix-axis text-center")
            for row, label in zip(LAYOUT, ("⭐ Important", "Pas important"), strict=True):
                ui.label(label).classes("matrix-axis matrix-axis-v")
                for quadrant in row:
                    self._quadrant(
                        quadrant, [t for t in tasks if rules.quadrant_of(t.importance, t.urgency) is quadrant]
                    )

    def _quadrant(self, quadrant: Quadrant, tasks: list[TaskOut]) -> None:
        meta = quadrant.meta
        zone = (
            ui.column()
            .classes("matrix-cell rounded-xl p-3 gap-2")
            .style(f"background: {hex_to_rgba(meta.color, 0.07)}; border-top: 4px solid {meta.color}")
            .mark(f"zone-q:{quadrant.value}")
        )
        drop_zone(zone, f"q:{quadrant.value}")
        with zone:
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.label(meta.emoji).classes("text-xl")
                ui.label(meta.label).classes("text-lg font-semibold")
                ui.badge(str(len(tasks))).props("rounded color=grey-5 text-color=black")
                ui.space()
                ui.label(meta.tooltip.split(":", 1)[-1].strip()).classes(
                    "text-xs text-gray-500 hidden lg:block"
                )
            with ui.element("div").classes("grid gap-2 w-full grid-cols-1 2xl:grid-cols-2"):
                for task in tasks:
                    task_card(task, self.ctx)
            if not tasks:
                ui.label("Déposez une carte ici").classes("w-full text-center text-xs text-gray-400 py-6")

    # --- 4×4 ---

    def _grid_4x4(self, tasks: list[TaskOut]) -> None:
        urgencies = list(reversed(Urgency))  # urgent à gauche, comme en 2×2
        importances = list(reversed(Importance))  # important en haut
        with ui.element("div").classes("matrix-4x4 w-full overflow-x-auto"):
            ui.element("div")
            for urgency in urgencies:
                ui.label(urgency.meta.text).classes("matrix-axis text-center").tooltip(urgency.meta.tooltip)
            for importance in importances:
                ui.label(importance.meta.text).classes("matrix-axis matrix-axis-v").tooltip(
                    importance.meta.tooltip
                )
                for urgency in urgencies:
                    quadrant = rules.quadrant_of(importance, urgency)
                    cell_tasks = [t for t in tasks if t.importance is importance and t.urgency is urgency]
                    zone = (
                        ui.column()
                        .classes("matrix-cell matrix-cell-small rounded-lg p-1 gap-0")
                        .style(f"background: {hex_to_rgba(quadrant.meta.color, 0.07)}")
                        .tooltip(f"{importance.meta.label} × {urgency.meta.label} — {quadrant.meta.text}")
                        .mark(f"zone-cell:{int(importance)}:{int(urgency)}")
                    )
                    drop_zone(zone, f"cell:{int(importance)}:{int(urgency)}")
                    with zone:
                        for task in cell_tasks:
                            task_row(
                                task,
                                self.ctx,
                                on_click=lambda t=task: self.ctx.editor.open(t.id),
                                draggable_row=True,
                            )

    # --- dépôt ---

    def _dropped(self, task_id: int, zone: str, _index: int | None) -> None:
        task = self.ctx.call(self.ctx.ds.tasks.get, task_id)
        if task is None:
            return
        kind, _, value = zone.partition(":")
        if kind == "q":
            importance, urgency = rules.matrix_drop(task.importance, task.urgency, Quadrant(value))
        elif kind == "cell":
            imp, urg = value.split(":")
            importance, urgency = Importance(int(imp)), Urgency(int(urg))
        else:
            return
        if (importance, urgency) == (task.importance, task.urgency):
            return
        if self.ctx.call(
            self.ctx.ds.tasks.update, task_id, TaskPatch(importance=importance, urgency=urgency)
        ):
            self.ctx.refresh()

    # --- préférences ---

    def _save(self) -> None:
        self.ctx.ds.account.set_pref(
            "view:matrix", {"filter": self.flt.model_dump(mode="json"), "mode": self.mode}
        )

    def _filter_changed(self, flt: TaskFilter) -> None:
        self.flt = flt
        self._save()
        self.body.refresh()

    def _mode_changed(self, e) -> None:
        self.mode = e.value
        self._save()
        self.body.refresh()
