"""📅 Calendrier : grille du mois (7 colonnes, du lundi au dimanche), ‹ › pour changer de mois.

Les cases sont vides pour l'instant : les événements et les échéances des tâches viendront s'y placer.
Le mois affiché se choisit aussi par l'adresse : ``/calendar?month=2026-11``.
"""

from __future__ import annotations

from datetime import date

from fastapi import Request
from fastapi.responses import Response
from nicegui import ui

from organizer.core import rules
from organizer.ui import format as fmt
from organizer.ui.context import UiContext
from organizer.ui.layout import app_frame


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


class CalendarView:
    def __init__(self, ctx: UiContext, month: tuple[int, int] | None = None):
        self.ctx = ctx
        today = ctx.today()
        self.year, self.month = month or (today.year, today.month)

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
        self.body = ui.refreshable(self._grid)
        self.body()
        ctx.on_refresh(self.body.refresh)

    # --- navigation ---

    def go(self, delta: int) -> None:
        self.year, self.month = rules.shift_month(self.year, self.month, delta)
        self.body.refresh()

    def go_today(self) -> None:
        today = self.ctx.today()
        self.year, self.month = today.year, today.month
        self.body.refresh()

    # --- grille ---

    def _grid(self) -> None:
        today = self.ctx.today()
        self.title.set_text(f"{fmt.MONTH_NAMES[self.month - 1].capitalize()} {self.year}")
        self.today_button.set_enabled((self.year, self.month) != (today.year, today.month))
        weeks = rules.month_grid(self.year, self.month)
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
                    self._cell(day, today)

    def _cell(self, day: date, today: date) -> None:
        css = "calendar-cell"
        if day.month != self.month:  # jour du mois précédent / suivant (grisé)
            css += " calendar-outside"
        if day.weekday() >= 5:
            css += " calendar-weekend"
        if day == today:
            css += " calendar-today"
        with ui.element("div").classes(css).mark(f"calendar-day-{day.isoformat()}"):
            ui.label(str(day.day)).classes("calendar-day-number").tooltip(fmt.long_date(day))
