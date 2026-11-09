"""🏠 Accueil : les points chauds (en retard, aujourd'hui, rappels, à faire maintenant, en cours)."""

from __future__ import annotations

from datetime import timedelta

from fastapi import Request
from fastapi.responses import Response
from nicegui import ui

from organizer.core import rules
from organizer.core.enums import DueBucket, Quadrant, Status
from organizer.core.schemas import TaskFilter, TaskOut, TaskSort
from organizer.ui import format as fmt
from organizer.ui.components.task_card import task_card
from organizer.ui.context import UiContext
from organizer.ui.layout import app_frame, card_grid, empty_state, section_title


def page(make_context):
    def home_page(request: Request):
        ctx = make_context(request)
        if isinstance(ctx, Response):
            return ctx
        with app_frame(ctx, "/", "Accueil", open_task=request.query_params.get("task")):
            view = {"tile": None}  # compteur dont la liste est dépliée
            body = ui.refreshable(lambda: _body(ctx, view, body))
            body()
            ctx.on_refresh(body.refresh)
        return None

    return home_page


def _body(ctx: UiContext, view: dict, body) -> None:
    today = ctx.today()
    all_tasks = ctx.ds.tasks.list(TaskFilter(include_subtasks=True), TaskSort(key="priority"))
    open_tasks = [t for t in all_tasks if not t.status.is_closed]
    reminders = {t.id for t in ctx.ds.tasks.reminders_due()}

    with ui.column().classes("gap-0"):
        ui.label(f"Bonjour {ctx.user.display_name} 👋").classes("text-2xl sm:text-3xl font-bold")
        ui.label(
            f"{fmt.DAY_NAMES[today.weekday()]} {today.day} {fmt.MONTH_NAMES[today.month - 1]} {today.year}"
        ).classes("text-gray-500")

    monday = today - timedelta(days=today.weekday())
    done_this_week = [
        t
        for t in all_tasks
        if t.status is Status.DONE and t.completed_at and t.completed_at.astimezone().date() >= monday
    ]
    overdue = [t for t in open_tasks if rules.due_bucket(t.due_date, today) is DueBucket.OVERDUE]
    in_progress = [t for t in open_tasks if t.status is Status.IN_PROGRESS]
    tiles = {
        "open": ("📌", "Ouvertes", open_tasks, "Tâches ni finies ni annulées (sous-tâches comprises)"),
        "overdue": ("⚠️", "En retard", overdue, "Échéance dépassée"),
        "in_progress": ("🚧", "En cours", in_progress, "Tâches au statut « En cours »"),
        "done_week": ("✅", "Finies cette semaine", done_this_week, "Terminées depuis lundi"),
    }

    def toggle(key: str) -> None:
        view["tile"] = None if view["tile"] == key else key
        body.refresh()

    with ui.element("div").classes("grid grid-cols-2 sm:grid-cols-4 gap-3 w-full"):
        for key, (emoji, label, tasks, tip) in tiles.items():
            card = (
                ui.card()
                .classes("stat-tile items-center gap-0 py-3 rounded-xl cursor-pointer")
                .on("click", lambda k=key: toggle(k))
                .tooltip(f"{tip} — cliquer pour afficher la liste")
                .mark(f"tile-{key}")
            )
            if view["tile"] == key:
                card.classes("stat-tile-active")
            with card:
                ui.label(emoji).classes("text-2xl")
                ui.label(str(len(tasks))).classes("text-3xl font-bold")
                ui.label(label).classes("text-xs text-gray-500 text-center")

    if view["tile"] in tiles:
        emoji, label, tasks, tip = tiles[view["tile"]]
        with ui.card().classes("w-full rounded-xl gap-3 p-4 stat-panel").mark("tile-panel"):
            with ui.row().classes("w-full items-center gap-2"):
                ui.label(emoji).classes("text-xl")
                ui.label(label).classes("text-lg font-semibold")
                ui.badge(str(len(tasks))).props("rounded color=grey-5 text-color=black")
                ui.space()
                ui.button(icon="close", on_click=lambda: toggle(view["tile"])).props(
                    "flat round dense"
                ).tooltip("Replier la liste")
            if not tasks:
                empty_state("🌤️", "Aucune tâche ici.")
            else:
                with card_grid():
                    for task in tasks:
                        task_card(task, ctx)

    shown: set[int] = set()

    def section(emoji: str, title: str, tooltip: str, tasks: list[TaskOut], empty: str | None = None) -> None:
        tasks = [t for t in tasks if t.id not in shown]
        if not tasks and empty is None:
            return
        section_title(emoji, title, len(tasks), tooltip)
        if not tasks:
            empty_state("🌤️", empty)
            return
        with card_grid():
            for task in tasks:
                shown.add(task.id)
                task_card(task, ctx)

    section("🔥", "En retard", "Échéance dépassée, à traiter en priorité", overdue)
    section(
        "📅",
        "Aujourd'hui",
        "Échéance aujourd'hui",
        [t for t in open_tasks if t.due_date == today],
    )
    section(
        "🔔",
        "Rappels",
        "Suivis dont la date de rappel est atteinte",
        [t for t in open_tasks if t.id in reminders],
    )
    section(
        "🎯",
        "À faire maintenant",
        "Quadrant « Faire » de la matrice : important et urgent",
        [t for t in open_tasks if rules.quadrant_of(t.importance, t.urgency) is Quadrant.DO],
    )
    section("🚧", "En cours", "Tâches commencées", [t for t in in_progress if t.parent_id is None])
    if not shown:
        empty_state("🎉", "Rien d'urgent ! Ajoutez une tâche avec le bouton ➕ (ou la touche N).")
