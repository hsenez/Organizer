"""Partage avec droit par personne (« ✏️ Peut modifier » / « 👁️ Lecture seule ») et interrupteur « Public » :
éditeur d'événement et page Notes."""

from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from organizer.core.schemas import ShareSpec
from organizer.ui.context import UiContext


def public_switch(label: str, value: bool, on_change: Callable[[bool], None]) -> ui.switch:
    return ui.switch(
        label, value=value, on_change=lambda e: on_change(bool(e.value)) if bool(e.value) != value else None
    ).props("dense")


def share_editor(ctx: UiContext, shares: list[ShareSpec], on_save: Callable[[list[ShareSpec]], None]) -> None:
    """Liste « 👥 Partager avec » + droit de chaque personne. ``on_save(partages)`` à chaque changement.
    Marqueurs : ``editor-shares`` (liste), ``editor-share-<id>`` (droit)."""
    people = {u.id: u.display_name for u in ctx.ds.users_public() if u.id != ctx.user.id}
    if not people:
        return
    rights = {share.user_id: share.can_edit for share in shares}

    def save(new_rights: dict[int, bool]) -> None:
        on_save([ShareSpec(user_id=u, can_edit=e) for u, e in new_rights.items()])

    def chosen(values: list) -> None:
        wanted = list(values or [])
        if set(wanted) != set(rights):
            save({u: rights.get(u, True) for u in wanted})

    with ui.column().classes("w-full gap-1"):
        ui.select(
            {u: f"👤 {name}" for u, name in people.items()},
            label="👥 Partager avec",
            value=list(rights),
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
