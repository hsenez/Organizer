"""📅 Calendrier : grille du mois (7 colonnes, du lundi au dimanche), ‹ › pour changer de mois.

- Échéances des tâches en petites pastilles de la couleur de leur **urgence** (``rules.calendar_days``) ;
  une tâche **en retard** (échéance passée, pas finie) s'affiche **aujourd'hui**, en rouge clignotant.
- Barre de filtres : tâches affichées ou non, et de qui (les miennes, partagées avec moi, les deux).
  Mémorisée dans la préférence ``view:calendar``.
- Pourtour des pastilles : couleur et épaisseur de l'**importance**.
- Colonne « 📥 Sans échéance » (à droite ; sous la grille sur petit écran) : tâches ouvertes sans échéance.
- Glisser une pastille vers un autre jour change son échéance ; vers « Sans échéance », la retire (et
  inversement). Zones ``day:<AAAA-MM-JJ>`` et ``undated`` (``dnd.js``).
- Clic sur une case : la sélectionne. Double-clic sur une pastille : éditeur de la tâche. Double-clic
  ailleurs dans la case : la case s'agrandit à toute la fenêtre avec les cartes complètes de ses tâches.
Le mois affiché se choisit aussi par l'adresse : ``/calendar?month=2026-11``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import Request
from fastapi.responses import Response
from nicegui import ui

from organizer.core import rules
from organizer.core.enums import Importance, Status, Urgency
from organizer.core.schemas import TaskFilter, TaskOut, TaskPatch, TaskSort
from organizer.ui import format as fmt
from organizer.ui.components.dnd import draggable, drop_zone
from organizer.ui.components.resizer import Resizer, resizable, resize_handle
from organizer.ui.components.task_card import task_card
from organizer.ui.context import UiContext
from organizer.ui.layout import app_frame, card_grid, empty_state, section_title
from organizer.ui.theme import IMPORTANCE_CHIP_BORDER_PX, hex_to_rgba, readable_text

PREF_KEY = "view:calendar"
UNDATED_ZONE = "undated"
UNDATED_WIDTH = 236  # largeur par défaut de la colonne « Sans échéance » (px)
UNDATED_MIN, UNDATED_MAX = 160, 560
DAY_ZONE = "day:"
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


def _ring(importance: Importance) -> str:
    """Pourtour d'une pastille : couleur et épaisseur de l'importance."""
    return f"border: {IMPORTANCE_CHIP_BORDER_PX[int(importance)]}px solid {importance.meta.color};"


@dataclass
class CalendarPrefs:
    """Préférence ``view:calendar``."""

    show_tasks: bool = True
    scope: str = "all"
    undated_width: int | None = None  # None = largeur par défaut
    undated_collapsed: bool = False

    def dump(self) -> dict:
        return {
            "tasks": self.show_tasks,
            "scope": self.scope,
            "undated": {"width": self.undated_width, "collapsed": self.undated_collapsed},
        }


def read_prefs(data) -> CalendarPrefs:
    """Tolérante : une valeur inattendue (ancienne version) redonne la valeur par défaut."""
    data = data if isinstance(data, dict) else {}
    prefs = CalendarPrefs()
    if isinstance(data.get("tasks"), bool):
        prefs.show_tasks = data["tasks"]
    if data.get("scope") in SCOPES:
        prefs.scope = data["scope"]
    undated = data.get("undated") if isinstance(data.get("undated"), dict) else {}
    width = undated.get("width")
    if isinstance(width, int) and not isinstance(width, bool):
        prefs.undated_width = max(UNDATED_MIN, min(UNDATED_MAX, width))
    if isinstance(undated.get("collapsed"), bool):
        prefs.undated_collapsed = undated["collapsed"]
    return prefs


class CalendarView:
    def __init__(self, ctx: UiContext, month: tuple[int, int] | None = None):
        self.ctx = ctx
        today = ctx.today()
        self.year, self.month = month or (today.year, today.month)
        self.prefs = read_prefs(ctx.ds.account.get_pref(PREF_KEY))
        self.undated_panel: ui.element | None = None
        self.selected: date | None = None
        self.cells: dict[date, ui.element] = {}
        self.zoomed: date | None = None
        self.tasks: dict[int, TaskOut] = {}  # tâches affichées, par identifiant (glisser-déposer)

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
        self.body = ui.refreshable(self._body)
        self.body()
        ctx.on_refresh(self.body.refresh)
        ctx.drop_handler = self._dropped
        Resizer(self._resized, min=UNDATED_MIN, max=UNDATED_MAX).mark("resizer")

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
            ui.switch("📋 Tâches", value=self.prefs.show_tasks, on_change=self._tasks_toggled).props(
                "dense"
            ).tooltip("Afficher les échéances des tâches dans le calendrier").mark("calendar-show-tasks")
            self.scope_toggle = (
                ui.toggle(SCOPES, value=self.prefs.scope, on_change=self._scope_changed)
                .props("no-caps unelevated dense")
                .tooltip("Tâches de qui ?")
                .mark("calendar-scope")
            )
            self.scope_toggle.set_enabled(self.prefs.show_tasks)
            ui.space()
            with ui.row().classes("items-center gap-1 text-xs text-gray-500 max-sm:hidden"):
                ui.label("Urgence :")
                for urgency in Urgency:
                    ui.label(urgency.meta.emoji).classes("calendar-legend").style(
                        f"background: {urgency.meta.color}"
                    ).tooltip(f"Fond : urgence {urgency.meta.label} — {urgency.meta.tooltip}")
                ui.label("Importance :").classes("ml-2")
                for importance in Importance:
                    ui.label(importance.meta.emoji).classes("calendar-legend calendar-legend-ring").style(
                        _ring(importance)
                    ).tooltip(f"Pourtour : importance {importance.meta.label} — {importance.meta.tooltip}")
                ui.label("⚠️ en retard").classes("calendar-chip calendar-chip-overdue ml-1").tooltip(
                    "Échéance passée et tâche pas finie : affichée aujourd'hui"
                )

    def _tasks_toggled(self, e) -> None:
        self.prefs.show_tasks = bool(e.value)
        self.scope_toggle.set_enabled(self.prefs.show_tasks)
        self._save_prefs()

    def _scope_changed(self, e) -> None:
        self.prefs.scope = e.value if e.value in SCOPES else "all"
        self._save_prefs()

    def _save_prefs(self, refresh: bool = True) -> None:
        self.ctx.ds.account.set_pref(PREF_KEY, self.prefs.dump())
        if refresh:
            self.body.refresh()

    # --- colonne « Sans échéance » : largeur, repli ---

    def _resized(self, _key: str, width: int | None) -> None:
        self.prefs.undated_width = None if width is None else max(UNDATED_MIN, min(UNDATED_MAX, int(width)))
        panel = self.undated_panel
        if panel is not None:  # garde l'élément d'accord avec le navigateur
            panel._style.pop("width", None)
            if self.prefs.undated_width is not None:
                panel.style(f"width: {self.prefs.undated_width}px")
            else:
                panel.update()
        self._save_prefs(refresh=False)

    def toggle_undated(self) -> None:
        self.prefs.undated_collapsed = not self.prefs.undated_collapsed
        self._save_prefs()

    # --- données ---

    def _load(self) -> tuple[dict[date, list[TaskOut]], list[TaskOut]]:
        """Tâches par jour d'affichage (voir ``rules.calendar_days``) et tâches ouvertes sans échéance (les
        plus prioritaires d'abord), selon les filtres."""
        if not self.prefs.show_tasks:
            self.tasks = {}
            return {}, []
        flt = TaskFilter(scope=self.prefs.scope, include_subtasks=True, status=SHOWN_STATUSES)
        tasks = self.ctx.ds.tasks.list(flt, TaskSort(key="priority"))
        self.tasks = {task.id: task for task in tasks}
        undated = [task for task in tasks if task.due_date is None and not task.status.is_closed]
        return rules.calendar_days(tasks, self.ctx.today()), undated

    # --- glisser-déposer ---

    def _dropped(self, task_id: int, zone: str, _index: int | None) -> None:
        """Pastille déposée sur un jour (nouvelle échéance) ou sur « Sans échéance » (échéance retirée)."""
        if zone == UNDATED_ZONE:
            due = None
        elif zone.startswith(DAY_ZONE):
            try:
                due = date.fromisoformat(zone[len(DAY_ZONE) :])
            except ValueError:
                return
        else:
            return
        task = self.tasks.get(task_id) or self.ctx.call(self.ctx.ds.tasks.get, task_id)
        if task is None or task.due_date == due:
            return  # reposée là d'où elle venait
        updated = self.ctx.call(self.ctx.ds.tasks.update, task_id, TaskPatch(due_date=due))
        if updated is None:
            return
        self.tasks[task_id] = updated  # un second dépôt avant la relecture de la page part du bon état
        where = f"échéance {fmt.long_date(due)}" if due else "plus d'échéance"
        ui.notify(f"📅 « {updated.title} » → {where} (Ctrl+Z pour annuler)", position="top")
        self.ctx.refresh()

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

    def _body(self) -> None:
        today = self.ctx.today()
        self.title.set_text(f"{fmt.MONTH_NAMES[self.month - 1].capitalize()} {self.year}")
        self.today_button.set_enabled((self.year, self.month) != (today.year, today.month))
        days, undated = self._load()
        with ui.element("div").classes("calendar-layout page-fill-grow w-full"):
            self._grid(days, today)
            if self.prefs.show_tasks:
                self._undated(undated, today)

    def _grid(self, days: dict[date, list[TaskOut]], today: date) -> None:
        weeks = rules.month_grid(self.year, self.month)
        self.cells = {}
        with (
            ui.element("div")
            .classes("calendar")
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
        drop_zone(cell, f"{DAY_ZONE}{day.isoformat()}")
        self.cells[day] = cell
        with cell:
            ui.label(str(day.day)).classes("calendar-day-number")
            if tasks:
                with ui.element("div").classes("calendar-chips"):
                    for task in tasks:
                        self._chip(task, today)

    def _undated(self, tasks: list[TaskOut], today: date) -> None:
        """Colonne des tâches ouvertes sans échéance, elle aussi zone de dépôt (retirer l'échéance).
        Largeur réglable (poignée à gauche), repliable en une bande étroite qui reste une zone de dépôt."""
        if self.prefs.undated_collapsed:
            self.undated_panel = None
            strip = (
                ui.element("div")
                .classes("calendar-undated calendar-undated-collapsed")
                .tooltip("Tâches sans échéance — cliquer pour déplier")
                .on("click", self.toggle_undated)
                .mark("calendar-undated", "calendar-undated-expand")
            )
            drop_zone(strip, UNDATED_ZONE)
            with strip:
                # Pas de on_click sur le bouton : le clic remonte à la bande entière (sinon double bascule).
                ui.button(icon="first_page").props("flat round dense size=sm color=grey-7")
                ui.badge(str(len(tasks))).props("rounded color=grey-5 text-color=black")
                ui.label("📥").classes("text-lg")
                ui.label("Sans échéance").classes("kanban-vtitle")
            return
        panel = ui.element("div").classes("calendar-undated").mark("calendar-undated")
        if self.prefs.undated_width is not None:
            panel.style(f"width: {self.prefs.undated_width}px")
        drop_zone(panel, UNDATED_ZONE)
        resizable(panel, "undated", side="left")
        self.undated_panel = panel
        with panel:
            resize_handle(side="left")
            with ui.row().classes("items-center gap-2 no-wrap"):
                ui.label("📥 Sans échéance").classes("font-semibold")
                ui.badge(str(len(tasks))).props("rounded color=grey-5 text-color=black")
                ui.space()
                ui.button(icon="last_page", on_click=self.toggle_undated).props(
                    "flat round dense size=sm color=grey-7"
                ).tooltip("Replier la colonne").mark("calendar-undated-collapse")
            ui.label(
                "Glissez une pastille vers un jour pour lui donner cette échéance, ou ici pour la retirer."
            ).classes("text-xs text-gray-500")
            if tasks:
                with ui.element("div").classes("calendar-chips"):
                    for task in tasks:
                        self._chip(task, today)
            else:
                ui.label("Toutes les tâches ouvertes ont une échéance 👍").classes(
                    "text-sm text-gray-500 py-2"
                )

    def _chip(self, task: TaskOut, today: date) -> None:
        """Pastille d'une tâche : fond = urgence, pourtour = importance ; en retard = rouge clignotant ;
        finie = estompée."""
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
            style = f"background: {hex_to_rgba(urgency.color, 0.25)};"
        else:
            style = f"background: {urgency.color}; color: {readable_text(urgency.color)};"
        style += _ring(task.importance)
        if task.due_date is None:
            due = "aucune"
        else:
            due = fmt.long_date(task.due_date) + (f" à {task.due_time:%H:%M}" if task.due_time else "")
        tooltip = f"{task.title}" + (
            f"\n↳ sous-tâche de « {task.parent_title} »" if task.parent_title else ""
        )
        tooltip += f"\nÉchéance : {due}"
        if late:
            tooltip += f" — {fmt.relative(task.due_date, today)}"
        tooltip += (
            f"\nUrgence : {urgency.emoji} {urgency.label} · Importance : {task.importance.meta.emoji} "
            f"{task.importance.meta.label}\n{task.status.meta.text}\n"
            "Double-clic : ouvrir la tâche · glisser : changer l'échéance"
        )
        chip = (
            ui.label(text)
            .classes(css)
            .style(style)
            .mark(f"calendar-task-{task.id}")
            .on("dblclick.stop", lambda _, t=task.id: self.ctx.editor.open(t))
            .tooltip(tooltip)
        )
        draggable(chip, task)

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
        tasks = self._load()[0].get(day, [])
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
            if not self.prefs.show_tasks:
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
