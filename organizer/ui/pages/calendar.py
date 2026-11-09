"""📅 Calendrier : grille du mois (7 colonnes, du lundi au dimanche), ‹ › pour changer de mois.

- Échéances des tâches en petites pastilles de la couleur de leur **urgence** (``rules.calendar_days``) ;
  une tâche **en retard** (échéance passée, pas finie) s'affiche **aujourd'hui**, en rouge clignotant.
- Barre de filtres : tâches affichées ou non, et de qui (les miennes, partagées avec moi, les deux).
  Mémorisée dans la préférence ``view:calendar``.
- Clic sur une case : la sélectionne. Double-clic sur une pastille : éditeur de la tâche. Double-clic
  ailleurs dans la case : la case s'agrandit à toute la fenêtre avec les cartes complètes de ses tâches.
Le mois affiché se choisit aussi par l'adresse : ``/calendar?month=2026-11``.
"""

from __future__ import annotations

from datetime import date

from fastapi import Request
from fastapi.responses import Response
from nicegui import ui

from organizer.core import rules
from organizer.core.enums import Status, Urgency
from organizer.core.schemas import TaskFilter, TaskOut, TaskSort
from organizer.ui import format as fmt
from organizer.ui.components.task_card import task_card
from organizer.ui.context import UiContext
from organizer.ui.layout import app_frame, card_grid, empty_state, section_title
from organizer.ui.theme import hex_to_rgba, readable_text

PREF_KEY = "view:calendar"
SCOPES = {"mine": "👤 Mes tâches", "shared": "🤝 Partagées avec moi", "all": "👥 Les deux"}
# Statuts affichés : tout sauf les tâches annulées (les finies restent à leur date, estompées).
SHOWN_STATUSES = [status for status in Status if status is not Status.CANCELLED]
# Mémorise, côté navigateur, le centre de la case double-cliquée : la vue agrandie « grandit » depuis là.
ZOOM_ORIGIN_JS = """(e) => {
    const r = e.currentTarget.getBoundingClientRect(), root = document.documentElement.style;
    root.setProperty('--calendar-zoom-x', `${r.left + r.width / 2}px`);
    root.setProperty('--calendar-zoom-y', `${r.top + r.height / 2}px`);
    emit();
}"""


def page(make_context):
    def calendar_page(request: Request):
        ctx = make_context(request)
        if isinstance(ctx, Response):
            return ctx
        with app_frame(ctx, "/calendar", "Calendrier", open_task=request.query_params.get("task"), wide=True):
            CalendarView(ctx, parse_month(request.query_params.get("month")))
        return None

    return calendar_page


def parse_month(text: str | None) -> tuple[int, int] | None:
    """``"2026-11"`` → ``(2026, 11)`` ; ``None`` si absent ou invalide (on affiche alors le mois courant)."""
    try:
        year, month = (int(part) for part in (text or "").split("-"))
        date(year, month, 1)
    except ValueError:
        return None
    return year, month


def read_prefs(data) -> tuple[bool, str]:
    """Préférence ``view:calendar`` → (tâches affichées, portée). Tolérante : une valeur inattendue
    (ancienne version) redonne la valeur par défaut."""
    data = data if isinstance(data, dict) else {}
    show = data.get("tasks")
    scope = data.get("scope")
    return (show if isinstance(show, bool) else True), (scope if scope in SCOPES else "all")


