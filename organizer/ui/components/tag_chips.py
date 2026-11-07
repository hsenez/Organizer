"""Affichage des tags dans leur couleur, partout de la même façon : pastille de la couleur du tag sur un fond
légèrement teinté (cartes, éditeur, barre de filtres)."""

from __future__ import annotations

import html
import json

from nicegui import ui

DEFAULT_COLOR = "#868e96"
TINT_ALPHA = "2e"  # ≈ 18 % d'opacité, ajouté au code hexadécimal de la couleur


def tint(color: str) -> str:
    """Fond teinté d'une couleur ``#rrggbb``."""
    return f"{color}{TINT_ALPHA}" if len(color) == 7 else color


def tag_chip(name: str, color: str) -> ui.element:
    """Pastille de tag (cartes de tâches)."""
    with ui.element("span").classes("chip").style(f"background: {tint(color)}") as chip:
        ui.element("span").classes("tag-dot").style(f"background: {color}")
        ui.label(name)
    return chip


def color_tag_select(select: ui.select, colors: dict[str, str]) -> ui.select:
    """Affiche les tags d'un ``ui.select`` (choix multiple) dans leur couleur : puces sélectionnées et liste
    déroulante. ``colors`` : nom du tag → couleur (les options NiceGUI ont pour libellé le nom du tag ; un nom
    tapé pour créer un nouveau tag, encore inconnu, s'affiche en gris)."""
    select.classes("tag-select")  # espace entre le libellé du champ et les puces (voir theme.py)
    mapping = html.escape(json.dumps(colors, ensure_ascii=False), quote=True)
    color = f"(({mapping})[props.opt.label] || '{DEFAULT_COLOR}')"
    select.add_slot(
        "selected-item",
        f"""
        <q-chip dense removable :tabindex="props.tabindex" @remove="props.removeAtIndex(props.index)"
                class="q-ml-none q-mr-xs" style="margin-top: 2px; margin-bottom: 2px"
                :style="{{ background: {color} + '{TINT_ALPHA}' }}">
          <span class="tag-dot q-mr-xs" :style="{{ background: {color} }}"></span>{{{{ props.opt.label }}}}
        </q-chip>
        """,
    )
    select.add_slot(
        "option",
        f"""
        <q-item v-bind="props.itemProps">
          <q-item-section side style="padding-right: 8px">
            <span class="tag-dot" :style="{{ background: {color}, width: '12px', height: '12px' }}"></span>
          </q-item-section>
          <q-item-section><q-item-label>{{{{ props.opt.label }}}}</q-item-label></q-item-section>
        </q-item>
        """,
    )
    return select
