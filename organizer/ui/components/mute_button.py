"""🔕 « Ne plus me notifier » pour une tâche, un événement ou une note (personnel, annulable par Ctrl+Z).

Affiché seulement quand d'autres peuvent agir sur l'élément (il est partagé, ou il appartient à un autre) :
sinon il n'y a jamais de notification à couper.
"""

from __future__ import annotations

from collections.abc import Iterable

from nicegui import ui

from organizer.core.errors import OrganizerError
from organizer.ui.context import UiContext

TOOLTIPS = {
    False: "Ne plus me notifier pour cet élément (🔕 ; réglages généraux : Réglages → 🔔 Notifications)",
    True: "Notifications coupées pour cet élément : cliquer pour les rétablir",
}


def concerns_others(ctx: UiContext, owner_id: int, shared_with: Iterable[int]) -> bool:
    """D'autres peuvent-ils agir sur l'élément (donc me notifier) ?"""
    return owner_id != ctx.user.id or bool(list(shared_with))


def mute_button(ctx: UiContext, item_type: str, item_id: int, *, mark: str = "mute") -> ui.button | None:
    """Bouton cloche ; None si l'état n'a pas pu être lu (élément disparu, serveur injoignable…)."""
    try:
        state = {"muted": ctx.ds.notifications.muted(item_type, item_id)}
    except OrganizerError:
        return None
    button = ui.button().props("flat round dense").mark(mark)
    with button:
        tooltip = ui.tooltip("")

    def render() -> None:
        muted = state["muted"]
        button.props(f"icon={'notifications_off' if muted else 'notifications_none'}")
        button.props(f"color={'deep-orange' if muted else 'grey-6'}")
        tooltip.set_text(TOOLTIPS[muted])

    def toggle() -> None:
        wanted = not state["muted"]
        result = ctx.call(ctx.ds.notifications.set_muted, item_type, item_id, wanted)
        if result is None:
            return
        state["muted"] = result
        render()
        ctx.refresh(light=True)  # boutons annuler / rétablir
        ui.notify(
            "🔕 Plus de notification pour cet élément" if result else "🔔 Notifications rétablies",
            position="top",
            timeout=1800,
        )

    button.on("click", toggle)
    render()
    return button
