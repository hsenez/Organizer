"""Téléphones : clavier virtuel et zone visible de la page.

- ``VIEWPORT`` : balise ``<meta name="viewport">`` de toutes les pages. ``interactive-widget=resizes-content``
  demande à Chrome (Android) de **rapetisser la page** quand le clavier sort, au lieu de la faire glisser sous
  la partie visible (comportement par défaut : l'en-tête et les panneaux partaient hors de l'écran). Safari
  (iOS) ignore ce réglage : le script ``viewport.js`` s'en charge.
- ``install_viewport_script`` : ``viewport.js`` (une fois par page, par ``app_frame``) — variables CSS
  ``--vv-top`` / ``--vv-height``, classe ``keyboard-open`` sur ``<body>``, mode écriture des éléments
  ``[data-writing]`` (voir le fichier JS et le CSS de ``theme.py``).
"""

from __future__ import annotations

from pathlib import Path

from nicegui import ui

VIEWPORT = "width=device-width, initial-scale=1, interactive-widget=resizes-content"

_JS = (Path(__file__).with_name("viewport.js")).read_text(encoding="utf-8")


def install_viewport_script() -> None:
    ui.add_body_html(f"<script>{_JS}</script>")


def writing_zone(element: ui.element) -> ui.element:
    """Sur téléphone, clavier sorti avec le focus dans ``element`` : l'élément occupe tout l'écran visible
    (mode écriture). Son enfant ``.md-toolbar`` se place en bas, collé au clavier."""
    return element.props("data-writing").classes("writing-zone")
