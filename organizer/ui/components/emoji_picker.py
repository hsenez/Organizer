"""Emojis proposés (notes, projets) : liste **personnelle**, modifiable dans Réglages → Apparence
(préférence ``EMOJIS_PREF``), ``enums.DEFAULT_EMOJIS`` par défaut."""

from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from organizer.core import rules
from organizer.core.enums import DEFAULT_EMOJIS, EMOJIS_PREF
from organizer.ui.context import UiContext


def emoji_choices(ctx: UiContext) -> list[str]:
    """La liste de l'utilisateur (lue avec tolérance : une valeur abîmée donne la liste par défaut)."""
    try:
        saved = ctx.ds.account.get_pref(EMOJIS_PREF)
        choices = rules.parse_emojis(saved) if isinstance(saved, (list, str)) else []
    except Exception:
        choices = []
    return choices or list(DEFAULT_EMOJIS)


def emoji_grid(choices: list[str], on_pick: Callable[[str], None]) -> None:
    with ui.row().classes("gap-0 flex-wrap"):
        for emoji in choices:
            ui.button(emoji, on_click=lambda e=emoji: on_pick(e)).props("flat dense").classes(
                "text-lg min-w-0 px-1"
            ).mark(f"emoji-{emoji}")


def emoji_button(ctx: UiContext, value: str, on_change: Callable[[str], None]) -> ui.button:
    """Bouton qui affiche l'emoji ; son menu propose la liste de l'utilisateur, ou un emoji tapé."""
    button = ui.button(value).props("flat dense").classes("text-3xl min-w-0 px-1")
    with button, ui.menu().classes("p-2 max-w-[320px]").mark("emoji-menu") as menu:

        def pick(emoji: str) -> None:
            menu.close()
            emoji = emoji.strip()
            if emoji and emoji != value:
                button.set_text(emoji)
                on_change(emoji)

        emoji_grid(emoji_choices(ctx), pick)
        other = ui.input("Autre emoji").props("outlined dense").classes("w-full mt-1")
        other.on("keydown.enter", lambda: pick(other.value or ""))
        ui.label("Liste modifiable dans ⚙️ Réglages → Apparence").classes("text-xs text-gray-500")
    return button
