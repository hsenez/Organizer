"""Redimensionnement horizontal (voir ``resize.js``) : colonnes de kanban.

L'élément redimensionnable porte ``data-resize-key`` (:func:`resizable`), sa poignée ``data-resize-handle``
(:func:`resize_handle`). Le composant :class:`Resizer` (un par page) écoute toute la page et appelle
``on_resize(key, width)`` à la fin du geste (``width`` = None : largeur par défaut, après un double-clic).
"""

from __future__ import annotations

from collections.abc import Callable

from nicegui import ui


class Resizer(ui.element, component="resize.js"):
    def __init__(
        self, on_resize: Callable[[str, int | None], None], *, min: int = 180, max: int = 720
    ) -> None:
        super().__init__()
        self._props["min"] = min
        self._props["max"] = max
        self.on("resize", lambda e: on_resize(str(e.args["key"]), e.args.get("width")))


def resizable(element: ui.element, key: str) -> ui.element:
    element._props["data-resize-key"] = key
    return element


def resize_handle(tooltip: str = "Glisser pour élargir · double-clic : largeur par défaut") -> ui.element:
    handle = ui.element("div").classes("resize-handle")
    handle._props["data-resize-handle"] = ""
    handle._props["data-dnd-ignore"] = ""
    handle._props["title"] = tooltip
    return handle
