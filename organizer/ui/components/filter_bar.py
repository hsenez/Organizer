"""Barre de filtres (liste, recherche ; kanbans et matrice à l'étape 6).

Champ texte (titre, notes, tags, projet ; sans tenir compte des accents) + bouton « 🎛️ Filtres » qui déplie
les menus déroulants multi-choix : importance, urgence, statut, type, projet, tags, échéance, portée,
sous-tâches. Le bouton affiche le nombre de critères actifs ; « Réinitialiser » remet tout à zéro.
"""

from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from organizer.core.enums import DueBucket, Importance, Status, TaskKind, Urgency
from organizer.core.schemas import TaskFilter
from organizer.ui.components.tag_chips import color_tag_select
from organizer.ui.context import UiContext

NO_PROJECT = 0  # clé de l'option « Sans projet » (None dans TaskFilter)

SCOPES = {"all": "👥 Toutes", "mine": "👤 Les miennes", "shared": "🤝 Partagées avec moi"}


def _options(enum_type) -> dict:
    return {member.value: member.meta.text for member in enum_type}


def active_count(flt: TaskFilter, *, ignore_text: bool = False) -> int:
    """Nombre de critères actifs (hors texte si ``ignore_text``)."""
    count = sum(
        bool(getattr(flt, field))
        for field in ("importance", "urgency", "status", "kind", "project_ids", "tag_ids", "due")
    )
    count += flt.scope != "all"
    count += flt.include_subtasks
    if not ignore_text:
        count += bool(flt.text.strip())
    return count


_CRITERIA = (
    "importance",
    "urgency",
    "status",
    "kind",
    "project_ids",
    "tag_ids",
    "due",
    "scope",
    "include_subtasks",
)


def changed_count(flt: TaskFilter, default: TaskFilter) -> int:
    """Nombre de critères modifiés par rapport aux filtres par défaut de la vue (hors texte) : les
    réglages par défaut (ex. statuts ouverts de la matrice) ne comptent pas comme des filtres posés."""
    return sum(getattr(flt, field) != getattr(default, field) for field in _CRITERIA)


class FilterBar:
    def __init__(
        self,
        ctx: UiContext,
        value: TaskFilter,
        on_change: Callable[[TaskFilter], None],
        *,
        default: TaskFilter | None = None,
        placeholder: str = "🔍 Rechercher (titre, notes, tags, projet)…",
        autofocus: bool = False,
    ):
        self.ctx = ctx
        self.value = value.model_copy()
        self.default = default or TaskFilter()
        self._on_change = on_change
        projects = {NO_PROJECT: "∅ Sans projet"}
        projects.update({p.id: f"{p.emoji} {p.name}" for p in ctx.ds.projects.list(include_archived=True)})
        all_tags = ctx.ds.tags.list()
        tags = {t.id: t.name for t in all_tags}

        with ui.column().classes("w-full gap-2").mark("filter-bar"):
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                self.text = (
                    ui.input(placeholder=placeholder, value=self.value.text)
                    .props("outlined dense clearable" + (" autofocus" if autofocus else ""))
                    .classes("flex-1")
                    .mark("filter-text")
                )
                self.text.on("update:model-value", self._text_changed, throttle=0.3, leading_events=False)
                self.text.on("clear", self._text_changed)
                self.toggle_button = (
                    ui.button(on_click=self._toggle_panel).props("outline no-caps").mark("filter-toggle")
                )
            self.panel = ui.element("div").classes(
                "grid w-full gap-2 grid-cols-2 lg:grid-cols-4 items-center"
            )
            with self.panel:
                self.selects = {
                    "importance": self._select("Importance", _options(Importance)),
                    "urgency": self._select("Urgence", _options(Urgency)),
                    "status": self._select("Statut", _options(Status)),
                    "kind": self._select("Type", _options(TaskKind)),
                    "project_ids": self._select("📁 Projet", projects),
                    "tag_ids": color_tag_select(
                        self._select("🏷️ Tags", tags), {t.name: t.color for t in all_tags}
                    ),
                    "due": self._select("📅 Échéance", _options(DueBucket)),
                }
                self.scope = ui.select(
                    SCOPES, value=self.value.scope, label="Portée", on_change=lambda _: self._changed()
                ).props("outlined dense options-dense")
                self.subtasks = ui.checkbox(
                    "🌳 Inclure les sous-tâches",
                    value=self.value.include_subtasks,
                    on_change=lambda _: self._changed(),
                )
                ui.button("↺ Réinitialiser", on_click=self.reset).props("flat no-caps").mark("filter-reset")
        self._load_selects()
        # Panneau déplié d'office seulement si les filtres s'écartent des réglages par défaut de la page.
        self.panel.set_visibility(self._without_text(self.value) != self._without_text(self.default))
        self._update_button()

    def _select(self, label: str, options: dict) -> ui.select:
        return (
            ui.select(
                options, label=label, multiple=True, clearable=True, on_change=lambda _: self._changed()
            )
            .props("outlined dense options-dense use-chips")
            .mark(f"filter-{label}")
        )

    def _load_selects(self) -> None:
        values = {
            "importance": [int(v) for v in self.value.importance],
            "urgency": [int(v) for v in self.value.urgency],
            "status": [str(v) for v in self.value.status],
            "kind": [str(v) for v in self.value.kind],
            "project_ids": [NO_PROJECT if p is None else p for p in self.value.project_ids],
            "tag_ids": list(self.value.tag_ids),
            "due": [str(v) for v in self.value.due],
        }
        self._loading = True
        for field, select in self.selects.items():
            select.set_value(values[field])
        self.scope.set_value(self.value.scope)
        self.subtasks.set_value(self.value.include_subtasks)
        self._loading = False

    def _text_changed(self) -> None:
        self._changed()

    def _changed(self) -> None:
        if getattr(self, "_loading", False):
            return
        selects = {field: list(select.value or []) for field, select in self.selects.items()}
        selects["project_ids"] = [None if p == NO_PROJECT else p for p in selects["project_ids"]]
        self.value = TaskFilter(
            text=self.text.value or "",
            scope=self.scope.value or "all",
            include_subtasks=bool(self.subtasks.value),
            parent_id=self.value.parent_id,
            **selects,
        )
        self._update_button()
        self._on_change(self.value)

    def _update_button(self) -> None:
        count = changed_count(self.value, self.default)
        self.toggle_button.set_text(f"🎛️ Filtres{f' ({count})' if count else ''}")
        self.toggle_button.props(f"color={'primary' if count else 'grey-7'}")

    @staticmethod
    def _without_text(flt: TaskFilter) -> dict:
        return flt.model_dump(mode="json", exclude={"text", "parent_id"})

    def _toggle_panel(self) -> None:
        self.panel.set_visibility(not self.panel.visible)

    def reset(self) -> None:
        self.value = self.default.model_copy(update={"text": ""})
        self.text.set_value("")
        self._load_selects()
        self._changed()
