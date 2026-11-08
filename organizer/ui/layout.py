"""Cadre commun des pages : en-tête, colonne de gauche (modules), raccourcis clavier, bouton ➕.

Sur téléphone, la colonne de gauche devient un tiroir ouvert par ☰.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from nicegui import events, ui

from organizer.ui.components.dnd import DragDrop
from organizer.ui.components.search_dialog import SearchDialog
from organizer.ui.components.task_editor import TaskEditor
from organizer.ui.context import UiContext
from organizer.ui.theme import apply_theme

# Thème choisi dans les réglages → valeur de ui.dark_mode (None = suivre le système).
THEMES = {"auto": None, "light": False, "dark": True}


@dataclass(frozen=True)
class Module:
    path: str
    emoji: str
    label: str
    tooltip: str


MODULES = [
    Module("/", "🏠", "Accueil", "Les points chauds : en retard, aujourd'hui, rappels, en cours"),
    Module("/tasks", "📋", "Toutes les tâches", "La liste complète, triée par priorité"),
    Module("/kanban", "📊", "Kanbans", "Boards par statut, échéance, type, projet… et les vôtres"),
    Module("/matrix", "🎯", "Matrice", "Matrice d'Eisenhower : important × urgent"),
    Module("/search", "🔍", "Recherche", "Rechercher dans les titres, notes, tags et projets (Ctrl+K)"),
]
SETTINGS = Module("/settings", "⚙️", "Réglages", "Profil, projets, tags, appareils, utilisateurs")


@contextmanager
def app_frame(
    ctx: UiContext, active: str, title: str, open_task: str | None = None, *, wide: bool = False
) -> Iterator[ui.column]:
    """Construit le cadre ; le contenu de la page se place dans la colonne renvoyée.

    ``open_task`` : paramètre d'URL ``?task=`` — identifiant d'une tâche dont l'éditeur s'ouvre au chargement,
    ou ``new`` pour ouvrir l'éditeur sur une nouvelle tâche.
    ``wide`` : contenu sur toute la largeur et toute la hauteur de la fenêtre (kanbans) ; le dernier enfant
    de la colonne renvoyée peut s'étirer jusqu'en bas avec la classe ``page-fill-grow``.
    """
    apply_theme()
    ctx.dark = ui.dark_mode(THEMES.get(ctx.user.theme))
    ui.page_title(f"{title} · Organizer")
    ctx.editor = TaskEditor(ctx)
    search = SearchDialog(ctx)
    DragDrop(on_drop=ctx.handle_drop, on_attach=ctx.attach, on_state=ctx.set_dragging).mark("dnd")
    # Ctrl+K est réservé par certains navigateurs (barre de recherche de Firefox) : on le garde pour nous.
    ui.add_body_html(
        "<script>document.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && "
        "e.key.toLowerCase() === 'k') e.preventDefault(); });</script>"
    )

    with ui.header().classes(
        "items-center gap-1 px-2 py-1 bg-white/90 dark:bg-slate-900/90 backdrop-blur "
        "text-gray-800 dark:text-gray-100 border-b border-gray-200 dark:border-gray-800"
    ):
        menu_button = ui.button(icon="menu").props("flat round").tooltip("Afficher / masquer les modules")
        ui.label("📋 Organizer").classes("text-lg font-bold mr-2")
        ui.space()
        ui.button(icon="search", on_click=search.open).props("flat round").tooltip(
            "Rechercher (Ctrl+K)"
        ).mark("search-button")
        with ui.button(icon="undo", on_click=ctx.undo).props("flat round").mark("undo-button") as undo_btn:
            undo_tip = ui.tooltip()
        with ui.button(icon="redo", on_click=ctx.redo).props("flat round").mark("redo-button") as redo_btn:
            redo_tip = ui.tooltip()
        with ui.button(icon="account_circle").props("flat round").tooltip(ctx.user.display_name):
            with ui.menu().mark("account-menu"):
                ui.menu_item(f"{'👑 ' if ctx.user.is_admin else '👤 '}{ctx.user.display_name}").props(
                    "disable"
                )
                ui.separator()
                ui.menu_item("⚙️ Réglages", on_click=lambda: ui.navigate.to(SETTINGS.path))
                ui.menu_item("🚪 Déconnexion", on_click=ctx.logout).mark("logout-item")
                if (
                    ctx.quit is not None
                ):  # client bureau : il tourne en arrière-plan quand on ferme la fenêtre
                    ui.menu_item("⏻ Quitter Organizer", on_click=ctx.quit).mark("quit-item")

    def update_undo_buttons() -> None:
        status = ctx.ds.undo.status()
        undo_btn.set_enabled(status.undo_label is not None)
        redo_btn.set_enabled(status.redo_label is not None)
        undo_tip.set_text(
            f"Annuler (Ctrl+Z) : {status.undo_label}" if status.undo_label else "Rien à annuler"
        )
        redo_tip.set_text(
            f"Rétablir (Ctrl+Maj+Z) : {status.redo_label}" if status.redo_label else "Rien à rétablir"
        )

    with ui.left_drawer().props("width=232 bordered").classes("app-drawer p-0 pt-2 gap-0") as drawer:
        for module in [*MODULES, None, SETTINGS]:
            if module is None:
                ui.separator().classes("my-2")
                continue
            item = (
                ui.item(on_click=lambda m=module: ui.navigate.to(m.path))
                .props("dense")
                .classes("nav-item min-h-0 py-2")
                .tooltip(module.tooltip)
            )
            if module.path == active:
                item.classes("nav-active")
            with item:
                with ui.item_section().props("avatar").classes("min-w-0 pr-2"):
                    ui.label(module.emoji).classes("text-xl")
                with ui.item_section():
                    ui.label(module.label)
    menu_button.on_click(drawer.toggle)

    with ui.page_sticky(position="bottom-right", x_offset=20, y_offset=20):
        ui.button(icon="add", on_click=ctx.editor.open_new).props("fab color=primary").tooltip(
            "Nouvelle tâche (N)"
        ).mark("fab-add")

    def on_key(e: events.KeyEventArguments) -> None:
        if not e.action.keydown:
            return
        key = str(e.key.name).lower()
        if e.modifiers.ctrl or e.modifiers.meta:
            if (key == "z" and e.modifiers.shift) or key == "y":
                ctx.redo()
            elif key == "z":
                ctx.undo()
            elif key == "k":
                search.open()
        elif key == "n" and not e.modifiers.alt and not ctx.editor.dialog.value:
            ctx.editor.open_new()

    # ``ignore`` : dans un champ texte, Ctrl+Z reste l'annulation de frappe du navigateur.
    ui.keyboard(on_key=on_key, ignore=["input", "select", "button", "textarea"])

    ctx.on_refresh(update_undo_buttons)
    update_undo_buttons()
    if open_task == "new":
        ctx.editor.open_new()
    elif open_task and open_task.isdigit():
        ctx.editor.open(int(open_task))
    if wide:
        ui.query(".nicegui-content").classes("page-fill")
        classes = "page-fill-column w-full p-3 sm:px-5 sm:py-4 gap-4"
    else:
        classes = "w-full max-w-6xl mx-auto p-3 sm:p-6 gap-5 pb-24"
    with ui.column().classes(classes) as content:
        if ctx.banner is not None:
            text, blocking = ctx.banner
            with (
                ui.row()
                .classes("w-full items-center gap-3 rounded-xl px-4 py-2 no-wrap")
                .style(f"background: {'rgba(250, 82, 82, .12)' if blocking else 'rgba(92, 124, 250, .12)'}")
                .mark("version-banner")
            ):
                ui.label(text).classes("text-sm flex-1")
                ui.button("Détails", on_click=lambda: ui.navigate.to("/settings?tab=connection")).props(
                    "flat dense no-caps"
                )
        yield content


def card_grid() -> ui.element:
    """Grille responsive de cartes : 1 colonne sur téléphone, jusqu'à 3 sur grand écran."""
    return ui.element("div").classes("grid gap-3 w-full grid-cols-1 md:grid-cols-2 xl:grid-cols-3")


def section_title(emoji: str, text: str, count: int | None = None, tooltip: str | None = None) -> None:
    with ui.row().classes("items-center gap-2 mt-2") as row:
        ui.label(emoji).classes("text-xl")
        ui.label(text).classes("text-lg font-semibold")
        if count is not None:
            ui.badge(str(count)).props("rounded color=grey-5 text-color=black")
    if tooltip:
        row.tooltip(tooltip)


def empty_state(emoji: str, text: str) -> None:
    with ui.column().classes("w-full items-center py-6 text-gray-500 gap-1"):
        ui.label(emoji).classes("text-4xl")
        ui.label(text).classes("text-sm")
