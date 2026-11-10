"""À qui est une tâche / un événement : pictogramme (``Ownership`` dans ``enums.py``) et infobulle avec les
noms. Rien pour un élément à moi partagé avec personne."""

from __future__ import annotations

from typing import Any

from nicegui import ui

from organizer.core import rules
from organizer.core.enums import Ownership
from organizer.ui.context import UiContext


def ownership_of(item: Any, ctx: UiContext) -> Ownership:
    return rules.ownership(item.owner_id, ctx.user.id, item.shared_with, getattr(item, "can_edit", True))


def ownership_text(item: Any, ctx: UiContext) -> str:
    """« À vous, partagé avec Bob », « À Bob, partagé avec vous : modifiable »…"""
    names = ctx.user_names()
    owner = names.get(item.owner_id, "?")
    kind = ownership_of(item, ctx)
    if kind is Ownership.MINE:
        return "À vous"
    if kind is Ownership.SHARED_BY_ME:
        others = ", ".join(names.get(u, "?") for u in item.shared_with)
        return f"À vous, partagé avec {others}"
    if kind is Ownership.SHARED_WITH_ME:
        return f"À {owner}, partagé avec vous : modifiable"
    if getattr(item, "is_public", False) and ctx.user.id not in item.shared_with:
        return f"Public, de {owner} : lecture seule"
    return f"À {owner}, partagé avec vous en lecture seule"


def ownership_emoji(item: Any, ctx: UiContext) -> str:
    """Pictogramme à placer devant un titre (``""`` pour un élément à moi, partagé avec personne)."""
    return ownership_of(item, ctx).meta.emoji


def ownership_chip(item: Any, ctx: UiContext) -> ui.label | None:
    """Pastille des cartes et des lignes (rien pour un élément à moi, partagé avec personne)."""
    kind = ownership_of(item, ctx)
    if kind is Ownership.MINE:
        return None
    return (
        ui.label(kind.meta.emoji)
        .classes("chip")
        .style(f"background: {kind.meta.color}22")
        .tooltip(ownership_text(item, ctx))
        .mark(f"ownership-{kind.value}")
    )
