"""Sélection de plusieurs jours du calendrier au clic-glisser (voir ``day_select.js``)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from nicegui import ui


class DaySelect(ui.element, component="day_select.js"):
    def __init__(self, on_range: Callable[[date, date], None]) -> None:
        super().__init__()
        self.on(
            "range",
            lambda e: on_range(date.fromisoformat(e.args["start"]), date.fromisoformat(e.args["end"])),
        )


def selectable_day(element: ui.element, day: date) -> ui.element:
    element._props["data-cal-day"] = day.isoformat()
    return element