class CalendarView:
    def __init__(self, ctx: UiContext, month: tuple[int, int] | None = None):
        self.ctx = ctx
        today = ctx.today()
        self.year, self.month = month or (today.year, today.month)
        self.show_tasks, self.scope = read_prefs(ctx.ds.account.get_pref(PREF_KEY))
        self.selected: date | None = None
        self.cells: dict[date, ui.element] = {}
        self.zoomed: date | None = None

        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            ui.label("📅").classes("text-2xl max-sm:hidden")
            ui.button(icon="chevron_left", on_click=lambda: self.go(-1)).props("flat round dense").tooltip(
                "Mois précédent"
            ).mark("calendar-prev")
            ui.button(icon="chevron_right", on_click=lambda: self.go(1)).props("flat round dense").tooltip(
                "Mois suivant"
            ).mark("calendar-next")
            self.title = (
                ui.label().classes("text-xl sm:text-2xl font-bold whitespace-nowrap").mark("calendar-title")
            )
            ui.space()
            self.today_button = (
                ui.button("Aujourd'hui", on_click=self.go_today)
                .props('outline no-caps padding="2px 12px"')
                .tooltip("Revenir au mois en cours")
                .mark("calendar-today")
            )
        self._filters()
        self.body = ui.refreshable(self._grid)
        self.body()
        ctx.on_refresh(self.body.refresh)

        with (
            ui.dialog()
            .props('maximized transition-show="scale" transition-hide="scale"')
            .classes("calendar-zoom")
            .on("hide", self._zoom_closed) as self.zoom_dialog
        ):
            with ui.card().classes("calendar-zoom-card w-full h-full p-0 gap-0 no-wrap"):
                self.zoom_body = ui.refreshable(self._zoom_content)
                self.zoom_body()
        ctx.on_refresh(self._refresh_zoom)

    # --- barre de filtres ---

    def _filters(self) -> None:
        with ui.row().classes("w-full items-center gap-x-4 gap-y-2 -mt-2").mark("calendar-filters"):
            ui.switch("📋 Tâches", value=self.show_tasks, on_change=self._tasks_toggled).props(
                "dense"
            ).tooltip("Afficher les échéances des tâches dans le calendrier").mark("calendar-show-tasks")
            self.scope_toggle = (
                ui.toggle(SCOPES, value=self.scope, on_change=self._scope_changed)
                .props("no-caps unelevated dense")
                .tooltip("Tâches de qui ?")
                .mark("calendar-scope")
            )
            self.scope_toggle.set_enabled(self.show_tasks)
            ui.space()
            with ui.row().classes("items-center gap-1 text-xs text-gray-500 max-sm:hidden"):
                ui.label("Urgence :")
                for urgency in Urgency:
                    ui.label(urgency.meta.emoji).classes("calendar-legend").style(
                        f"background: {urgency.meta.color}"
                    ).tooltip(f"{urgency.meta.label} — {urgency.meta.tooltip}")
                ui.label("⚠️ en retard").classes("calendar-chip calendar-chip-overdue ml-1").tooltip(
                    "Échéance passée et tâche pas finie : affichée aujourd'hui"
                )

    def _tasks_toggled(self, e) -> None:
        self.show_tasks = bool(e.value)
        self.scope_toggle.set_enabled(self.show_tasks)
        self._save_prefs()

    def _scope_changed(self, e) -> None:
        self.scope = e.value if e.value in SCOPES else "all"
        self._save_prefs()

    def _save_prefs(self) -> None:
        self.ctx.ds.account.set_pref(PREF_KEY, {"tasks": self.show_tasks, "scope": self.scope})
        self.body.refresh()

    # --- données ---

    def _days(self) -> dict[date, list[TaskOut]]:
        """Tâches par jour d'affichage (voir ``rules.calendar_days``), selon les filtres."""
        if not self.show_tasks:
            return {}
        flt = TaskFilter(scope=self.scope, include_subtasks=True, status=SHOWN_STATUSES)
        tasks = self.ctx.ds.tasks.list(flt, TaskSort(key="due"))
        return rules.calendar_days(tasks, self.ctx.today())

    # --- navigation ---

    def go(self, delta: int) -> None:
        self.year, self.month = rules.shift_month(self.year, self.month, delta)
        self.body.refresh()

    def go_today(self) -> None:
        today = self.ctx.today()
        self.year, self.month = today.year, today.month
        self.body.refresh()

    def select(self, day: date) -> None:
        """Sélectionne une case (sans reconstruire la grille)."""
        previous = self.cells.get(self.selected) if self.selected else None
        if previous is not None:
            previous.classes(remove="calendar-selected")
        self.selected = day
        if day in self.cells:
            self.cells[day].classes(add="calendar-selected")

    # --- grille ---

    def _grid(self) -> None:
        today = self.ctx.today()
        self.title.set_text(f"{fmt.MONTH_NAMES[self.month - 1].capitalize()} {self.year}")
        self.today_button.set_enabled((self.year, self.month) != (today.year, today.month))
        weeks = rules.month_grid(self.year, self.month)
        days = self._days()
        self.cells = {}
        with (
            ui.element("div")
            .classes("calendar page-fill-grow w-full")
            .style(f"grid-template-rows: auto repeat({len(weeks)}, minmax(0, 1fr))")
            .mark("calendar-grid")
        ):
            for index, name in enumerate(fmt.DAYS):
                ui.label(name).classes("calendar-head" + (" calendar-weekend" if index >= 5 else "")).tooltip(
                    fmt.DAY_NAMES[index]
                )
            for week in weeks:
                for day in week:
                    self._cell(day, today, days.get(day, []))

    def _cell(self, day: date, today: date, tasks: list[TaskOut]) -> None:
        css = "calendar-cell"
        if day.month != self.month:  # jour du mois précédent / suivant (grisé)
            css += " calendar-outside"
        if day.weekday() >= 5:
            css += " calendar-weekend"
        if day == today:
            css += " calendar-today"
            if any(rules.is_overdue(task, today) for task in tasks):
                css += " calendar-alarm"
        if day == self.selected:
            css += " calendar-selected"
        cell = (
            ui.element("div")
            .classes(css)
            .mark(f"calendar-day-{day.isoformat()}")
            .on("click", lambda _, d=day: self.select(d))
            .on("dblclick", lambda _, d=day: self.zoom(d), js_handler=ZOOM_ORIGIN_JS)
        )
        self.cells[day] = cell
        with cell:
            ui.label(str(day.day)).classes("calendar-day-number")
            if tasks:
                with ui.element("div").classes("calendar-chips"):
                    for task in tasks:
                        self._chip(task, today)

    def _chip(self, task: TaskOut, today: date) -> None:
        """Pastille d'une tâche : couleur de son urgence ; en retard = rouge clignotant ; finie = estompée."""
        urgency = task.urgency.meta
        late = rules.is_overdue(task, today)
        text = task.title
        if task.due_time and not late:
            text = f"{task.due_time:%H:%M} {text}"
        css = "calendar-chip"
        if late:
            css += " calendar-chip-overdue"
            text = f"⚠️ {text}"
            style = ""
        elif task.status.is_closed:
            css += " calendar-chip-done"
            style = f"background: {hex_to_rgba(urgency.color, 0.25)}"
        else:
            style = f"background: {urgency.color}; color: {readable_text(urgency.color)}"
        due = f"{fmt.long_date(task.due_date)}" + (f" à {task.due_time:%H:%M}" if task.due_time else "")
        tooltip = f"{task.title}\nÉchéance : {due}"
        if late:
            tooltip += f" — {fmt.relative(task.due_date, today)}"
        tooltip += (
            f"\nUrgence : {urgency.emoji} {urgency.label} · Importance : {task.importance.meta.emoji} "
            f"{task.importance.meta.label}\n{task.status.meta.text}\nDouble-clic : ouvrir la tâche"
        )
        ui.label(text).classes(css).style(style).mark(f"calendar-task-{task.id}").on(
            "dblclick.stop", lambda _, t=task.id: self.ctx.editor.open(t)
        ).tooltip(tooltip)

    # --- case agrandie ---

    def zoom(self, day: date) -> None:
        self.select(day)
        self.zoomed = day
        self.zoom_body.refresh()
        self.zoom_dialog.open()

    def _zoom_closed(self) -> None:
        self.zoomed = None

    def _refresh_zoom(self) -> None:
        if self.zoomed is not None:
            self.zoom_body.refresh()

    def _zoom_content(self) -> None:
        day = self.zoomed
        if day is None:
            return
        today = self.ctx.today()
        tasks = self._days().get(day, [])
        late = [task for task in tasks if rules.is_overdue(task, today)]
        due = [task for task in tasks if not rules.is_overdue(task, today)]
        with ui.row().classes("calendar-zoom-head w-full items-center gap-2 px-4 py-3 no-wrap"):
            ui.label(str(day.day)).classes(
                "calendar-day-number calendar-zoom-number"
                + (" calendar-today-number" if day == today else "")
            )
            ui.label(
                f"{fmt.DAY_NAMES[day.weekday()].capitalize()} {day.day} {fmt.MONTH_NAMES[day.month - 1]} "
                f"{day.year}"
            ).classes("text-xl font-bold")
            if day != today:
                ui.label(fmt.distance(day, today)).classes("text-sm text-gray-500")
            ui.space()
            ui.button(icon="close", on_click=self.zoom_dialog.close).props("flat round").tooltip(
                "Fermer (Échap)"
            ).mark("calendar-zoom-close")
        with ui.column().classes("w-full p-4 gap-4 overflow-auto").mark("calendar-zoom"):
            if not self.show_tasks:
                empty_state("🙈", "Les tâches sont masquées (filtre 📋 Tâches).")
                return
            if not tasks:
                empty_state("🌤️", "Aucune échéance ce jour-là.")
                return
            if late:
                section_title("⚠️", "En retard", len(late), "Échéance passée et tâche pas finie")
                with card_grid():
                    for task in late:
                        task_card(task, self.ctx)
            if due:
                section_title("📅", "Échéance ce jour", len(due))
                with card_grid():
                    for task in due:
                        task_card(task, self.ctx)
