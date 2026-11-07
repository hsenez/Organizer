"""Vue « liste de tâches » : barre de filtres, tri, regroupement, cartes.

Utilisée par « 📋 Toutes les tâches » et « 🔍 Recherche ». Filtres, tri et regroupement sont mémorisés par
utilisateur (préférence ``pref_key``).
"""

from __future__ import annotations

from nicegui import ui

from organizer.core import rules
from organizer.core.enums import DueBucket, Importance, Status, TaskKind
from organizer.core.schemas import TaskFilter, TaskOut, TaskSort
from organizer.ui.components.filter_bar import FilterBar, active_count
from organizer.ui.components.task_card import task_card
from organizer.ui.context import UiContext
from organizer.ui.layout import card_grid, empty_state, section_title

SORTS = {
    "priority": "⚡ Priorité",
    "due": "📅 Échéance",
    "importance": "🔴 Importance",
    "urgency": "🔥 Urgence",
    "created": "🆕 Création",
    "updated": "✏️ Modification",
    "title": "🔤 Titre",
}
GROUPS = {
    "none": "Aucun regroupement",
    "project": "📁 Par projet",
    "status": "📊 Par statut",
    "kind": "🗂️ Par type",
    "due": "📅 Par échéance",
    "importance": "🔴 Par importance",
}


class TaskListView:
    def __init__(
        self,
        ctx: UiContext,
        pref_key: str,
        *,
        default_filter: TaskFilter | None = None,
        default_sort: TaskSort | None = None,
        initial_text: str | None = None,
        mixed_closed: bool = False,
        autofocus: bool = False,
    ):
        """``mixed_closed`` : afficher les tâches finies / annulées avec les autres (recherche) plutôt que
        dans un bloc replié en bas de page."""
        self.ctx = ctx
        self.pref_key = pref_key
        self.mixed_closed = mixed_closed
        self.default_filter = default_filter or TaskFilter()
        prefs = ctx.ds.account.get_pref(pref_key) or {}
        self.flt = _validate(TaskFilter, prefs.get("filter"), self.default_filter)
        self.sort = _validate(TaskSort, prefs.get("sort"), default_sort or TaskSort(key="priority"))
        self.group = prefs.get("group", "none") if prefs.get("group") in GROUPS else "none"
        if initial_text is not None:
            self.flt = self.flt.model_copy(update={"text": initial_text})

        FilterBar(ctx, self.flt, self._filter_changed, default=self.default_filter, autofocus=autofocus)
        with ui.row().classes("w-full items-center gap-2"):
            ui.select(SORTS, value=self.sort.key, label="Trier par", on_change=self._sort_changed).props(
                "outlined dense options-dense"
            ).classes("w-44").mark("list-sort")
            self.direction = (
                ui.button(on_click=self._flip_direction).props("flat round dense").mark("list-direction")
            )
            ui.select(GROUPS, value=self.group, label="Regrouper", on_change=self._group_changed).props(
                "outlined dense options-dense"
            ).classes("w-48").mark("list-group")
            ui.space()
            self.count = ui.label().classes("text-sm text-gray-500").mark("list-count")
        self._update_direction()
        self.results = ui.refreshable(self._results)
        self.results()
        ctx.on_refresh(self.results.refresh)

    # --- changements ---

    def _save(self) -> None:
        self.ctx.ds.account.set_pref(
            self.pref_key,
            {"filter": self.flt.model_dump(mode="json"), "sort": self.sort.model_dump(), "group": self.group},
        )

    def _filter_changed(self, flt: TaskFilter) -> None:
        self.flt = flt
        self._save()
        self.results.refresh()

    def _sort_changed(self, e) -> None:
        self.sort = TaskSort(key=e.value, descending=False)
        self._update_direction()
        self._save()
        self.results.refresh()

    def _flip_direction(self) -> None:
        self.sort = self.sort.model_copy(update={"descending": not self.sort.descending})
        self._update_direction()
        self._save()
        self.results.refresh()

    def _group_changed(self, e) -> None:
        self.group = e.value
        self._save()
        self.results.refresh()

    def _update_direction(self) -> None:
        self.direction.props(f"icon={'arrow_upward' if self.sort.descending else 'arrow_downward'}")
        self.direction.tooltip("Inverser l'ordre")

    # --- affichage ---

    def _results(self) -> None:
        tasks = self.ctx.ds.tasks.list(self.flt, self.sort)
        self.count.set_text(f"{len(tasks)} tâche{'s' if len(tasks) > 1 else ''}")
        if not tasks:
            empty_state(
                "🔎", "Aucune tâche ne correspond." if _filtered(self.flt) else "Aucune tâche pour l'instant."
            )
            return
        split_closed = not self.mixed_closed and not self.flt.status
        shown = [t for t in tasks if not (split_closed and t.status.is_closed)]
        closed = [t for t in tasks if split_closed and t.status.is_closed]
        if not shown:
            empty_state("🎉", "Aucune tâche ouverte.")
        for emoji, title, group_tasks in self._groups(shown):
            if title:
                section_title(emoji, title, len(group_tasks))
            with card_grid():
                for task in group_tasks:
                    task_card(task, self.ctx)
        if closed:
            with ui.expansion(f"✅ Terminées et annulées ({len(closed)})").classes("w-full"):
                with card_grid():
                    for task in closed:
                        task_card(task, self.ctx)

    def _groups(self, tasks: list[TaskOut]) -> list[tuple[str, str, list[TaskOut]]]:
        """[(emoji, titre, tâches)] dans l'ordre d'affichage (un seul groupe sans titre si pas de
        regroupement)."""
        if self.group == "none":
            return [("", "", tasks)]
        today = self.ctx.today()
        if self.group == "project":
            order = {p.id: i for i, p in enumerate(self.ctx.ds.projects.list(include_archived=True))}
            buckets: dict = {}
            for task in tasks:
                key = task.project.id if task.project else None
                buckets.setdefault(key, []).append(task)
            keys = sorted(buckets, key=lambda k: (k is None, order.get(k, 0)))
            result = []
            for key in keys:
                project = buckets[key][0].project
                result.append(
                    (project.emoji, project.name, buckets[key])
                    if project
                    else ("∅", "Sans projet", buckets[key])
                )
            return result
        enum_type, key_of = {
            "status": (Status, lambda t: t.status),
            "kind": (TaskKind, lambda t: t.kind),
            "due": (DueBucket, lambda t: rules.due_bucket(t.due_date, today)),
            "importance": (Importance, lambda t: t.importance),
        }[self.group]
        members = list(enum_type)
        if enum_type is Importance:
            members.reverse()  # critique d'abord
        return [
            (m.meta.emoji, m.meta.label, [t for t in tasks if key_of(t) == m])
            for m in members
            if any(key_of(t) == m for t in tasks)
        ]


def _filtered(flt: TaskFilter) -> bool:
    return active_count(flt) > 0


def _validate(model, data, default):
    if not data:
        return default
    try:
        return model.model_validate(data)
    except ValueError:
        return default  # préférence enregistrée par une ancienne version : on repart des valeurs par défaut
