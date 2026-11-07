"""Carte de tâche : tout l'état d'une tâche d'un coup d'œil (voir specifications.md §7).

- liseré gauche : importance (couleur + épaisseur) ;
- emoji en haut à droite : urgence (🔥 pulse) ;
- fond teinté : statut ; fini = estompé et barré ; annulé = pointillés ;
- pastilles : échéance (rouge / orange / jaune), type et rappel, projet, tags, progression, indicateurs.
Chaque élément porte une infobulle.
"""

from __future__ import annotations

from nicegui import ui

from organizer.core import rules
from organizer.core.enums import DueBucket, LinkKind, Status, Urgency
from organizer.core.schemas import TaskOut, TaskPatch
from organizer.ui import format as fmt
from organizer.ui.components.tag_chips import tag_chip
from organizer.ui.context import UiContext
from organizer.ui.theme import IMPORTANCE_BORDER_PX


def task_card(task: TaskOut, ctx: UiContext, *, show_parent: bool = True) -> ui.card:
    importance, urgency, status = task.importance, task.urgency, task.status
    card = (
        ui.card()
        .classes(f"task-card st-{status.value} w-full p-3 gap-2")
        .style(f"--imp-w: {IMPORTANCE_BORDER_PX[int(importance)]}px; --imp-c: {importance.meta.color};")
        .mark(f"task-card-{task.id}")
        .on("click", lambda: ctx.editor.open(task.id))
    )
    with card:
        # Ligne 1 : importance, titre, urgence, menu
        with ui.row().classes("w-full items-start gap-2 no-wrap"):
            ui.label(importance.meta.emoji).classes("text-base leading-6").tooltip(
                f"Importance : {importance.meta.label} — {importance.meta.tooltip}"
            )
            ui.label(task.title).classes("task-title flex-1 text-[15px]")
            urgency_label = (
                ui.label(urgency.meta.emoji)
                .classes("text-base leading-6")
                .tooltip(f"Urgence : {urgency.meta.label} — {urgency.meta.tooltip}")
            )
            if urgency is Urgency.IMMEDIATE and not status.is_closed:
                urgency_label.classes("pulse")
            _card_menu(task, ctx)

        # Ligne 2 : pastilles
        with ui.row().classes("w-full items-center gap-1.5"):
            if show_parent and task.parent_id is not None:
                ui.label(f"↳ {task.parent_title}").classes("chip cursor-pointer").tooltip(
                    "Sous-tâche de cette tâche — cliquer pour l'ouvrir"
                ).on("click.stop", lambda: ctx.editor.open(task.parent_id))
            ui.label(status.meta.emoji).classes("chip").tooltip(
                f"{status.meta.label} — {status.meta.tooltip}"
            )
            _due_chip(task, ctx)
            kind_text = task.kind.meta.emoji
            kind_tip = f"{task.kind.meta.label} — {task.kind.meta.tooltip}"
            if task.reminder_date is not None:
                kind_text += f" 🔔 {fmt.short_date(task.reminder_date, ctx.today())}"
                kind_tip += f"\nRappel : {fmt.long_date(task.reminder_date)}"
            ui.label(kind_text).classes("chip").tooltip(kind_tip)
            if task.project is not None:
                ui.label(f"{task.project.emoji} {task.project.name}").classes("chip").style(
                    f"background: {task.project.color}22; color: {task.project.color};"
                ).tooltip(f"Projet : {task.project.name}")
            for tag in task.tags:
                tag_chip(tag.name, tag.color).tooltip(f"Tag : {tag.name}")
            if task.subtask_total:
                percent = round(100 * task.subtask_done / task.subtask_total)
                with (
                    ui.element("span")
                    .classes("chip")
                    .tooltip(f"Sous-tâches : {task.subtask_done} finie(s) sur {task.subtask_total}")
                ):
                    with ui.element("span").classes("progress-track"):
                        ui.element("span").classes("progress-fill").style(f"width: {percent}%")
                    ui.label(f"{task.subtask_done}/{task.subtask_total}")
            if task.due_after_parent:
                ui.label("⚠️").classes("chip").tooltip("L'échéance dépasse celle de la tâche parente")
            if task.notes.strip():
                ui.label("📝").classes("chip").tooltip("A des notes")
            if task.links:
                kinds = {link.kind for link in task.links}
                emoji = "📎" if kinds == {LinkKind.ATTACHMENT} else "🔗"
                ui.label(f"{emoji} {len(task.links)}").classes("chip").tooltip(f"{len(task.links)} lien(s)")
            if task.shared_with or task.owner_id != ctx.user.id:
                ui.label("👥").classes("chip").tooltip(
                    "Partagée avec moi"
                    if task.owner_id != ctx.user.id
                    else "Partagée avec d'autres personnes"
                )
    return card


