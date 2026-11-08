"""Écran d'accueil des pages de connexion (serveur : /login, /setup ; client bureau : /connect)."""

from __future__ import annotations

from nicegui import ui

PRIMARY = "#5c7cfa"


def auth_shell(subtitle: str) -> ui.column:
    """Fond dégradé + carte centrée ; renvoie la colonne où placer le formulaire."""
    ui.colors(primary=PRIMARY)
    ui.query("body").classes(
        "bg-gradient-to-br from-indigo-100 via-white to-sky-100 "
        "dark:from-slate-900 dark:via-slate-800 dark:to-indigo-950"
    )
    with ui.column().classes("w-full min-h-screen items-center justify-center p-4"):
        card = ui.card().classes("w-full max-w-sm p-6 gap-4 rounded-2xl shadow-xl")
        with card:
            with ui.column().classes("w-full items-center gap-1"):
                ui.label("📋").classes("text-5xl")
                ui.label("Organizer").classes("text-2xl font-bold")
                ui.label(subtitle).classes("text-sm text-gray-500 text-center")
            body = ui.column().classes("w-full gap-3")
    return body
