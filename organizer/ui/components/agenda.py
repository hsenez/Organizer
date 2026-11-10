"""Agenda d'une journée (vue d'un jour du calendrier) : deux colonnes 0-12 h et 12-24 h, événements placés
selon leurs heures (``rules.agenda_layout``), glisser-déposer des événements et de leurs bords
(``agenda.js``)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timedelta

from nicegui import ui

from organizer.core import rules
from organizer.core.schemas import EventOut
from organizer.ui.theme import hex_to_rgba

HOURS_PER_COLUMN = 12


class Agenda(ui.element, component="agenda.js"):
    """Conteneur ; on y construit les colonnes avec :func:`agenda_columns`."""

    def __init__(
        self,
        on_change: Callable[[int, int, int], None],
        on_create: Callable[[int], None],
        on_slot: Callable[[int], None],
    ) -> None:
        super().__init__()
        self._props["step"] = rules.AGENDA_STEP
        self.on("change", lambda e: on_change(int(e.args["id"]), int(e.args["start"]), int(e.args["end"])))
        self.on("create", lambda e: on_create(int(e.args["minute"])))
        self.on("slot", lambda e: on_slot(int(e.args["minute"])))


def minutes_of(day: date, moment: datetime) -> int:
    """Minutes depuis minuit le jour ``day`` (négatif la veille, au-delà de 1440 le lendemain)."""
    return int((moment - datetime.combine(day, time(0))).total_seconds() // 60)


def moment_of(day: date, minutes: int) -> datetime:
    return datetime.combine(day, time(0)) + timedelta(minutes=minutes)


def bounds(event: EventOut) -> tuple[datetime, datetime]:
    start = datetime.combine(event.start_date, event.start_time or time(0))
    end = datetime.combine(event.end_date, event.end_time or time(0))
    return start, end


def agenda_columns(
    day: date,
    events: list[EventOut],
    on_open: Callable[[int], None],
    now: datetime | None,
    mark_of: Callable[[EventOut], str] = lambda _: "",
) -> None:
    """Les deux colonnes de la journée, avec les événements horaires (les journées entières sont affichées à
    part, au-dessus). ``mark_of`` : pictogramme de partage à placer devant le titre."""
    spans = [(event, *bounds(event)) for event in events]
    blocks = rules.agenda_layout(spans, day)
    with ui.element("div").classes("agenda-columns"):
        for column in (0, 1):
            offset = column * rules.HALF_DAY
            with ui.element("div").classes("agenda-col"):
                with ui.element("div").classes("agenda-hours"):
                    for hour in range(HOURS_PER_COLUMN):
                        ui.label(f"{offset // 60 + hour:02d}:00").classes("agenda-hour")
                track = ui.element("div").classes("agenda-track").mark(f"agenda-col-{column}")
                track._props["data-agenda-track"] = ""
                track._props["data-agenda-offset"] = str(offset)
                with track:
                    for block in (b for b in blocks if b.column == column):
                        _block(day, block, on_open, mark_of(block.key))
                    if now is not None and now.date() == day:
                        minute = minutes_of(day, now) - offset
                        if 0 <= minute < rules.HALF_DAY:
                            ui.element("div").classes("agenda-now").style(
                                f"top: {minute / rules.HALF_DAY * 100}%"
                            )


def _block(day: date, block: rules.AgendaBlock, on_open: Callable[[int], None], mark: str = "") -> None:
    event: EventOut = block.key
    start, end = bounds(event)
    first, last = minutes_of(day, start), minutes_of(day, end)
    editable = event.can_edit and 0 <= first and last <= rules.DAY_MINUTES
    color = event.display_color
    height = block.bottom - block.top
    element = (
        ui.element("div")
        .classes(
            "agenda-block"
            + ("" if block.starts else " agenda-cont-top")
            + ("" if block.ends else " agenda-cont-bottom")
        )
        .style(
            f"top: {block.top / rules.HALF_DAY * 100}%; height: {height / rules.HALF_DAY * 100}%; "
            f"left: calc({block.lane / block.lanes * 100}% + 2px); width: calc({100 / block.lanes}% - 4px); "
            f"border-left-color: {color}; background: {hex_to_rgba(color, 0.22)}"
        )
        .on("click", lambda: on_open(event.id))
        .mark(f"agenda-event-{event.id}")
    )
    element._props["data-agenda-event"] = str(event.id)
    element._props["data-start"] = str(first)
    element._props["data-end"] = str(last)
    element._props["data-editable"] = "1" if editable else "0"
    title = (
        "Glisser : déplacer · bords : changer le début / la fin · clic : ouvrir"
        if editable
        else "Clic : ouvrir"
    )
    element._props["title"] = f"{event.title} — {start:%H:%M} → {end:%H:%M}\n{title}"
    with element:
        if editable and block.starts:
            ui.element("div").classes("agenda-handle agenda-handle-start")._props["data-agenda-handle"] = (
                "start"
            )
        ui.label(f"{mark} {event.title}" if mark else event.title).classes("agenda-title")
        if height >= 30:
            ui.label(f"{start:%H:%M} – {end:%H:%M}").classes("agenda-time")
        if height >= 60 and event.location:
            ui.label(f"📍 {event.location}").classes("agenda-time")
        if editable and block.ends:
            ui.element("div").classes("agenda-handle agenda-handle-end")._props["data-agenda-handle"] = "end"
