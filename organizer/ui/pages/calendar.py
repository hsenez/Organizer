"""📅 Calendrier : grille de 7 colonnes (lundi → dimanche) ; vues **Mois**, **Semaine** et **6 semaines**
(‹ › : mois précédent / suivant, ou semaine par semaine).

- **Événements** (``ds.agenda``) : toute la journée ou sur plusieurs jours = **bande** qui traverse les jours
  (``rules.band_layout``) ; sinon pastille horaire dans sa case. Couleur : ``display_color``. On les glisse
  vers un autre jour (horaires et durée gardés) ; double-clic : éditeur.

- Échéances des tâches en petites pastilles de la couleur de leur **urgence** (``rules.calendar_days``) ;
  une tâche **en retard** (échéance passée, pas finie) s'affiche **aujourd'hui**, en rouge clignotant.
- Barre de filtres : événements / tâches affichés ou non (tâches masquées par défaut ; mémorisé dans la
  préférence ``view:calendar``, avec la vue), et de qui (les miens, partagés avec moi, tous) : **pas**
  mémorisé, la page s'ouvre toujours sur « Tous ».
- Pourtour des pastilles : couleur et épaisseur de l'**importance**.
- Colonne « 📥 Sans échéance » (à droite ; sous la grille sur petit écran) : tâches ouvertes sans échéance.
- Glisser une pastille vers un autre jour change son échéance ; vers « Sans échéance », la retire (et
  inversement). Zones ``day:<AAAA-MM-JJ>`` et ``undated`` (``dnd.js``).
- Clic sur une tâche ou un événement : le sélectionne ; **Suppr** (ou ⌫) le supprime (Ctrl+Z annule).
- Pictogramme devant le titre : 👥 à moi et partagé, 🤝 partagé avec moi, 👁️ lecture seule (``Ownership``).
- Clic sur une case : la sélectionne. Double-clic sur une pastille : éditeur de la tâche. Double-clic
  ailleurs dans la case : la case s'agrandit à toute la fenêtre avec les cartes complètes de ses tâches.
Le mois affiché se choisit aussi par l'adresse : ``/calendar?month=2026-11``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from fastapi import Request
from fastapi.responses import Response
from nicegui import ui

from organizer.core import rules
from organizer.core.enums import Importance, Ownership, Status, Urgency
from organizer.core.schemas import EventFilter, EventOut, EventPatch, TaskFilter, TaskOut, TaskPatch, TaskSort
from organizer.ui import format as fmt
from organizer.ui.components.agenda import Agenda, agenda_columns, moment_of
from organizer.ui.components.day_select import DaySelect, selectable_day
from organizer.ui.components.dnd import draggable, draggable_event, drop_zone
from organizer.ui.components.ownership import ownership_emoji, ownership_text
from organizer.ui.components.resizer import Resizer, resizable, resize_handle
from organizer.ui.components.task_card import confirm_delete, task_row
from organizer.ui.context import UiContext
from organizer.ui.layout import app_frame
from organizer.ui.theme import IMPORTANCE_CHIP_BORDER_PX, hex_to_rgba, readable_text

PREF_KEY = "view:calendar"
UNDATED_ZONE = "undated"
UNDATED_WIDTH = 236  # largeur par défaut de la colonne « Sans échéance » (px)
UNDATED_MIN, UNDATED_MAX = 160, 560
DAY_ZONE = "day:"
SCOPES = {"mine": "👤 Les miens", "shared": "🤝 Partagés avec moi", "all": "👥 Tous"}
VIEWS = {"month": "Mois", "week": "Semaine", "six": "6 semaines"}
SIX_WEEKS = 6
LANE_PX = 20  # hauteur d'une ligne de bandes (px)
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
        with app_frame(
            ctx,
            "/calendar",
            "Calendrier",
            open_task=request.query_params.get("task"),
            open_event=request.query_params.get("event"),
            wide=True,
        ):
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

    show_tasks: bool = False  # les échéances des tâches s'ajoutent d'un clic
    show_events: bool = True
    view: str = "month"
    undated_width: int | None = None  # None = largeur par défaut
    undated_collapsed: bool = False

    def dump(self) -> dict:
        return {
            "tasks": self.show_tasks,
            "events": self.show_events,
            "view": self.view,
            "undated": {"width": self.undated_width, "collapsed": self.undated_collapsed},
        }


def read_prefs(data) -> CalendarPrefs:
    """Tolérante : une valeur inattendue (ancienne version) redonne la valeur par défaut."""
    data = data if isinstance(data, dict) else {}
    prefs = CalendarPrefs()
    if isinstance(data.get("tasks"), bool):
        prefs.show_tasks = data["tasks"]
    if isinstance(data.get("events"), bool):
        prefs.show_events = data["events"]
    if data.get("view") in VIEWS:
        prefs.view = data["view"]
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
        # « De qui ? » n'est pas mémorisé : la page s'ouvre toujours sur « Tous » (un filtre oublié cachait
        # les événements partagés).
        self.scope = "all"
        if month is not None:  # ?month= : le mois demandé
            self.prefs.view = "month"
        self.anchor = rules.week_start(today)  # premier lundi affiché (vues Semaine et 6 semaines)
        self.undated_panel: ui.element | None = None
        self.selection: tuple[date, date] | None = None  # jours sélectionnés (premier, dernier)
        self.selected_item: tuple[str, int] | None = None  # ("task" | "event", identifiant)
        self.item_elements: dict[tuple[str, int], list[ui.element]] = {}
        self.cells: dict[date, ui.element] = {}
        self.zoomed: date | None = None
        self.tasks: dict[int, TaskOut] = {}  # tâches affichées, par identifiant (glisser-déposer)
        self.events: dict[int, EventOut] = {}  # événements affichés

        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            ui.label("📅").classes("text-2xl max-sm:hidden")
            with (
                ui.button(icon="chevron_left", on_click=lambda: self.go(-1))
                .props("flat round dense")
                .mark("calendar-prev")
            ):
                self.prev_tip = ui.tooltip()
            with (
                ui.button(icon="chevron_right", on_click=lambda: self.go(1))
                .props("flat round dense")
                .mark("calendar-next")
            ):
                self.next_tip = ui.tooltip()
            self.title = (
                ui.label().classes("text-xl sm:text-2xl font-bold whitespace-nowrap").mark("calendar-title")
            )
            ui.space()
            # Choix de la vue : dans l'en-tête sur grand écran, dans la barre des filtres sur téléphone.
            self.view_toggles: list[ui.toggle] = []
            with ui.element("div").classes("max-sm:hidden"):
                self._view_toggle().mark("calendar-view")
            self.today_button = (
                ui.button("Aujourd'hui", on_click=self.go_today)
                .props('outline no-caps padding="2px 12px"')
                .tooltip("Revenir à aujourd'hui")
                .mark("calendar-today")
            )
        self._filters()
        self.body = ui.refreshable(self._body)
        self.body()
        ctx.on_refresh(self.body.refresh)
        ctx.drop_handler = self._dropped
        ctx.event_drop_handler = self._event_dropped
        Resizer(self._resized, min=UNDATED_MIN, max=UNDATED_MAX).mark("resizer")
        DaySelect(self.select_range).mark("day-select")
        ui.keyboard(on_key=self._key, ignore=["input", "select", "button", "textarea"]).mark("calendar-keys")

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
            ui.switch("📅 Événements", value=self.prefs.show_events, on_change=self._events_toggled).props(
                "dense"
            ).tooltip("Afficher les événements").mark("calendar-show-events")
            ui.switch("📋 Tâches", value=self.prefs.show_tasks, on_change=self._tasks_toggled).props(
                "dense"
            ).tooltip("Afficher les échéances des tâches dans le calendrier").mark("calendar-show-tasks")
            self.scope_toggle = (
                ui.toggle(SCOPES, value=self.scope, on_change=self._scope_changed)
                .props("no-caps unelevated dense")
                .tooltip("De qui ? (événements et tâches)")
                .mark("calendar-scope")
            )
            self.scope_toggle.set_enabled(self.prefs.show_tasks or self.prefs.show_events)
            with ui.element("div").classes("sm:hidden"):
                self._view_toggle()
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
                for kind in (Ownership.SHARED_BY_ME, Ownership.SHARED_WITH_ME, Ownership.READ_ONLY):
                    ui.label(kind.meta.emoji).classes("ml-1 text-sm").tooltip(
                        f"{kind.meta.label} — {kind.meta.tooltip}"
                    ).mark(f"legend-{kind.value}")
                ui.label("⚠️ en retard").classes("calendar-chip calendar-chip-overdue ml-1").tooltip(
                    "Échéance passée et tâche pas finie : affichée aujourd'hui"
                )

    def _view_toggle(self) -> ui.toggle:
        toggle = (
            ui.toggle(VIEWS, value=self.prefs.view, on_change=self._view_changed)
            .props("no-caps unelevated dense")
            .tooltip("Mois · semaine · 6 semaines (défilement à la semaine)")
        )
        self.view_toggles.append(toggle)
        return toggle

    def _tasks_toggled(self, e) -> None:
        self.prefs.show_tasks = bool(e.value)
        self.scope_toggle.set_enabled(self.prefs.show_tasks or self.prefs.show_events)
        self._save_prefs()

    def _events_toggled(self, e) -> None:
        self.prefs.show_events = bool(e.value)
        self.scope_toggle.set_enabled(self.prefs.show_tasks or self.prefs.show_events)
        self._save_prefs()

    def _view_changed(self, e) -> None:
        if e.value not in VIEWS or e.value == self.prefs.view:
            return
        today = self.ctx.today()
        if e.value == "month":
            shown = self.anchor if self.prefs.view != "month" else date(self.year, self.month, 1)
            self.year, self.month = shown.year, shown.month
        elif self.prefs.view == "month":
            current = (self.year, self.month) == (today.year, today.month)
            self.anchor = rules.week_start(today if current else date(self.year, self.month, 1))
        self.prefs.view = e.value
        for toggle in self.view_toggles:  # l'autre bouton (téléphone / grand écran) suit
            if toggle.value != e.value:
                toggle.set_value(e.value)
        self._save_prefs()

    def _scope_changed(self, e) -> None:
        self.scope = e.value if e.value in SCOPES else "all"
        self.body.refresh()

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

    def _weeks(self) -> list[list[date]]:
        if self.prefs.view == "week":
            return rules.weeks_from(self.anchor, 1)
        if self.prefs.view == "six":
            return rules.weeks_from(self.anchor, SIX_WEEKS)
        return rules.month_grid(self.year, self.month)

    def _load_events(self, first: date, last: date) -> list[EventOut]:
        if not self.prefs.show_events:
            self.events = {}
            return []
        events = self.ctx.ds.agenda.list(EventFilter(start=first, end=last, scope=self.scope))
        self.events = {event.id: event for event in events}
        return events

    def _load(self) -> tuple[dict[date, list[TaskOut]], list[TaskOut]]:
        """Tâches par jour d'affichage (voir ``rules.calendar_days``) et tâches ouvertes sans échéance (les
        plus prioritaires d'abord), selon les filtres."""
        if not self.prefs.show_tasks:
            self.tasks = {}
            return {}, []
        flt = TaskFilter(scope=self.scope, include_subtasks=True, status=SHOWN_STATUSES)
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

    def _event_dropped(self, event_id: int, zone: str, _index: int | None) -> None:
        """Événement déposé sur un autre jour : il y commence, avec les mêmes horaires et la même durée."""
        if zone == UNDATED_ZONE:
            ui.notify("Un événement a toujours une date.", type="warning", position="top")
            return
        if not zone.startswith(DAY_ZONE):
            return
        try:
            day = date.fromisoformat(zone[len(DAY_ZONE) :])
        except ValueError:
            return
        event = self.events.get(event_id) or self.ctx.call(self.ctx.ds.agenda.get, event_id)
        if event is None or event.start_date == day:
            return
        shift = day - event.start_date
        patch = EventPatch(start_date=day, end_date=event.end_date + shift)
        updated = self.ctx.call(self.ctx.ds.agenda.update, event_id, patch)
        if updated is None:
            return
        self.events[event_id] = updated
        ui.notify(f"📅 « {updated.title} » → {fmt.long_date(day)} (Ctrl+Z pour annuler)", position="top")
        self.ctx.refresh()

    # --- navigation ---

    def go(self, delta: int) -> None:
        """Mois précédent / suivant ; semaine précédente / suivante dans les vues Semaine et 6 semaines."""
        if self.prefs.view == "month":
            self.year, self.month = rules.shift_month(self.year, self.month, delta)
        else:
            self.anchor += timedelta(days=7 * delta)
        self.body.refresh()

    def go_today(self) -> None:
        today = self.ctx.today()
        self.year, self.month = today.year, today.month
        self.anchor = rules.week_start(today)
        self.body.refresh()

    def _header_texts(self, weeks: list[list[date]], today: date) -> None:
        if self.prefs.view == "month":
            self.title.set_text(f"{fmt.MONTH_NAMES[self.month - 1].capitalize()} {self.year}")
            at_today = (self.year, self.month) == (today.year, today.month)
            self.prev_tip.set_text("Mois précédent")
            self.next_tip.set_text("Mois suivant")
        else:
            first, last = weeks[0][0], weeks[-1][-1]
            prefix = "Semaine du " if self.prefs.view == "week" else ""
            same_month = first.month == last.month
            start = f"{first.day}" if same_month else f"{first.day} {fmt.MONTHS[first.month - 1]}"
            joint = " au " if self.prefs.view == "week" else " → "
            self.title.set_text(f"{prefix}{start}{joint}{last.day} {fmt.MONTHS[last.month - 1]} {last.year}")
            at_today = self.anchor == rules.week_start(today)
            self.prev_tip.set_text("Semaine précédente")
            self.next_tip.set_text("Semaine suivante")
        self.today_button.set_enabled(not at_today)

    def select(self, day: date) -> None:
        """Sélectionne une case."""
        self.select_range(day, day)

    def select_range(self, first: date, last: date) -> None:
        """Sélectionne les jours de ``first`` à ``last`` (sans reconstruire la grille)."""
        first, last = min(first, last), max(first, last)
        self.selection = (first, last)
        for day, cell in self.cells.items():
            wanted = first <= day <= last
            if wanted != ("calendar-selected" in cell.classes):
                cell.classes(add="calendar-selected") if wanted else cell.classes(remove="calendar-selected")
        self._update_menu()

    # --- sélection d'une tâche / d'un événement, Suppr ---

    def _selectable(self, element: ui.element, key: tuple[str, int]) -> None:
        """Un clic sélectionne l'élément (une bande sur plusieurs semaines : tous ses morceaux)."""
        self.item_elements.setdefault(key, []).append(element)
        element.on("click.stop", lambda _, k=key: self.select_item(k))
        if key == self.selected_item:
            element.classes(add="calendar-item-selected")

    def select_item(self, key: tuple[str, int] | None) -> None:
        if key == self.selected_item:
            return
        for element in self.item_elements.get(self.selected_item, []) if self.selected_item else []:
            if not element.is_deleted:
                element.classes(remove="calendar-item-selected")
        self.selected_item = key
        for element in self.item_elements.get(key, []) if key else []:
            element.classes(add="calendar-item-selected")

    def _key(self, e) -> None:
        if not e.action.keydown or str(e.key.name) not in ("Delete", "Backspace"):
            return
        if self.selected_item is None or self.ctx.editor.dialog.value or self.zoom_dialog.value:
            return
        self.delete_selected()

    def delete_selected(self) -> None:
        """Supprime la tâche / l'événement sélectionné (Ctrl+Z annule) ; une tâche qui a des sous-tâches
        passe par la question habituelle (les supprimer aussi ou les garder)."""
        if self.selected_item is None:
            return
        kind, item_id = self.selected_item
        if kind == "event":
            event = self.events.get(item_id) or self.ctx.call(self.ctx.ds.agenda.get, item_id)
            if event is None:
                return
            if not event.can_delete:
                ui.notify(
                    "Seul son propriétaire peut supprimer cet événement.", type="warning", position="top"
                )
                return
            if self.ctx.attempt(self.ctx.ds.agenda.delete, item_id):
                self._deleted(event.title)
            return
        task = self.tasks.get(item_id) or self.ctx.call(self.ctx.ds.tasks.get, item_id)
        if task is None:
            return
        if not task.can_delete:
            ui.notify("Seul son propriétaire peut supprimer cette tâche.", type="warning", position="top")
            return
        if task.has_subtasks:
            confirm_delete(task, self.ctx, after=lambda: self.select_item(None))
            return
        if self.ctx.attempt(self.ctx.ds.tasks.delete, item_id):
            self._deleted(task.title)

    def _deleted(self, title: str) -> None:
        self.selected_item = None
        ui.notify(f"🗑️ « {title} » supprimé (Ctrl+Z pour annuler)", position="top")
        self.ctx.refresh()

    def is_selected(self, day: date) -> bool:
        return self.selection is not None and self.selection[0] <= day <= self.selection[1]

    # --- clic droit : créer ---

    def _context(self, day: date) -> None:
        """Clic droit : sélectionne la case, sauf si elle fait déjà partie de la sélection (le menu porte
        alors sur toute la sélection)."""
        if not self.is_selected(day):
            self.select(day)

    def _context_menu(self) -> None:
        with ui.context_menu().mark("calendar-menu"):
            self.menu_title = ui.label().classes("px-4 pt-2 pb-1 text-xs text-gray-500")
            ui.menu_item("📅 Nouvel événement", on_click=self.new_event).mark("calendar-new-event")
            ui.menu_item("📋 Nouvelle tâche (échéance ce jour)", on_click=self.new_task).mark(
                "calendar-new-task"
            )
        self._update_menu()

    def _update_menu(self) -> None:
        title = getattr(self, "menu_title", None)
        if title is None or title.is_deleted:
            return
        if self.selection is None:
            title.set_text("")
            return
        first, last = self.selection
        if first == last:
            title.set_text(fmt.long_date(first))
        else:
            title.set_text(f"{fmt.long_date(first)} → {fmt.long_date(last)} ({(last - first).days + 1} j)")

    def new_event(self) -> None:
        """Nouvel événement sur la sélection : de 9 h à 10 h pour un jour, toute la journée pour plusieurs."""
        first, last = self.selection or (self.ctx.today(), self.ctx.today())
        if first == last:
            self.ctx.editor.open_new_event(
                start_date=first, start_time=rules.DEFAULT_EVENT_START, end_date=first, end_time=None
            )
        else:
            self.ctx.editor.open_new_event(start_date=first, start_time=None, end_date=last, end_time=None)

    def new_task(self) -> None:
        first = self.selection[0] if self.selection else self.ctx.today()
        self.ctx.editor.open_new(due_date=first)

    # --- grille ---

    def _body(self) -> None:
        today = self.ctx.today()
        weeks = self._weeks()
        self._header_texts(weeks, today)
        days, undated = self._load()
        events = self._load_events(weeks[0][0], weeks[-1][-1])
        self.item_elements = {}
        with ui.element("div").classes("calendar-layout page-fill-grow w-full"):
            self._grid(weeks, days, events, today)
            if self.prefs.show_tasks:
                self._undated(undated, today)

    def _grid(
        self, weeks: list[list[date]], days: dict[date, list[TaskOut]], events: list[EventOut], today: date
    ) -> None:
        self.cells = {}
        bands = [e for e in events if rules.is_band(e.start_date, e.start_time, e.end_date, e.end_time)]
        timed: dict[date, list[EventOut]] = {}
        for event in events:
            if event not in bands:
                timed.setdefault(event.start_date, []).append(event)
        spans = [(e, e.start_date, _last_day(e)) for e in bands]
        grid = (
            ui.element("div")
            .classes("calendar" + (" calendar-single-week" if len(weeks) == 1 else ""))
            .style(f"grid-template-rows: auto repeat({len(weeks)}, minmax(0, 1fr))")
            .mark("calendar-grid")
        )
        with grid:
            for index, name in enumerate(fmt.DAYS):
                ui.label(name).classes("calendar-head" + (" calendar-weekend" if index >= 5 else "")).style(
                    f"grid-row: 1; grid-column: {index + 1}"
                ).tooltip(fmt.DAY_NAMES[index])
            for row, week in enumerate(weeks, start=2):
                placed = rules.band_layout(spans, week[0])
                lanes = [0] * 7  # lignes de bandes au-dessus des pastilles, par jour
                for _, start, end, lane, _before, _after in placed:
                    for col in range(start, end + 1):
                        lanes[col] = max(lanes[col], lane + 1)
                for col, day in enumerate(week):
                    self._cell(day, today, days.get(day, []), timed.get(day, []), row, col, lanes[col])
                for event, start, end, lane, before, after in placed:
                    self._band(event, row, start, end, lane, before, after)
            self._context_menu()

    def _cell(
        self,
        day: date,
        today: date,
        tasks: list[TaskOut],
        events: list[EventOut],
        row: int,
        col: int,
        lanes: int,
    ) -> None:
        css = "calendar-cell"
        if self.prefs.view == "month" and day.month != self.month:  # jour d'un mois voisin (grisé)
            css += " calendar-outside"
        if day.weekday() >= 5:
            css += " calendar-weekend"
        if day == today:
            css += " calendar-today"
            if any(rules.is_overdue(task, today) for task in tasks):
                css += " calendar-alarm"
        if self.is_selected(day):
            css += " calendar-selected"
        cell = (
            ui.element("div")
            .classes(css)
            .style(f"grid-row: {row}; grid-column: {col + 1}; --lanes: {lanes}")
            .mark(f"calendar-day-{day.isoformat()}")
            .on("click", lambda _, d=day: (self.select(d), self.select_item(None)))
            .on("dblclick", lambda _, d=day: self.zoom(d), js_handler=ZOOM_ORIGIN_JS)
            .on("contextmenu", lambda _, d=day: self._context(d))
        )
        drop_zone(cell, f"{DAY_ZONE}{day.isoformat()}")
        selectable_day(cell, day)
        self.cells[day] = cell
        with cell:
            number = str(day.day)
            if self.prefs.view != "month" and (day.day == 1 or (row, col) == (2, 0)):
                number = f"{day.day} {fmt.MONTHS[day.month - 1]}"  # repère du mois
            ui.label(number).classes("calendar-day-number")
            if tasks or events:
                with ui.element("div").classes("calendar-chips"):
                    for event in events:
                        self._event_chip(event)
                    for task in tasks:
                        self._chip(task, today)

    # --- événements ---

    def _event_tooltip(self, event: EventOut) -> str:
        lines = [
            event.title,
            fmt.event_range(event.start_date, event.start_time, event.end_date, event.end_time),
        ]
        if event.location:
            lines.append(f"📍 {event.location}")
        lines.append(f"{ownership_emoji(event, self.ctx)} {ownership_text(event, self.ctx)}".strip())
        lines.append(
            "Clic : sélectionner (Suppr : supprimer) · double-clic : ouvrir"
            + (" · glisser : changer de jour" if event.can_edit else "")
        )
        return "\n".join(lines)

    def _event_chip(self, event: EventOut) -> None:
        """Événement d'un seul jour, avec heures : rectangle à liseré de sa couleur, heure en tête."""
        color = event.display_color
        chip = (
            ui.label(_with_mark(ownership_emoji(event, self.ctx), f"{event.start_time:%H:%M} {event.title}"))
            .classes("calendar-event")
            .style(f"border-left-color: {color}; background: {hex_to_rgba(color, 0.18)}")
            .mark(f"calendar-event-{event.id}")
            .on("dblclick.stop", lambda _, i=event.id: self.ctx.editor.open_event(i))
            .tooltip(self._event_tooltip(event))
        )
        self._selectable(chip, ("event", event.id))
        if event.can_edit:
            draggable_event(chip, event)

    def _band(
        self, event: EventOut, row: int, start: int, end: int, lane: int, before: bool, after: bool
    ) -> None:
        """Bande d'un événement de plusieurs jours (ou toute la journée), qui traverse les cases d'une
        semaine ; coins carrés et flèche quand elle continue sur la semaine d'avant / d'après."""
        color = event.display_color
        text = event.title if event.all_day else f"{event.start_time:%H:%M} {event.title}"
        text = _with_mark(ownership_emoji(event, self.ctx), text)
        css = (
            "calendar-band"
            + (" calendar-band-before" if before else "")
            + (" calendar-band-after" if after else "")
        )
        band = (
            ui.label(("◂ " if before else "") + text + (" ▸" if after else ""))
            .classes(css)
            .style(
                f"grid-row: {row}; grid-column: {start + 1} / {end + 2}; --lane: {lane}; "
                f"background: {color}; color: {readable_text(color)}"
            )
            .mark(f"calendar-event-{event.id}")
            .on("dblclick.stop", lambda _, i=event.id: self.ctx.editor.open_event(i))
            .tooltip(self._event_tooltip(event))
        )
        self._selectable(band, ("event", event.id))
        if event.can_edit:
            draggable_event(band, event)

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
        text = _with_mark(ownership_emoji(task, self.ctx), text)
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
        )
        tooltip += f"{ownership_emoji(task, self.ctx)} {ownership_text(task, self.ctx)}".strip()
        tooltip += (
            "\nClic : sélectionner (Suppr : supprimer) · double-clic : ouvrir · glisser : changer l'échéance"
        )
        chip = (
            ui.label(text)
            .classes(css)
            .style(style)
            .mark(f"calendar-task-{task.id}")
            .on("dblclick.stop", lambda _, t=task.id: self.ctx.editor.open(t))
            .tooltip(tooltip)
        )
        self._selectable(chip, ("task", task.id))
        draggable(chip, task)

    # --- vue d'un jour (case agrandie) ---

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

    def _zoom_go(self, delta: int) -> None:
        self.zoomed += timedelta(days=delta)
        self.select(self.zoomed)
        self.zoom_body.refresh()

    def _day_tasks(self, day: date) -> list[TaskOut]:
        """Tâches dont l'échéance est ce jour (et, aujourd'hui, celles en retard), selon « De qui ? » — même
        si les tâches sont masquées dans la grille."""
        flt = TaskFilter(scope=self.scope, include_subtasks=True, status=SHOWN_STATUSES)
        tasks = self.ctx.ds.tasks.list(flt, TaskSort(key="priority"))
        return rules.calendar_days(tasks, self.ctx.today()).get(day, [])

    def _day_events(self, day: date) -> list[EventOut]:
        events = self.ctx.ds.agenda.list(EventFilter(start=day, end=day, scope=self.scope))
        events = [
            e for e in events if day in rules.event_days(e.start_date, e.start_time, e.end_date, e.end_time)
        ]
        self.events.update({e.id: e for e in events})
        return events

    def _zoom_content(self) -> None:
        day = self.zoomed
        if day is None:
            return
        today = self.ctx.today()
        with ui.row().classes("calendar-zoom-head w-full items-center gap-2 px-4 py-2 no-wrap"):
            ui.button(icon="chevron_left", on_click=lambda: self._zoom_go(-1)).props(
                "flat round dense"
            ).tooltip("Jour précédent").mark("zoom-prev")
            ui.button(icon="chevron_right", on_click=lambda: self._zoom_go(1)).props(
                "flat round dense"
            ).tooltip("Jour suivant").mark("zoom-next")
            ui.label(str(day.day)).classes(
                "calendar-day-number calendar-zoom-number"
                + (" calendar-today-number" if day == today else "")
            )
            weekday, month = fmt.DAY_NAMES[day.weekday()].capitalize(), fmt.MONTH_NAMES[day.month - 1]
            ui.label(f"{weekday} {day.day} {month} {day.year}").classes("text-lg sm:text-xl font-bold").mark(
                "zoom-title"
            )
            if day != today:
                ui.label(fmt.distance(day, today)).classes("text-sm text-gray-500 max-sm:hidden")
            ui.space()
            ui.button(icon="close", on_click=self.zoom_dialog.close).props("flat round").tooltip(
                "Fermer (Échap)"
            ).mark("calendar-zoom-close")
        events = self._day_events(day)
        whole = [e for e in events if e.all_day]
        timed = [e for e in events if not e.all_day]
        with ui.element("div").classes("zoom-layout").mark("calendar-zoom"):
            self._zoom_tasks(day, today)
            with ui.column().classes("zoom-agenda gap-2"):
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    ui.label("📅 Agenda").classes("font-semibold")
                    ui.label(
                        "double-clic sur une heure : nouvel événement · glisser : déplacer, bords : durée"
                    ).classes("text-xs text-gray-500 max-sm:hidden")
                if whole:
                    with ui.row().classes("w-full gap-1"):
                        for event in whole:
                            self._whole_day_bar(event)
                agenda = Agenda(
                    on_change=self._agenda_changed, on_create=self._agenda_create, on_slot=self._agenda_slot
                )
                agenda.classes("w-full").mark("agenda")
                with agenda:
                    agenda_columns(
                        day,
                        timed,
                        self.ctx.editor.open_event,
                        datetime.now() if day == today else None,
                        mark_of=lambda e: ownership_emoji(e, self.ctx),
                    )
                    with ui.context_menu().mark("agenda-menu"):
                        with ui.menu_item(on_click=self._agenda_menu_event).mark("agenda-new-event"):
                            self.slot_label = ui.label("📅 Nouvel événement")
                        ui.menu_item(
                            "📋 Nouvelle tâche (échéance ce jour)",
                            on_click=lambda: self.ctx.editor.open_new(due_date=self.zoomed),
                        )

    def _zoom_tasks(self, day: date, today: date) -> None:
        tasks = self._day_tasks(day)
        late = [t for t in tasks if rules.is_overdue(t, today)]
        due = [t for t in tasks if not rules.is_overdue(t, today)]
        with ui.column().classes("zoom-tasks gap-1").mark("zoom-tasks"):
            with ui.row().classes("w-full items-center gap-2"):
                ui.label("📋 Tâches").classes("font-semibold")
                ui.badge(str(len(tasks))).props("rounded color=grey-5 text-color=black")
            if not tasks:
                ui.label("Aucune échéance ce jour-là.").classes("text-sm text-gray-500")
            if late:
                ui.label("⚠️ En retard").classes("text-xs font-semibold text-red-600 mt-1")
                for task in late:
                    task_row(task, self.ctx, lambda _, t=task.id: self.ctx.editor.open(t))
            if late and due:
                ui.label("📅 Échéance ce jour").classes("text-xs font-semibold text-gray-500 mt-1")
            for task in due:
                task_row(task, self.ctx, lambda _, t=task.id: self.ctx.editor.open(t))

    def _whole_day_bar(self, event: EventOut) -> None:
        color = event.display_color
        text = _with_mark(ownership_emoji(event, self.ctx), event.title)
        if event.start_date != event.end_date:
            text += f" ({fmt.event_range(event.start_date, None, event.end_date, None).split('(')[-1]}"
        (
            ui.label(text)
            .classes("calendar-band zoom-whole-day")
            .style(f"background: {color}; color: {readable_text(color)}")
            .on("click", lambda i=event.id: self.ctx.editor.open_event(i))
            .tooltip(self._event_tooltip(event))
            .mark(f"zoom-event-{event.id}")
        )

    # --- agenda : glisser, créer ---

    def _agenda_changed(self, event_id: int, start: int, end: int) -> None:
        """Événement déplacé (ou un de ses bords) dans l'agenda du jour : minutes depuis minuit."""
        day = self.zoomed
        event = self.events.get(event_id) or self.ctx.call(self.ctx.ds.agenda.get, event_id)
        if day is None or event is None:
            return
        begin, finish = moment_of(day, start), moment_of(day, end)
        patch = EventPatch(
            start_date=begin.date(), start_time=begin.time(), end_date=finish.date(), end_time=finish.time()
        )
        updated = self.ctx.call(self.ctx.ds.agenda.update, event_id, patch)
        if updated is None:
            self.zoom_body.refresh()  # remet l'événement à sa place
            return
        self.events[event_id] = updated
        with self.zoom_dialog:
            ui.notify(
                f"🕐 « {updated.title} » : {begin:%H:%M} → {finish:%H:%M} (Ctrl+Z pour annuler)",
                position="top",
            )
        self.ctx.refresh()

    def _agenda_create(self, minute: int) -> None:
        """Double-clic sur une heure libre : nouvel événement d'une heure à cette heure-là."""
        if self.zoomed is None:
            return
        begin = moment_of(self.zoomed, minute)
        self.ctx.editor.open_new_event(
            start_date=begin.date(), start_time=begin.time(), end_date=begin.date(), end_time=None
        )

    def _agenda_slot(self, minute: int) -> None:
        """Clic droit sur une heure libre : le menu propose un événement à cette heure."""
        self.slot_minute = minute
        if getattr(self, "slot_label", None) is not None and not self.slot_label.is_deleted:
            self.slot_label.set_text(f"📅 Nouvel événement à {moment_of(self.zoomed, minute):%H:%M}")

    def _agenda_menu_event(self) -> None:
        self._agenda_create(getattr(self, "slot_minute", 9 * 60))


def _with_mark(mark: str, text: str) -> str:
    """Pictogramme de partage devant un texte (rien pour un élément à moi, partagé avec personne)."""
    return f"{mark} {text}" if mark else text


def _last_day(event: EventOut) -> date:
    return rules.event_days(event.start_date, event.start_time, event.end_date, event.end_time)[-1]
