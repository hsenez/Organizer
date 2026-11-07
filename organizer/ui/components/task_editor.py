"""Éditeur de tâche : panneau latéral (plein écran sur téléphone), enregistrement automatique.

Chaque modification est enregistrée immédiatement (les frappes rapides sont regroupées dans l'historique
annuler / rétablir). Les notes utilisent l'éditeur markdown « façon Obsidian » (``markdown_editor``).

**Création** (:meth:`TaskEditor.open_new`) : l'éditeur complet s'ouvre sur un *brouillon*. Les réglages
(curseurs, échéance, projet, tags, notes…) sont gardés en mémoire ; la tâche est créée en base dès qu'elle a
un titre (sortie du champ, Entrée, ou fermeture de l'éditeur). Sans titre, rien n'est créé.
"""

from __future__ import annotations

import io
from datetime import date, time, timedelta

from nicegui import events, ui

from organizer.core import rules
from organizer.core.enums import Importance, LinkKind, Status, TaskKind, Urgency
from organizer.core.models import utcnow
from organizer.core.schemas import LinkIn, TagIn, TaskCreate, TaskOut, TaskPatch
from organizer.ui import format as fmt
from organizer.ui.components.level_slider import LevelSlider
from organizer.ui.components.markdown_editor import MarkdownEditor
from organizer.ui.components.tag_chips import color_tag_select
from organizer.ui.components.task_card import confirm_delete, duplicate
from organizer.ui.context import UiContext

NO_PROJECT = 0