def _due_chip(task: TaskOut, ctx: UiContext) -> None:
    if task.due_date is None:
        return
    today = ctx.today()
    bucket = rules.due_bucket(task.due_date, today)
    css = "chip"
    if not task.status.is_closed:
        if bucket is DueBucket.OVERDUE:
            css += " chip-overdue"
        elif bucket is DueBucket.TODAY:
            css += " chip-today"
        elif (task.due_date - today).days <= 3:
            css += " chip-soon"
    emoji = "⚠️" if bucket is DueBucket.OVERDUE and not task.status.is_closed else "📅"
    ui.label(f"{emoji} {fmt.due_text(task.due_date, task.due_time, today)}").classes(css).tooltip(
        f"Échéance : {fmt.long_date(task.due_date)} ({fmt.relative(task.due_date, today)})"
    )


def _card_menu(task: TaskOut, ctx: UiContext) -> None:
    def set_status(status: Status) -> None:
        if ctx.call(ctx.ds.tasks.update, task.id, TaskPatch(status=status)) is not None:
            ctx.refresh()

    def detach() -> None:
        if ctx.call(ctx.ds.tasks.detach, task.id) is not None:
            ui.notify(f"🌳 « {task.title} » est redevenue une tâche indépendante", position="top")
            ctx.refresh()

    with (
        ui.button(icon="more_vert")
        .props("flat round dense size=sm")
        .classes("-mt-1 -mr-1 opacity-60")
        .on("click.stop", lambda: None)
        .tooltip("Actions rapides")
    ):
        with ui.menu().props("auto-close").mark(f"card-menu-{task.id}"):
            for status in Status:
                ui.menu_item(
                    f"{status.meta.text}{'  ✓' if status is task.status else ''}",
                    on_click=lambda s=status: set_status(s),
                ).mark(f"card-status-{task.id}-{status.value}")
            ui.separator()
            ui.menu_item("📋 Dupliquer", on_click=lambda: duplicate(task, ctx)).mark(
                f"card-duplicate-{task.id}"
            )
            if task.parent_id is not None:
                ui.menu_item("🌳 Détacher du parent", on_click=detach)
            if task.can_delete:
                ui.menu_item("🗑️ Supprimer", on_click=lambda: confirm_delete(task, ctx))


def duplicate(task: TaskOut, ctx: UiContext) -> None:
    """Duplique la tâche (et ses sous-tâches) puis ouvre la copie dans l'éditeur."""
    copy = ctx.call(ctx.ds.tasks.duplicate, task.id)
    if copy is not None:
        ui.notify(f"📋 « {task.title} » dupliquée — Ctrl+Z pour annuler", position="top")
        ctx.refresh()
        ctx.editor.open(copy.id)


def confirm_delete(task: TaskOut, ctx: UiContext, after=None) -> None:
    """Supprime sans confirmation (Ctrl+Z annule), sauf s'il y a des sous-tâches : on demande quoi en
    faire."""

    def do_delete(with_subtasks: bool) -> None:
        if ctx.attempt(ctx.ds.tasks.delete, task.id, with_subtasks=with_subtasks):
            ui.notify(f"🗑️ « {task.title} » supprimée — Ctrl+Z pour annuler", position="top")
            ctx.refresh()
            if after:
                after()

    if not task.has_subtasks:
        do_delete(False)
        return
    with ui.dialog() as dialog, ui.card().classes("gap-3"):
        ui.label(f"🗑️ Supprimer « {task.title} » ?").classes("text-lg font-semibold")
        ui.label(f"Cette tâche a {task.subtask_count} sous-tâche(s). Que faut-il en faire ?")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Annuler", on_click=dialog.close).props("flat")
            ui.button(
                "Garder les sous-tâches",
                on_click=lambda: (dialog.close(), do_delete(False)),
            ).props("outline")
            ui.button(
                "Tout supprimer",
                color="negative",
                on_click=lambda: (dialog.close(), do_delete(True)),
            )
    dialog.open()


def task_row(task: TaskOut, ctx: UiContext, on_click) -> ui.row:
    """Version compacte sur une ligne (résultats de recherche) : statut, importance, titre, projet,
    échéance."""
    row = (
        ui.row()
        .classes("task-row w-full items-center gap-2 no-wrap px-2 py-1.5 rounded-lg cursor-pointer")
        .on("click", on_click)
        .mark(f"task-row-{task.id}")
    )
    with row:
        ui.label(task.status.meta.emoji).tooltip(task.status.meta.label)
        ui.label(task.importance.meta.emoji).tooltip(f"Importance : {task.importance.meta.label}")
        with ui.column().classes("flex-1 min-w-0 gap-0"):
            title = ui.label(task.title).classes("truncate w-full font-medium")
            if task.status.is_closed:
                title.classes("line-through text-gray-500")
            if task.parent_title:
                ui.label(f"↳ {task.parent_title}").classes("text-xs text-gray-500 truncate w-full")
        if task.project is not None:
            ui.label(f"{task.project.emoji} {task.project.name}").classes("chip hidden sm:inline-flex")
        _due_chip(task, ctx)
    return row
