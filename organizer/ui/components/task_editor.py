"""Éditeur de tâche (voir :mod:`organizer.ui.components.item_editor` pour le panneau et la partie commune) :
curseurs importance / urgence / statut / type, échéance, rappel, partage, sous-tâches."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from nicegui import ui

from organizer.core import rules
from organizer.core.enums import Importance, Status, TaskKind, Urgency
from organizer.core.models import utcnow
from organizer.core.schemas import TaskCreate, TaskOut, TaskPatch
from organizer.ui import format as fmt
from organizer.ui.components.item_editor import ItemEditor, parse_date, parse_time
from organizer.ui.components.level_slider import LevelSlider
from organizer.ui.components.task_card import confirm_delete, duplicate

# Champs propres aux tâches, réappliqués si la tâche redevient une tâche dans la même session.
TASK_SPECIFIC = ("importance", "urgency", "status", "kind", "reminder_offset_days")


class TaskEditor(ItemEditor):
    kind = "task"
    noun = "la tâche"
    created_text = "✔ Tâche créée"
    new_label = "✨ Nouvelle tâche"
    creation_hint = "La tâche sera créée dès que vous lui aurez donné un titre."
    title_placeholder = "Que faut-il faire ?"

    @property
    def task(self) -> TaskOut | None:
        return self.item

    @task.setter
    def task(self, value: TaskOut | None) -> None:
        self.item = value

    @property
    def service(self):
        return self.ds.tasks

    def _create(self, title: str, fields: dict) -> TaskOut:
        return self.ds.tasks.create(TaskCreate(title=title, **fields))

    def _update(self, item_id: int, fields: dict) -> TaskOut:
        return self.ds.tasks.update(item_id, TaskPatch(**fields))

    def _upload_fn(self):
        return self.ds.attachments.upload

    def open_new(self, draft: dict | None = None) -> None:
        """Ouvre l'éditeur complet sur une nouvelle tâche (brouillon)."""
        # Profil à jour : le décalage de rappel par défaut a pu changer dans un autre onglet.
        fresh = self.ctx.call(self.ds.account.me)
        if fresh is not None:
            self.ds.user = fresh
        super().open_new(draft)

    # --- bascule ---

    def can_switch(self) -> tuple[bool, str]:
        allowed, reason = super().can_switch()
        if not allowed or self.is_draft:
            return allowed, reason
        if self.task.parent_id is not None:
            return False, "Une sous-tâche ne peut pas devenir un événement"
        if self.task.has_subtasks:
            return False, "Une tâche qui a des sous-tâches ne peut pas devenir un événement"
        return True, ""

    def specific_from(self, other: ItemEditor) -> dict:
        """Depuis un brouillon d'événement : échéance = début."""
        draft = other.draft or {}
        if draft.get("start_date") is None:
            return {}
        return {"due_date": draft["start_date"], "due_time": draft.get("start_time")}

    def specific_of_item(self) -> dict:
        return {key: getattr(self.task, key) for key in TASK_SPECIFIC}

    def convert_from(self, other: ItemEditor) -> Any:
        """Événement → tâche, en reprenant (même action) les champs gardés d'une conversion précédente."""
        extra = TaskPatch(**self.stash) if self.stash else None
        return self.ctx.call(self.ds.agenda.to_task, other.item.id, extra)

    def _merge_draft(self, fields: dict) -> None:
        if fields.get("reminder_date") is not None:
            self.draft.pop("reminder_offset_days", None)
        if "reminder_offset_days" in fields:
            self.draft.pop("reminder_date", None)
        self.draft.update(fields)

    def _draft_out(self) -> TaskOut:
        """Représentation affichable du brouillon (mêmes champs qu'une vraie tâche)."""
        d = self.draft or {}
        kind = d.get("kind", TaskKind.TODO)
        offset = d.get("reminder_offset_days")
        manual = d.get("reminder_date")
        if kind is TaskKind.FOLLOWUP and offset is None and manual is None:
            offset = self.ctx.user.reminder_offset_days
        projects = {p.id: p for p in self.ds.projects.list()}
        tags = {t.id: t for t in self.ds.tags.list()}
        now = utcnow()
        return TaskOut(
            id=0,
            owner_id=self.ctx.user.id,
            parent_id=None,
            position=0,
            title=d.get("title", ""),
            importance=d.get("importance", Importance.NORMAL),
            urgency=d.get("urgency", Urgency.SOON),
            due_date=d.get("due_date"),
            due_time=d.get("due_time"),
            status=d.get("status", Status.NOT_STARTED),
            kind=kind,
            reminder_offset_days=offset,
            reminder_date=rules.effective_reminder(kind, d.get("due_date"), offset, manual),
            notes=d.get("notes", ""),
            project=projects.get(d.get("project_id")),
            tags=[tags[i] for i in d.get("tag_ids", []) if i in tags],
            created_at=now,
            updated_at=now,
            completed_at=None,
        )

    # ==================================================================================================
    # Construction
    # ==================================================================================================

    def _build_content(self, task: TaskOut) -> None:
        self._header(task, left=self._parent_header if task.parent_id is not None else None)
        self._title(task)
        self._sliders(task)
        self._dates(task)
        self.reminder_box = ui.column().classes("w-full gap-2")
        self._reminder()
        self._labels(task)
        if self.is_draft:
            ui.label(
                "🌳 Sous-tâches, 🔗 liens et 👥 partage : disponibles dès que la tâche a un titre."
            ).classes("text-sm text-gray-500")
            self._notes(task)
            return
        if task.owner_id == self.ctx.user.id:
            self._sharing(task)
        if task.parent_id is None:
            self.subtasks_box = ui.column().classes("w-full gap-1")
            self._subtasks()
        self.links_box = ui.column().classes("w-full gap-1")
        self._links()
        self._notes(task)
        self._footer(task)

    def _parent_header(self) -> None:
        task = self.task
        ui.button(f"↳ {task.parent_title}", on_click=lambda: self.open(task.parent_id)).props(
            "flat dense no-caps"
        ).classes("text-sm").tooltip("Sous-tâche : ouvrir la tâche parente")
        ui.button("🌳 Détacher", on_click=self._detach).props("flat dense no-caps").classes(
            "text-sm"
        ).tooltip("En faire une tâche indépendante")

    def _sliders(self, task: TaskOut) -> None:
        with ui.element("div").classes("grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2 w-full"):
            LevelSlider(
                "Importance",
                list(Importance),
                task.importance,
                lambda v: self._save(importance=v),
                marker="slider-importance",
            )
            LevelSlider(
                "Urgence",
                list(Urgency),
                task.urgency,
                lambda v: self._save(urgency=v),
                marker="slider-urgency",
            )
            LevelSlider("Statut", list(Status), task.status, self._status_changed, marker="slider-status")
            LevelSlider(
                "Type",
                list(TaskKind),
                task.kind,
                lambda v: self._save(rebuild=True, kind=v),
                marker="slider-kind",
            )

    def _status_changed(self, status: Status) -> None:
        if self._save(status=status) and self.task.parent_id is not None and status is Status.DONE:
            self._maybe_suggest_parent(self.task.parent_id)

    # --- dates ---

    def _dates(self, task: TaskOut) -> None:
        today = self.ctx.today()
        with ui.column().classes("w-full gap-1"):
            with ui.row().classes("w-full items-center gap-2"):
                due = (
                    ui.date_input("📅 Échéance", value=task.due_date.isoformat() if task.due_date else "")
                    .props("outlined dense clearable")
                    .classes("w-48")
                    .mark("editor-due")
                )
                due.on_value_change(lambda e: self._due_changed(e.value))
                due_time = (
                    ui.input("🕐 Heure", value=task.due_time.strftime("%H:%M") if task.due_time else "")
                    .props("outlined dense type=time clearable")
                    .classes("w-32")
                    .mark("editor-due-time")
                    .tooltip("Heure facultative")
                )
                due_time.set_enabled(task.due_date is not None)
                due_time.on_value_change(lambda e: self._time_changed(e.value))
                for label, target in (
                    ("Aujourd'hui", today),
                    ("Demain", today + timedelta(days=1)),
                    ("+1 semaine", today + timedelta(days=7)),
                ):
                    ui.button(label, on_click=lambda d=target: due.set_value(d.isoformat())).props(
                        "flat dense no-caps size=sm"
                    )
                ui.button("Aucune", on_click=lambda: due.set_value("")).props("flat dense no-caps size=sm")
            if task.due_date is not None:
                ui.label(f"{fmt.long_date(task.due_date)} — {fmt.relative(task.due_date, today)}").classes(
                    "text-xs text-gray-500 pl-1"
                )
            if task.due_after_parent:
                ui.label("⚠️ Cette échéance dépasse celle de la tâche parente.").classes(
                    "text-xs text-amber-700"
                )

    def _time_changed(self, value: str | None) -> None:
        new_time = parse_time(value)
        if new_time != self.task.due_time:
            self._save(due_time=new_time)

    def _due_changed(self, value: str | None) -> None:
        new_due = parse_date(value)
        if new_due != self.task.due_date:
            self._save(rebuild=True, due_date=new_due)

    def _reminder(self) -> None:
        task = self.task
        self.reminder_box.clear()
        self.reminder_box.set_visibility(task.kind is TaskKind.FOLLOWUP)
        if task.kind is not TaskKind.FOLLOWUP:
            return
        today = self.ctx.today()
        with self.reminder_box, ui.card().classes("w-full p-3 gap-2 bg-cyan-50 dark:bg-cyan-950 shadow-none"):
            with ui.row().classes("w-full items-center gap-3"):
                ui.label("🔔 Rappel").classes("font-semibold")
                mode = "offset" if task.reminder_offset_days is not None else "manual"
                ui.toggle(
                    {"offset": "🔗 Lié à l'échéance", "manual": "📌 Date fixe"},
                    value=mode,
                    on_change=lambda e: self._reminder_mode(e.value),
                ).props("dense no-caps unelevated")
            if mode == "offset":
                ui.number(
                    "Jours avant l'échéance",
                    value=task.reminder_offset_days,
                    min=0,
                    max=365,
                    step=1,
                    precision=0,
                    on_change=lambda e: self._offset_changed(e.value),
                ).props("outlined dense").classes("w-48")
            else:
                manual = ui.date_input(
                    "Date du rappel", value=task.reminder_date.isoformat() if task.reminder_date else ""
                ).props("outlined dense")
                manual.on_value_change(lambda e: self._save(rebuild=True, reminder_date=parse_date(e.value)))
            if task.reminder_date is not None:
                when = f"{fmt.long_date(task.reminder_date)} ({fmt.relative(task.reminder_date, today)})"
                ui.label(f"Rappel le {when}").classes("text-sm")
            elif mode == "offset":
                ui.label("Pas de rappel tant qu'il n'y a pas d'échéance.").classes("text-sm text-gray-500")

    def _offset_changed(self, value: float | None) -> None:
        if value is not None and int(value) != self.task.reminder_offset_days:
            self._save(rebuild=True, reminder_offset_days=int(value))

    def _reminder_mode(self, mode: str) -> None:
        if mode == "offset":
            self._save(rebuild=True, reminder_offset_days=self.ctx.user.reminder_offset_days)
        else:
            self._save(rebuild=True, reminder_date=self.task.reminder_date or self.ctx.today())

    # --- partage ---

    def _sharing(self, task: TaskOut) -> None:
        others = {u.id: f"👤 {u.display_name}" for u in self.ds.users_public() if u.id != self.ctx.user.id}
        if not others:
            return

        def changed(values: list) -> None:
            updated = self.ctx.call(self.ds.tasks.set_shares, self.task.id, list(values or []))
            if updated is not None:
                self.task = updated
                self._flash_saved()
                self._page_changed()

        ui.select(
            others,
            label="👥 Partager avec (droit de modification)",
            value=task.shared_with,
            multiple=True,
            on_change=lambda e: changed(e.value),
        ).props("outlined dense use-chips").classes("w-full")

    # --- sous-tâches ---

    def _subtasks(self) -> None:
        task = self.task
        self.subtasks_box.clear()
        subs = self.ds.tasks.subtasks(task.id)
        with self.subtasks_box:
            with ui.row().classes("w-full items-center gap-2"):
                ui.label("🌳 Sous-tâches").classes("font-semibold")
                active = [s for s in subs if s.status is not Status.CANCELLED]
                if active:
                    done = sum(s.status is Status.DONE for s in active)
                    ui.linear_progress(value=done / len(active), show_value=False).props(
                        "rounded size=8px color=positive"
                    ).classes("w-24")
                    ui.label(f"{done}/{len(active)}").classes("text-sm text-gray-500")
            for sub in subs:
                with ui.row().classes(
                    "w-full items-center gap-1 no-wrap hover:bg-gray-100 dark:hover:bg-gray-800 rounded"
                ):
                    ui.checkbox(
                        value=sub.status is Status.DONE,
                        on_change=lambda e, s=sub: self._toggle_subtask(s, e.value),
                    ).props("dense").tooltip("Cocher pour terminer")
                    ui.label(sub.status.meta.emoji).tooltip(sub.status.meta.label)
                    title = ui.label(sub.title).classes("flex-1 cursor-pointer")
                    if sub.status.is_closed:
                        title.classes("line-through text-gray-500")
                    title.on("click", lambda s=sub: self.open(s.id))
                    if sub.due_date:
                        ui.label(fmt.short_date(sub.due_date, self.ctx.today())).classes("chip")
                    ui.button(icon="edit", on_click=lambda s=sub: self.open(s.id)).props(
                        "flat round dense size=sm"
                    ).tooltip("Ouvrir la sous-tâche")
            new = (
                ui.input(placeholder="➕ Ajouter une sous-tâche… (Entrée)")
                .props("dense borderless")
                .classes("w-full")
                .mark("editor-new-subtask")
            )

            def add() -> None:
                text = (new.value or "").strip()
                if not text:
                    return
                if self.ctx.call(self.ds.tasks.create, TaskCreate(title=text, parent_id=self.task.id)):
                    self.task = self.ds.tasks.get(self.task.id)
                    self._page_changed()
                    self._subtasks()
                    self._focus_new_subtask()

            new.on("keydown.enter", add)

    def _focus_new_subtask(self) -> None:
        for element in self.subtasks_box.descendants():
            if isinstance(element, ui.input):
                element.run_method("focus")

    def _toggle_subtask(self, sub: TaskOut, done: bool) -> None:
        target = Status.DONE if done else Status.NOT_STARTED
        if sub.status is target or (not done and sub.status is not Status.DONE):
            return
        if self.ctx.call(self.ds.tasks.update, sub.id, TaskPatch(status=target)) is None:
            return
        self.task = self.ds.tasks.get(self.task.id)
        self._page_changed()
        self._subtasks()
        if done:
            self._maybe_suggest_parent(self.task.id)

    def _maybe_suggest_parent(self, parent_id: int) -> None:
        parent = self.ctx.call(self.ds.tasks.get, parent_id)
        if parent is None or not rules.should_suggest_parent_completion(parent):
            return
        with ui.dialog() as dialog, ui.card().classes("gap-3 items-center"):
            ui.label("🎉").classes("text-4xl")
            ui.label("Toutes les sous-tâches sont finies !").classes("text-lg font-semibold")
            ui.label(f"Marquer « {parent.title} » comme terminée ?")
            with ui.row().classes("gap-2"):
                ui.button("Plus tard", on_click=dialog.close).props("flat")

                def finish() -> None:
                    dialog.close()
                    if self.ctx.call(self.ds.tasks.update, parent.id, TaskPatch(status=Status.DONE)):
                        ui.notify(f"✅ « {parent.title} » terminée", position="top")
                        self._page_changed()
                        self.reload()

                ui.button("✅ Oui, terminer", on_click=finish, color="positive")
        dialog.open()

    def _detach(self) -> None:
        updated = self.ctx.call(self.ds.tasks.detach, self.task.id)
        if updated is not None:
            self.task = updated
            self._page_changed()
            self._build()

    def _footer(self, task: TaskOut) -> None:
        ui.separator()
        with ui.row().classes("w-full items-center gap-2 text-xs text-gray-500"):
            self._dates_footer(task, feminine=True)
            ui.space()
            ui.button("📋 Dupliquer", on_click=lambda: duplicate(self.task, self.ctx)).props(
                "flat no-caps"
            ).tooltip("Créer une copie de cette tâche (et de ses sous-tâches)")
            ui.button("➕ Nouvelle tâche", on_click=lambda: self.editor.open_new()).props(
                "flat no-caps"
            ).tooltip("Créer une autre tâche (N)")
            if task.can_delete:
                ui.button(
                    "🗑️ Supprimer",
                    on_click=lambda: confirm_delete(self.task, self.ctx, after=self.dialog.close),
                ).props("flat no-caps color=negative")