class TaskEditor:
    def __init__(self, ctx: UiContext):
        self.ctx = ctx
        self.task: TaskOut | None = None
        self.draft: dict | None = None  # champs de TaskCreate d'une tâche pas encore créée
        with (
            ui.dialog().props("position=right full-height").mark("task-editor-dialog") as self.dialog,
            ui.card().classes("w-[660px] max-w-[100vw] h-full rounded-none p-0 gap-0").mark("task-editor"),
        ):
            self.body = ui.column().classes("w-full h-full overflow-y-auto p-4 sm:p-6 gap-4 no-wrap")
        self.dialog.on("hide", self._on_hide)

    # ==================================================================================================
    # Ouverture / fermeture
    # ==================================================================================================

    @property
    def ds(self):
        return self.ctx.ds

    def open(self, task_id: int) -> None:
        task = self.ctx.call(self.ds.tasks.get, task_id)
        if task is None:
            return
        self.task = task
        self._build()
        self.dialog.open()

    def open_new(self) -> None:
        """Ouvre l'éditeur complet sur une nouvelle tâche (brouillon)."""
        self.draft = {}
        self.task = self._draft_out()
        self._build()
        self.dialog.open()

    @property
    def is_draft(self) -> bool:
        return self.draft is not None

    def reload(self) -> None:
        """Recharge la tâche affichée (après Ctrl+Z…) ; ferme l'éditeur si elle n'existe plus."""
        if self.task is None or not self.dialog.value or self.is_draft:
            return
        try:
            self.task = self.ds.tasks.get(self.task.id)
        except Exception:
            self.dialog.close()
            return
        self._build()

    def _on_hide(self) -> None:
        self._save_notes()  # dernières frappes pas encore enregistrées
        if self.is_draft and (self.title_input.value or "").strip():
            self._create_from_draft(self.title_input.value.strip(), rebuild=False)
        self.task = None
        self.draft = None
        self.ctx.refresh()

    # ==================================================================================================
    # Enregistrement
    # ==================================================================================================

    def _save(self, rebuild: bool = False, **fields) -> bool:
        assert self.task is not None
        if self.is_draft:
            return self._save_draft(rebuild, fields)
        updated = self.ctx.call(self.ds.tasks.update, self.task.id, TaskPatch(**fields))
        if updated is None:
            self.reload()  # on réaffiche l'état réel
            return False
        self.task = updated
        self._flash_saved()
        self.ctx.refresh()
        if rebuild:
            self._build()
        return True

    def _save_draft(self, rebuild: bool, fields: dict) -> bool:
        if "title" in fields:
            return self._create_from_draft(fields.pop("title"), rebuild=True, extra=fields)
        if fields.get("reminder_date") is not None:
            self.draft.pop("reminder_offset_days", None)
        if "reminder_offset_days" in fields:
            self.draft.pop("reminder_date", None)
        self.draft.update(fields)
        self.task = self._draft_out()
        if rebuild:
            self._build()
        return True

    def _create_from_draft(self, title: str, *, rebuild: bool, extra: dict | None = None) -> bool:
        data = TaskCreate(title=title, **{**self.draft, **(extra or {})})
        created = self.ctx.call(self.ds.tasks.create, data)
        if created is None:
            return False
        self.draft = None
        self.task = created
        self.ctx.refresh()
        if rebuild:
            self._build()
            self._flash_saved("✔ Tâche créée")
        return True

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

    def _flash_saved(self, text: str = "✔ Enregistré") -> None:
        if self.is_draft:
            return
        self.saved.set_text(text)
        self.saved.classes(remove="opacity-0")
        ui.timer(1.8, lambda: self.saved.classes(add="opacity-0"), once=True)

    # ==================================================================================================
    # Construction
    # ==================================================================================================

    def _build(self) -> None:
        task = self.task
        assert task is not None
        self.body.clear()
        with self.body:
            self._header(task)
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

    def _header(self, task: TaskOut) -> None:
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            if task.parent_id is not None:
                ui.button(f"↳ {task.parent_title}", on_click=lambda: self.open(task.parent_id)).props(
                    "flat dense no-caps"
                ).classes("text-sm").tooltip("Sous-tâche : ouvrir la tâche parente")
                ui.button("🌳 Détacher", on_click=self._detach).props("flat dense no-caps").classes(
                    "text-sm"
                ).tooltip("En faire une tâche indépendante")
            elif self.is_draft:
                ui.label("✨ Nouvelle tâche").classes("text-sm font-semibold text-primary")
            else:
                ui.label("✏️ Tâche").classes("text-sm text-gray-500")
            ui.space()
            self.saved = ui.label().classes(
                "text-sm text-green-600 transition-opacity duration-500 opacity-0"
            )
            ui.button(icon="close", on_click=self.dialog.close).props("flat round dense").tooltip(
                "Fermer (Échap)"
            )

    def _title(self, task: TaskOut) -> None:
        title = (
            ui.textarea(value=task.title, placeholder="Que faut-il faire ?")
            .props('borderless autogrow dense input-class="text-2xl font-bold leading-tight"')
            .classes("w-full -mt-2")
            .mark("editor-title")
        )
        self.title_input = title
        if self.is_draft:
            title.props("autofocus")
            ui.label("La tâche sera créée dès que vous lui aurez donné un titre.").classes(
                "text-xs text-gray-500 -mt-3"
            )

        def save_title() -> None:
            value = (title.value or "").strip()
            if not value:
                if not self.is_draft:
                    title.set_value(self.task.title)
                return
            if value != self.task.title:
                self._save(title=value)

        title.on("blur", save_title)
        title.on("keydown.enter.prevent", lambda: title.run_method("blur"))

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
        new_time = _parse_time(value)
        if new_time != self.task.due_time:
            self._save(due_time=new_time)

    def _due_changed(self, value: str | None) -> None:
        new_due = _parse_date(value)
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
                manual.on_value_change(lambda e: self._save(rebuild=True, reminder_date=_parse_date(e.value)))
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

    # --- projet, tags, partage ---

    def _labels(self, task: TaskOut) -> None:
        projects = {NO_PROJECT: "— Aucun projet —"}
        projects.update({p.id: f"{p.emoji} {p.name}" for p in self.ds.projects.list()})
        if task.project is not None and task.project.id not in projects:  # projet archivé
            projects[task.project.id] = f"{task.project.emoji} {task.project.name} (archivé)"
        all_tags = self.ds.tags.list()
        tags = {t.id: t.name for t in all_tags}
        with ui.element("div").classes("grid grid-cols-1 sm:grid-cols-2 gap-3 w-full"):
            ui.select(
                projects,
                label="📁 Projet / sujet",
                value=task.project.id if task.project else NO_PROJECT,
                on_change=lambda e: self._save(project_id=e.value or None),
            ).props("outlined dense options-dense")
            self.tags_select = (
                ui.select(
                    tags,
                    label="🏷️ Tags (taper pour créer)",
                    value=[t.id for t in task.tags],
                    multiple=True,
                    with_input=True,
                    new_value_mode="add-unique",
                    on_change=lambda e: self._tags_changed(e.value),
                )
                .props("outlined dense use-chips options-dense")
                .mark("editor-tags")
            )
            color_tag_select(self.tags_select, {t.name: t.color for t in all_tags})

    def _tags_changed(self, values: list) -> None:
        existing = {t.name.casefold(): t.id for t in self.ds.tags.list()}
        ids: list[int] = []
        created = False
        colors = {t.id: t.color for t in self.ds.tags.list()}
        avoid = [colors[v] for v in values or [] if isinstance(v, int) and v in colors]
        for value in values or []:
            if isinstance(value, int):
                ids.append(value)
                continue
            name = str(value).strip()
            if not name:
                continue
            if name.casefold() in existing:
                ids.append(existing[name.casefold()])
            else:
                # Couleur choisie loin de celles des tags déjà sur cette tâche (et des autres tags).
                tag = self.ctx.call(self.ds.tags.create, TagIn(name=name, avoid_colors=avoid))
                if tag is not None:
                    ids.append(tag.id)
                    avoid.append(tag.color)
                    created = True
        if sorted(ids) != sorted(t.id for t in self.task.tags) or created:
            self._save(rebuild=created, tag_ids=ids)

    def _sharing(self, task: TaskOut) -> None:
        others = {u.id: f"👤 {u.display_name}" for u in self.ds.users_public() if u.id != self.ctx.user.id}
        if not others:
            return

        def changed(values: list) -> None:
            updated = self.ctx.call(self.ds.tasks.set_shares, self.task.id, list(values or []))
            if updated is not None:
                self.task = updated
                self._flash_saved()
                self.ctx.refresh()

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
                    self.ctx.refresh()
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
        self.ctx.refresh()
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
                        self.ctx.refresh()
                        self.reload()

                ui.button("✅ Oui, terminer", on_click=finish, color="positive")
        dialog.open()

    def _detach(self) -> None:
        updated = self.ctx.call(self.ds.tasks.detach, self.task.id)
        if updated is not None:
            self.task = updated
            self.ctx.refresh()
            self._build()

    # --- liens ---

    def _links(self) -> None:
        task = self.task
        self.links_box.clear()
        with self.links_box:
            ui.label("🔗 Liens et fichiers").classes("font-semibold")
            for link in task.links:
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    ui.label(link.kind.meta.emoji).tooltip(link.kind.meta.tooltip)
                    with (
                        ui.column()
                        .classes("flex-1 gap-0 min-w-0 cursor-pointer")
                        .on("click", lambda lk=link: self._open_link(lk))
                        .tooltip(_link_action(link.kind, self.ds))
                        .mark(f"link-{link.id}")
                    ):
                        ui.label(link.label or link.target).classes("text-primary truncate w-full")
                        if link.label and link.kind is not LinkKind.ATTACHMENT:
                            ui.label(link.target).classes("text-xs text-gray-500 truncate w-full")
                    ui.button(icon="close", on_click=lambda lk=link: self._remove_link(lk.id)).props(
                        "flat round dense size=sm"
                    ).tooltip("Retirer ce lien")
            new = (
                ui.input(placeholder="Coller une adresse web ou un chemin de fichier, puis Entrée")
                .props("dense outlined")
                .classes("w-full")
                .mark("editor-new-link")
            )

            def add() -> None:
                target = (new.value or "").strip()
                if not target:
                    return
                kind = rules.detect_link_kind(target)
                if self.ctx.call(self.ds.tasks.add_link, self.task.id, LinkIn(kind=kind, target=target)):
                    self._after_links_change()

            new.on("keydown.enter", add)
            # Composant d'envoi invisible : le bouton ouvre directement le sélecteur de fichiers.
            upload = ui.upload(auto_upload=True, on_upload=self._uploaded).classes("hidden")
            ui.button("📎 Joindre un fichier", on_click=lambda: upload.run_method("pickFiles")).props(
                "flat dense no-caps"
            ).tooltip("Envoyer un fichier sur le serveur (50 Mo max)")

    async def _uploaded(self, e: events.UploadEventArguments) -> None:
        data = await e.file.read()
        link = self.ctx.call(
            self.ds.attachments.upload, self.task.id, e.file.name, io.BytesIO(data), e.file.content_type
        )
        if link is not None:
            ui.notify(f"📎 « {link.label} » ajouté", position="top")
            self._after_links_change()

    def _remove_link(self, link_id: int) -> None:
        if self.ctx.attempt(self.ds.tasks.remove_link, link_id):
            self._after_links_change()

    def _after_links_change(self) -> None:
        self.task = self.ds.tasks.get(self.task.id)
        self._flash_saved()
        self.ctx.refresh()
        self._links()

    def _open_link(self, link) -> None:
        open_link(link.kind, link.target, self.ds)

    # --- notes ---

    def _notes(self, task: TaskOut) -> None:
        with ui.column().classes("w-full gap-1"):
            with ui.row().classes("w-full items-baseline gap-2"):
                ui.label("📝 Notes").classes("font-semibold")
                ui.label("markdown · clic sur un lien pour l'ouvrir").classes("text-xs text-gray-500")
            self.notes_editor = (
                MarkdownEditor(
                    task.notes,
                    placeholder="Écrire ici… « - » liste, « 1. » numérotée, « - [ ] » case à cocher, "
                    "**gras**, # titre",
                    on_open_link=self._open_note_link,
                )
                .classes("w-full")
                .mark("editor-notes")
            )
        self.notes_editor.on("update:value", self._save_notes, throttle=1.5, leading_events=False)
        self.notes_editor.on("blur", self._save_notes)

    def _open_note_link(self, target: str, kind: str) -> None:
        """Clic sur un lien des notes : une adresse reconnue comme web par le markdown est toujours ouverte ;
        sinon on devine (adresse web ou chemin de fichier)."""
        link_kind = LinkKind.URL if kind == "url" else rules.detect_link_kind(target)
        open_link(link_kind, target, self.ds)

    def _save_notes(self) -> None:
        """Enregistre les notes si elles ont changé (frappe : au plus toutes les 1,5 s ; sortie du champ)."""
        if self.task is None:
            return
        text = self.notes_editor.value or ""
        if text != self.task.notes:
            self._save(notes=text)

    def _footer(self, task: TaskOut) -> None:
        ui.separator()
        with ui.row().classes("w-full items-center gap-2 text-xs text-gray-500"):
            with ui.column().classes("gap-0"):
                ui.label(f"Créée le {fmt.local_datetime(task.created_at)}")
                ui.label(f"Modifiée le {fmt.local_datetime(task.updated_at)}")
                if task.owner_id != self.ctx.user.id:
                    owner = next(
                        (u.display_name for u in self.ds.users_public() if u.id == task.owner_id), "?"
                    )
                    ui.label(f"👤 Appartient à {owner}")
            ui.space()
            ui.button("📋 Dupliquer", on_click=lambda: duplicate(self.task, self.ctx)).props(
                "flat no-caps"
            ).tooltip("Créer une copie de cette tâche (et de ses sous-tâches)")
            ui.button("➕ Nouvelle tâche", on_click=self.open_new).props("flat no-caps").tooltip(
                "Créer une autre tâche (N)"
            )
            if task.can_delete:
                ui.button(
                    "🗑️ Supprimer",
                    on_click=lambda: confirm_delete(self.task, self.ctx, after=self.dialog.close),
                ).props("flat no-caps color=negative")


# ======================================================================================================
# Liens : ouverture selon le type et la plateforme (spécifications §4.4)
# ======================================================================================================


def _link_action(kind: LinkKind, ds) -> str:
    if kind is LinkKind.PATH and not ds.is_desktop:
        return "Cliquer pour copier le chemin dans le presse-papiers"
    return "Cliquer pour ouvrir"


def open_link(kind: LinkKind, target: str, ds) -> None:
    if kind is LinkKind.URL:
        ui.navigate.to(rules.normalize_url(target), new_tab=True)
    elif kind is LinkKind.ATTACHMENT:
        ui.navigate.to(ds.attachment_url(target), new_tab=True)
    elif ds.is_desktop:
        ds.open_path(target)
    else:
        ui.clipboard.write(target)
        ui.notify("📋 Chemin copié dans le presse-papiers", position="top")


def _parse_time(value: str | None) -> time | None:
    if not value:
        return None
    try:
        return time.fromisoformat(value)
    except ValueError:
        return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.replace("/", "-"))
    except ValueError:
        return None
