"""Glisser-déposer (voir ``dnd.js``) : un composant par page, qui écoute toute la page.

Les pages déclarent leurs zones de dépôt avec :func:`drop_zone` et enregistrent un gestionnaire
(``ctx.drop_handler``) qui reçoit ``(task_id, zone, index)``. Le rattachement en sous-tâche (Ctrl + dépôt sur
une carte, ou maintien au doigt) est géré partout de la même façon par :meth:`UiContext.attach`.
"""

from __future__ import annotations

from collections.abc import Callable

from nicegui import ui


class DragDrop(ui.element, component="dnd.js"):
    def __init__(self, on_drop: Callable[[dict], None], on_attach: Callable[[dict], None]) -> None:
        super().__init__()
        self.on("drop", lambda e: on_drop(e.args))
        self.on("attach", lambda e: on_attach(e.args))


def drop_zone(
    element: ui.element, key: str, *, accept: bool = True, denied: str = "", ordered: bool = False
) -> ui.element:
    """Fait de ``element`` une zone de dépôt identifiée par ``key``.

    ``accept=False`` : on ne peut pas y déposer une carte venue d'ailleurs (mais on peut y reclasser les
    siennes). ``ordered`` : l'ordre des cartes compte ; un repère montre où la carte va s'insérer.
    """
    element._props["data-dnd-zone"] = key
    if ordered:
        element._props["data-dnd-ordered"] = "1"
    if not accept:
        element._props["data-dnd-accept"] = "0"
        element._props["data-dnd-denied"] = denied or "🚫 Dépôt impossible ici"
    return element


def draggable(element: ui.element, task) -> ui.element:
    """Rend une carte (ou une ligne) de tâche saisissable."""
    element._props["data-dnd-task"] = str(task.id)
    element._props["data-dnd-title"] = task.title
    if task.parent_id is not None:
        element._props["data-dnd-parent"] = str(task.parent_id)
    if task.has_subtasks:
        element._props["data-dnd-has-subtasks"] = "1"
    return element
