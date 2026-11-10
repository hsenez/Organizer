"""Éditeur d'événement (voir :mod:`organizer.ui.components.item_editor` : panneau et partie commune) :
début / fin (ou toute la journée), lieu (Google Maps, Waze), couleur, public, partage modifiable ou non.

Un événement en **lecture seule** pour l'utilisateur (public, ou partagé sans droit de modification)
s'affiche sans champs de saisie.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

from nicegui import ui

from organizer.core import rules
from organizer.core.enums import EVENT_DEFAULT_COLOR, EVENT_PALETTE, LinkKind
from organizer.core.errors import OrganizerError
from organizer.core.models import utcnow
from organizer.core.schemas import EventCreate, EventOut, EventPatch, EventTimes, ShareSpec
from organizer.ui import format as fmt
from organizer.ui.components.item_editor import ItemEditor, open_link, parse_date, parse_time
from organizer.ui.components.tag_chips import tag_chip

TIME_KEYS = ("start_date", "start_time", "end_date", "end_time")
# Champs propres aux événements, réappliqués s'il redevient un événement dans la même session.
EVENT_SPECIFIC = (*TIME_KEYS, "location", "color", "is_public")


class EventEditor(ItemEditor):
    kind = "event"
    noun = "l'événement"
    created_text = "✔ Événement créé"
    new_label = "✨ Nouvel événement"
    creation_hint = "L'événement sera créé dès que vous lui aurez donné un titre."
    title_placeholder = "Quel événement ?"

    @property
    def event(self) -> EventOut | None:
        return self.item

    @property
    def service(self):
        return self.ds.agenda

    def _create(self, title: str, fields: dict) -> EventOut:
        return self.ds.agenda.create(EventCreate(title=title, **fields))

    def _update(self, item_id: int, fields: dict) -> EventOut:
        return self.ds.agenda.update(item_id, EventPatch(**fields))

    def _upload_fn(self):
        return self.ds.attachments.upload_event

    # --- bascule ---

    def specific_from(self, other: ItemEditor) -> dict:
        """Depuis un brouillon de tâche : il commence à l'échéance (ou aujourd'hui à 9 h), une heure."""
        draft = other.draft or {}
        span = rules.event_times_from_due(draft.get("due_date"), draft.get("due_time"), self.ctx.today())
        return dict(zip(TIME_KEYS, span, strict=True))

    def specific_of_item(self) -> dict:
        return {key: getattr(self.event, key) for key in EVENT_SPECIFIC}

    def convert_from(self, other: ItemEditor) -> Any:
        """Tâche → événement, en reprenant (même action) horaires, lieu, couleur et visibilité gardés d'une
        conversion précédente."""
        if not self.stash:
            return self.ctx.call(self.ds.agenda.from_task, other.item.id)
        times = EventTimes(**{k: self.stash[k] for k in TIME_KEYS})
        extra = EventPatch(**{k: self.stash[k] for k in ("location", "color", "is_public")})
        return self.ctx.call(self.ds.agenda.from_task, other.item.id, times, extra)

    def _draft_out(self) -> EventOut:
        d = self.draft or {}
        today = self.ctx.today()
        values = [d.get(key) for key in TIME_KEYS]
        if values[0] is None:
            values = list(rules.event_times_from_due(None, None, today))
            self.draft.update(dict(zip(TIME_KEYS, values, strict=True)))
        try:
            start_date, start_time, end_date, end_time = rules.event_span(*values)
        except OrganizerError:
            start_date, start_time, end_date, end_time = values[0], values[1], values[0], values[1]
        projects = {p.id: p for p in self.ds.projects.list()}
        tags = {t.id: t for t in self.ds.tags.list()}
        project = projects.get(d.get("project_id"))
        now = utcnow()
        return EventOut(
            id=0,
            owner_id=self.ctx.user.id,
            title=d.get("title", ""),
            notes=d.get("notes", ""),
            project=project,
            tags=[tags[i] for i in d.get("tag_ids", []) if i in tags],
            created_at=now,
            updated_at=now,
            start_date=start_date,
            start_time=start_time,
            end_date=end_date,
            end_time=end_time,
            all_day=start_time is None,
            location=d.get("location", ""),
            color=d.get("color"),
            display_color=d.get("color") or (project.color if project else EVENT_DEFAULT_COLOR),
            is_public=d.get("is_public", False),
            can_edit=True,
        )

    # ==================================================================================================
    # Construction
    # ==================================================================================================

    def _build_content(self, event: EventOut) -> None:
        if not self.is_draft and not event.can_edit:
            self._read_only(event)
            return
        self._header(event)
        self._title(event)
        self._times(event)
        self._location(event)
        self._colors(event)
        self._labels(event)
        if self.is_draft:
            self._public(event)
            ui.label(
                "🔗 Liens, fichiers et 👥 partage : disponibles dès que l'événement a un titre."
            ).classes("text-sm text-gray-500")
            self._notes(event)
            return
        if event.owner_id == self.ctx.user.id:
            self._public(event)
            self._sharing(event)
        self.links_box = ui.column().classes("w-full gap-1")
        self._links()
        self._notes(event)
        self._footer(event)

    # --- début / fin ---

    def _times(self, event: EventOut) -> None:
        with (
            ui.column()
            .classes("w-full gap-2 p-3 rounded-lg")
            .style(f"background: {event.display_color}14; border-left: 4px solid {event.display_color}")
        ):
            with ui.row().classes("w-full items-center gap-3"):
                ui.switch(
                    "🌙 Toute la journée", value=event.all_day, on_change=lambda e: self._all_day(e.value)
                ).props("dense").mark("editor-all-day")
                ui.label(
                    fmt.event_range(event.start_date, event.start_time, event.end_date, event.end_time)
                ).classes("text-sm text-gray-600 dark:text-gray-300").mark("editor-range")
            with ui.row().classes("w-full items-center gap-2"):
                ui.label("Début").classes("w-10 text-sm text-gray-500")
                ui.date_input(
                    value=event.start_date.isoformat(), on_change=lambda e: self._start_changed(date_=e.value)
                ).props("outlined dense").classes("w-44").mark("editor-start-date")
                if not event.all_day:
                    ui.input(
                        value=event.start_time.strftime("%H:%M"),
                        on_change=lambda e: self._start_changed(time_=e.value),
                    ).props("outlined dense type=time").classes("w-32").mark("editor-start-time")
            with ui.row().classes("w-full items-center gap-2"):
                ui.label("Fin").classes("w-10 text-sm text-gray-500")
                ui.date_input(
                    value=event.end_date.isoformat(), on_change=lambda e: self._end_changed(date_=e.value)
                ).props("outlined dense").classes("w-44").mark("editor-end-date")
                if not event.all_day:
                    ui.input(
                        value=event.end_time.strftime("%H:%M"),
                        on_change=lambda e: self._end_changed(time_=e.value),
                    ).props("outlined dense type=time").classes("w-32").mark("editor-end-time")

    def _bounds(self) -> tuple[datetime, datetime]:
        e = self.event
        start = datetime.combine(e.start_date, e.start_time or time(0))
        end = datetime.combine(e.end_date, e.end_time or time(0))
        return start, end

    def _save_times(self, start: datetime, end: datetime, all_day: bool) -> None:
        if all_day:
            fields = {
                "start_date": start.date(),
                "start_time": None,
                "end_date": end.date(),
                "end_time": None,
            }
        else:
            fields = {
                "start_date": start.date(),
                "start_time": start.time(),
                "end_date": end.date(),
                "end_time": end.time(),
            }
        current = {key: getattr(self.event, key) for key in TIME_KEYS}
        if fields != current:
            self._save(rebuild=True, **fields)

    def _all_day(self, value: bool) -> None:
        if value == self.event.all_day:
            return
        start, _ = self._bounds()
        if value:
            last = rules.event_days(*(getattr(self.event, key) for key in TIME_KEYS))[-1]
            self._save_times(start, datetime.combine(last, time(0)), all_day=True)
        else:
            begin = datetime.combine(self.event.start_date, rules.DEFAULT_EVENT_START)
            self._save_times(begin, begin + rules.DEFAULT_EVENT_DURATION, all_day=False)

    def _start_changed(self, date_: str | None = None, time_: str | None = None) -> None:
        """Nouveau début : la durée est gardée (la fin suit)."""
        start, end = self._bounds()
        new_date = parse_date(date_) if date_ is not None else start.date()
        new_time = parse_time(time_) if time_ is not None else start.time()
        if new_date is None or new_time is None:
            return
        new_start = datetime.combine(new_date, new_time)
        self._save_times(new_start, new_start + (end - start), all_day=self.event.all_day)

    def _end_changed(self, date_: str | None = None, time_: str | None = None) -> None:
        start, end = self._bounds()
        new_date = parse_date(date_) if date_ is not None else end.date()
        new_time = parse_time(time_) if time_ is not None else end.time()
        if new_date is None or new_time is None:
            return
        new_end = datetime.combine(new_date, new_time)
        if self.is_draft and new_end < start + (timedelta(0) if self.event.all_day else timedelta(minutes=1)):
            ui.notify("La fin doit être après le début.", type="warning", position="top")
            self._build()
            return
        self._save_times(start, new_end, all_day=self.event.all_day)

    # --- lieu, couleur ---

    def _location(self, event: EventOut) -> None:
        with ui.row().classes("w-full items-center gap-1 no-wrap"):
            place = (
                ui.input("📍 Lieu", value=event.location, placeholder="Adresse, nom ou lien Google Maps")
                .props("outlined dense clearable")
                .classes("flex-1")
                .mark("editor-location")
            )

            def save() -> None:
                value = (place.value or "").strip()
                if value != self.event.location:
                    self._save(rebuild=True, location=value)

            place.on("blur", save)
            place.on("keydown.enter", save)
            place.on("clear", save)
            self._map_buttons(event.location)

    def _map_buttons(self, location: str) -> None:
        maps, waze = rules.maps_url(location), rules.waze_url(location)
        if maps:
            ui.button("🗺️", on_click=lambda: self._open_url(maps)).props("flat round dense").tooltip(
                "Ouvrir dans Google Maps"
            ).mark("editor-maps")
        if waze:
            ui.button("🚗", on_click=lambda: self._open_url(waze)).props("flat round dense").tooltip(
                "Y aller avec Waze"
            ).mark("editor-waze")

    def _open_url(self, url: str) -> None:
        self.ctx.call(open_link, LinkKind.URL, url, self.ds)

    def _colors(self, event: EventOut) -> None:
        with ui.row().classes("w-full items-center gap-1.5"):
            ui.label("🎨 Couleur").classes("text-sm text-gray-500 mr-1")
            auto = event.project.color if event.project else EVENT_DEFAULT_COLOR
            (
                ui.button("Auto", on_click=lambda: self._color(None))
                .props("dense no-caps unelevated size=sm")
                .style(f"background: {auto} !important; color: white")
                .classes("rounded-full px-2" + (" calendar-swatch-on" if event.color is None else ""))
                .tooltip("Couleur du projet (ou couleur par défaut)")
                .mark("editor-color-auto")
            )
            for color in EVENT_PALETTE:
                ui.element("div").classes(
                    "calendar-swatch" + (" calendar-swatch-on" if event.color == color else "")
                ).style(f"background: {color}").on("click", lambda c=color: self._color(c)).mark(
                    f"editor-color-{color}"
                )
            with ui.button(icon="colorize").props("flat round dense size=sm").tooltip("Autre couleur…"):
                ui.color_picker(on_pick=lambda e: self._color(e.color))

    def _color(self, color: str | None) -> None:
        if color != self.event.color:
            self._save(rebuild=True, color=color)

    # --- public, partage ---

    def _public(self, event: EventOut) -> None:
        ui.switch(
            "📢 Public — visible (en lecture seule) par tous les comptes",
            value=event.is_public,
            on_change=lambda e: (
                self._save(rebuild=True, is_public=bool(e.value)) if e.value != self.event.is_public else None
            ),
        ).props("dense").mark("editor-public")

    def _sharing(self, event: EventOut) -> None:
        people = {u.id: u.display_name for u in self.ds.users_public() if u.id != self.ctx.user.id}
        if not people:
            return
        rights = {share.user_id: share.can_edit for share in event.shares}

        def save(new_rights: dict[int, bool]) -> None:
            shares = [ShareSpec(user_id=u, can_edit=e) for u, e in new_rights.items()]
            updated = self.ctx.call(self.ds.agenda.set_shares, self.event.id, shares)
            if updated is not None:
                self.item = updated
                self._flash_saved()
                self._page_changed()
                self._build()

        def chosen(values: list) -> None:
            wanted = list(values or [])
            if set(wanted) != set(rights):
                save({u: rights.get(u, True) for u in wanted})

        with ui.column().classes("w-full gap-1"):
            ui.select(
                {u: f"👤 {name}" for u, name in people.items()},
                label="👥 Partager avec",
                value=event.shared_with,
                multiple=True,
                on_change=lambda e: chosen(e.value),
            ).props("outlined dense use-chips").classes("w-full").mark("editor-shares")
            for user_id, can_edit in rights.items():
                with ui.row().classes("w-full items-center gap-2 pl-2"):
                    ui.label(f"👤 {people.get(user_id, '?')}").classes("text-sm flex-1")
                    ui.toggle(
                        {True: "✏️ Peut modifier", False: "👁️ Lecture seule"},
                        value=can_edit,
                        on_change=lambda e, u=user_id: (
                            save({**rights, u: bool(e.value)}) if bool(e.value) != rights[u] else None
                        ),
                    ).props("dense no-caps unelevated size=sm").mark(f"editor-share-{user_id}")

    # --- lecture seule ---

    def _read_only(self, event: EventOut) -> None:
        reason = (
            "📢 Événement public"
            if event.is_public and self.ctx.user.id not in event.shared_with
            else "👥 Partagé"
        )

        def left() -> None:
            ui.label(f"👁️ Lecture seule · {reason}").classes("text-sm text-gray-500").mark("editor-read-only")

        self._header(event, left=left)
        self.title_input = ui.label(event.title).classes("text-2xl font-bold leading-tight")
        with (
            ui.column()
            .classes("w-full gap-1 p-3 rounded-lg")
            .style(f"background: {event.display_color}14; border-left: 4px solid {event.display_color}")
        ):
            ui.label(fmt.event_range(event.start_date, event.start_time, event.end_date, event.end_time))
        if event.location:
            with ui.row().classes("w-full items-center gap-1"):
                ui.label(f"📍 {event.location}").classes("flex-1")
                self._map_buttons(event.location)
        if event.project or event.tags:
            with ui.row().classes("w-full items-center gap-1.5"):
                if event.project:
                    ui.label(f"{event.project.emoji} {event.project.name}").classes("chip")
                for tag in event.tags:
                    tag_chip(tag.name, tag.color)
        self.links_box = ui.column().classes("w-full gap-1")
        self._links(editable=False)
        if event.notes:
            ui.label("📝 Notes").classes("font-semibold")
            ui.markdown(event.notes).classes("w-full")
        ui.separator()
        with ui.row().classes("w-full items-center gap-2 text-xs text-gray-500"):
            self._dates_footer(event, feminine=False)

    def _footer(self, event: EventOut) -> None:
        ui.separator()
        with ui.row().classes("w-full items-center gap-2 text-xs text-gray-500"):
            self._dates_footer(event, feminine=False)
            ui.space()
            ui.button("➕ Nouvel événement", on_click=lambda: self.editor.open_new_event()).props(
                "flat no-caps"
            )
            if event.can_delete:
                ui.button("🗑️ Supprimer", on_click=self._delete).props("flat no-caps color=negative").mark(
                    "editor-delete"
                )

    def _delete(self) -> None:
        title = self.event.title
        if self.ctx.attempt(self.ds.agenda.delete, self.event.id):
            self.item = None
            self.dialog.close()
            ui.notify(f"🗑️ « {title} » supprimé (Ctrl+Z pour annuler)", position="top")
