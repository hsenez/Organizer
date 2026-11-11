"""Éditeur de tâche ou d'événement : panneau latéral (plein écran sur téléphone), enregistrement automatique.

- :class:`Editor` (``ctx.editor``) : le panneau (une seule fenêtre par page) et l'aiguillage entre les deux
  éditeurs ; la bascule « 📋 Tâche / 📅 Événement » de l'en-tête passe de l'un à l'autre (voir
  :meth:`Editor.switch`).
- :class:`ItemEditor` : tout ce qui est commun — brouillon, enregistrement, titre, projet, tags, liens et
  fichiers, notes. Sous-classes : ``TaskEditor`` (curseurs, échéance, rappel, sous-tâches, partage) et
  ``EventEditor`` (début / fin, lieu, couleur, public, partage modifiable ou non).

Chaque modification est enregistrée immédiatement (les frappes rapides sont regroupées dans l'historique
annuler / rétablir). **Création** : l'éditeur complet s'ouvre sur un *brouillon* (``draft`` : champs du
schéma de création) ; l'élément est créé en base dès qu'il a un titre. Sans titre, rien n'est créé.
"""

from __future__ import annotations

import io
from datetime import date, time
from typing import Any

from nicegui import events, ui

from organizer.core import rules
from organizer.core.enums import LinkKind
from organizer.core.schemas import LinkIn, TagIn
from organizer.ui import format as fmt
from organizer.ui.components.file_drop import (
    attach_local_files,
    file_drop_zone,
    open_file_picker,
    reusable_upload,
)
from organizer.ui.components.markdown_editor import MarkdownEditor
from organizer.ui.components.ref_links import RefLinks, open_ref
from organizer.ui.components.tag_chips import color_tag_select
from organizer.ui.context import UiContext

NO_PROJECT = 0
COMMON_DRAFT_KEYS = ("title", "notes", "project_id", "tag_ids")
KINDS = {"task": "📋 Tâche", "event": "📅 Événement"}


class Editor:
    """Le panneau d'édition de la page (``ctx.editor``), partagé par l'éditeur de tâche et d'événement."""

    def __init__(self, ctx: UiContext):
        from organizer.ui.components.event_editor import EventEditor
        from organizer.ui.components.task_editor import TaskEditor

        self.ctx = ctx
        with (
            ui.dialog().props("position=right full-height").mark("task-editor-dialog") as self.dialog,
            ui.card()
            .classes("w-[660px] max-w-[100vw] h-full rounded-none p-0 gap-0")
            .mark("task-editor") as card,
        ):
            self.body = ui.column().classes("w-full h-full overflow-y-auto p-4 sm:p-6 gap-4 no-wrap")
            # Envoi de fichiers, invisible et permanent : le bouton « Joindre un fichier » ouvre son
            # sélecteur, et les fichiers déposés n'importe où sur l'éditeur lui sont confiés.
            self.upload = reusable_upload(
                ui.upload(auto_upload=True, multiple=True, on_upload=lambda e: self.active._uploaded(e))
                .classes("hidden")
                .mark("editor-upload")
            )
        file_drop_zone(card, self.upload)
        self.dialog.on("hide", lambda: self.active._on_hide())
        self.tasks = TaskEditor(self)
        self.events = EventEditor(self)
        self.active: ItemEditor = self.tasks

    # --- ouverture (depuis les pages) ---

    def _start(self, editor: ItemEditor) -> ItemEditor:
        """Nouvelle session d'édition : on oublie les champs gardés pour une rebascule."""
        if self.dialog.value and self.active is not editor:
            self.active._leave()
        self.tasks.stash = {}
        self.events.stash = {}
        self.active = editor
        return editor

    def open(self, task_id: int) -> None:
        self._start(self.tasks).open(task_id)

    def open_new(self, **draft: Any) -> None:
        """Nouvelle tâche ; ``draft`` : champs déjà remplis (ex. ``due_date``)."""
        self._start(self.tasks).open_new(draft)

    def open_event(self, event_id: int) -> None:
        self._start(self.events).open(event_id)

    def open_new_event(self, **draft: Any) -> None:
        """Nouvel événement ; ``draft`` : champs de ``EventCreate`` (début, fin…)."""
        self._start(self.events).open_new(draft)

    @property
    def is_draft(self) -> bool:
        return self.active.is_draft

    def reload(self) -> None:
        self.active.reload()

    def attach_local_files(self, paths: list) -> None:
        self.active.attach_local_files(paths)

    # --- bascule tâche ↔ événement ---

    def switch(self, kind: str) -> None:
        """Passe de l'éditeur de tâche à celui d'événement (ou l'inverse) en gardant les champs communs.

        Brouillon : les champs propres à l'un sont gardés (``stash``) pour une éventuelle rebascule.
        Élément existant : il est **converti** (une seule action, Ctrl+Z l'annule), en réappliquant les
        champs propres gardés d'une conversion précédente de la même session."""
        source = self.active
        target = self.events if kind == "event" else self.tasks
        if target is source:
            return
        if source.is_draft:
            common = source.common_draft()
            source.stash = source.specific_draft()
            specific = target.stash or target.specific_from(source)
            self.active = target
            target.open_new({**common, **specific})
            return
        source._save_notes()
        stash = source.specific_of_item()
        converted = target.convert_from(source)
        if converted is None:
            source._build()  # remet la bascule sur sa valeur
            return
        source.stash = stash
        source.item = None
        self.active = target
        target.draft = None
        target.item = converted
        target._build()
        target._page_changed()
        noun = "un événement" if kind == "event" else "une tâche"
        with self.dialog:  # l'élément qui a déclenché la bascule vient d'être remplacé
            ui.notify(f"🔁 « {converted.title} » est devenu {noun} (Ctrl+Z pour annuler)", position="top")


class ItemEditor:
    """Base des éditeurs : ``item`` (objet affiché, ``*Out``) ou brouillon (``draft``)."""

    kind = "item"
    noun = "élément"
    created_text = "✔ Créé"
    new_label = "✨ Nouveau"
    creation_hint = "Il sera créé dès que vous lui aurez donné un titre."
    title_placeholder = "Titre"

    def __init__(self, editor: Editor):
        self.editor = editor
        self.ctx = editor.ctx
        self.item: Any = None
        self.draft: dict | None = None
        self.stash: dict = {}  # champs propres gardés pendant une bascule vers l'autre éditeur

    # --- à fournir par les sous-classes ---

    @property
    def service(self) -> Any:
        raise NotImplementedError

    def _create(self, title: str, fields: dict) -> Any:
        raise NotImplementedError

    def _update(self, item_id: int, fields: dict) -> Any:
        raise NotImplementedError

    def _draft_out(self) -> Any:
        raise NotImplementedError

    def _build_content(self, item: Any) -> None:
        raise NotImplementedError

    def _upload_fn(self):
        raise NotImplementedError

    def specific_draft(self) -> dict:
        """Champs propres du brouillon (gardés pendant une bascule)."""
        return {k: v for k, v in (self.draft or {}).items() if k not in COMMON_DRAFT_KEYS}

    def specific_of_item(self) -> dict:
        """Champs propres de l'élément affiché, à réappliquer s'il redevient de ce type."""
        return {}

    def specific_from(self, other: ItemEditor) -> dict:
        """Champs propres déduits du brouillon de l'autre éditeur (ex. échéance → début)."""
        return {}

    def convert_from(self, other: ItemEditor) -> Any:
        """Convertit l'élément existant de l'autre éditeur (en réappliquant, dans la même action, les champs
        propres gardés d'une conversion précédente) ; renvoie le nouvel objet (None : refus)."""
        raise NotImplementedError

    def can_switch(self) -> tuple[bool, str]:
        """La bascule est-elle possible ? (oui, ou non avec la raison en infobulle)."""
        if self.is_draft:
            return True, ""
        if self.item.owner_id != self.ctx.user.id:
            return False, "Seul le propriétaire peut changer le type"
        return True, ""

    # --- dialogue partagé ---

    @property
    def ds(self):
        return self.ctx.ds

    @property
    def dialog(self) -> ui.dialog:
        return self.editor.dialog

    @property
    def body(self) -> ui.column:
        return self.editor.body

    @property
    def upload(self) -> ui.upload:
        return self.editor.upload

    @property
    def is_draft(self) -> bool:
        return self.draft is not None

    # ==================================================================================================
    # Ouverture / fermeture
    # ==================================================================================================

    def open(self, item_id: int) -> None:
        item = self.ctx.call(self.service.get, item_id)
        if item is None:
            return
        self.draft = None
        self.item = item
        self._build()
        self.dialog.open()

    def open_new(self, draft: dict | None = None) -> None:
        self.draft = dict(draft or {})
        self.item = self._draft_out()
        self._build()
        self.dialog.open()

    def reload(self) -> None:
        """Recharge l'élément affiché (après Ctrl+Z…) ; ferme l'éditeur s'il n'existe plus."""
        if self.item is None or not self.dialog.value or self.is_draft:
            return
        try:
            self.item = self.service.get(self.item.id)
        except Exception:
            self.dialog.close()
            return
        self._build()

    def _page_changed(self) -> None:
        """Modification faite dans l'éditeur ouvert : la page derrière n'est relue qu'à sa fermeture
        (``_on_hide``), une requête de moins par clic (≈ 300 ms pour le client bureau à travers Internet).
        Seuls les boutons annuler / rétablir suivent tout de suite."""
        if self.dialog.value:
            self.ctx.refresh(light=True)
        else:
            self.ctx.refresh()

    def _leave(self) -> None:
        """Un autre éditeur prend le panneau : enregistre ce qui reste à enregistrer."""
        self._save_notes()
        if self.is_draft and (self.title_input.value or "").strip():
            self._create_from_draft(self.title_input.value.strip(), rebuild=False)

    def _on_hide(self) -> None:
        self._leave()
        self.item = None
        self.draft = None
        self.stash = {}
        self.ctx.refresh()

    # ==================================================================================================
    # Enregistrement
    # ==================================================================================================

    def _save(self, rebuild: bool = False, **fields) -> bool:
        assert self.item is not None
        if self.is_draft:
            return self._save_draft(rebuild, fields)
        updated = self.ctx.call(self._update, self.item.id, fields)
        if updated is None:
            self.reload()  # on réaffiche l'état réel
            return False
        self.item = updated
        self._flash_saved()
        self._page_changed()
        if rebuild:
            self._build()
        return True

    def _save_draft(self, rebuild: bool, fields: dict) -> bool:
        if "title" in fields:
            return self._create_from_draft(fields.pop("title"), rebuild=True, extra=fields)
        self._merge_draft(fields)
        self.item = self._draft_out()
        if rebuild:
            self._build()
        return True

    def _merge_draft(self, fields: dict) -> None:
        self.draft.update(fields)

    def _create_from_draft(self, title: str, *, rebuild: bool, extra: dict | None = None) -> bool:
        fields = {**self.draft, **(extra or {})}
        fields.pop("title", None)
        created = self.ctx.call(self._create, title, fields)
        if created is None:
            return False
        self.draft = None
        self.item = created
        self._page_changed()
        if rebuild:
            self._build()
            self._flash_saved(self.created_text)
        return True

    def common_draft(self) -> dict:
        """Champs communs du brouillon, avec ce qui est en cours de saisie (titre, notes)."""
        common = {k: v for k, v in (self.draft or {}).items() if k in COMMON_DRAFT_KEYS}
        title = (self.title_input.value or "").strip()
        if title:
            common["title"] = title
        notes = getattr(self, "notes_editor", None)
        if notes is not None and notes.value:
            common["notes"] = notes.value
        return common

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
        item = self.item
        assert item is not None
        self.body.clear()
        with self.body:
            self._build_content(item)

    def _header(self, item: Any, left=None) -> None:
        """En-tête : bascule tâche / événement (ou ``left`` : autre contenu à gauche), « Enregistré », ✕."""
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            if left is not None:
                left()
            else:
                self._kind_toggle()
            ui.space()
            self.saved = ui.label().classes(
                "text-sm text-green-600 transition-opacity duration-500 opacity-0"
            )
            ui.button(icon="close", on_click=self.dialog.close).props("flat round dense").tooltip(
                "Fermer (Échap)"
            )

    def _kind_toggle(self) -> None:
        allowed, reason = self.can_switch()
        toggle = (
            ui.toggle(KINDS, value=self.kind, on_change=lambda e: self.editor.switch(e.value))
            .props("dense no-caps unelevated rounded")
            .mark("editor-kind")
        )
        if not allowed:
            toggle.set_enabled(False)
            toggle.tooltip(reason)
        elif self.is_draft:
            toggle.tooltip("Créer plutôt une tâche ou un événement (les champs communs sont gardés)")
        else:
            toggle.tooltip("Transformer en tâche / en événement (Ctrl+Z pour annuler)")
        if self.is_draft:
            ui.label(self.new_label).classes("text-sm font-semibold text-primary")

    def _title(self, item: Any) -> None:
        title = (
            ui.textarea(value=item.title, placeholder=self.title_placeholder)
            .props('borderless autogrow dense input-class="text-2xl font-bold leading-tight"')
            .classes("w-full -mt-2")
            .mark("editor-title")
        )
        self.title_input = title
        if self.is_draft:
            title.props("autofocus")
            ui.label(self.creation_hint).classes("text-xs text-gray-500 -mt-3")

        def save_title() -> None:
            value = (title.value or "").strip()
            if not value:
                if not self.is_draft:
                    title.set_value(self.item.title)
                return
            if value != self.item.title:
                self._save(title=value)

        title.on("blur", save_title)
        title.on("keydown.enter.prevent", lambda: title.run_method("blur"))

    # --- projet, tags ---

    def _labels(self, item: Any) -> None:
        self.tags_select = label_selects(
            self.ctx,
            item,
            on_project=lambda value: self._save(rebuild=self.kind == "event", project_id=value),
            on_tags=self._tags_changed,
        )

    def _tags_changed(self, values: list) -> None:
        ids, created = tag_ids_from(self.ctx, values)
        if sorted(ids) != sorted(t.id for t in self.item.tags) or created:
            self._save(rebuild=created, tag_ids=ids)

    # --- liens ---

    def _links(self, *, editable: bool = True) -> None:
        item = self.item
        self.links_box.clear()
        with self.links_box:
            ui.label("🔗 Liens et fichiers").classes("font-semibold")
            for link in item.links:
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
                    if editable:
                        ui.button(icon="close", on_click=lambda lk=link: self._remove_link(lk.id)).props(
                            "flat round dense size=sm"
                        ).tooltip("Retirer ce lien")
            if not editable:
                if not item.links:
                    ui.label("Aucun").classes("text-sm text-gray-500")
                return
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
                if self.ctx.call(self.service.add_link, self.item.id, LinkIn(kind=kind, target=target)):
                    self._after_links_change()

            new.on("keydown.enter", add)
            open_file_picker(
                ui.button("📎 Joindre un fichier").props("flat dense no-caps").mark("editor-attach"),
                self.upload,
            ).tooltip("Envoyer des fichiers sur le serveur (50 Mo max chacun) — ou déposez-les sur l'éditeur")

    def _can_attach(self) -> bool:
        if self.item is None or self.is_draft or not self.dialog.value:
            ui.notify(
                f"Donnez d'abord un titre à {self.noun}, puis joignez le fichier.",
                type="warning",
                position="top",
            )
            return False
        if not getattr(self.item, "can_edit", True):
            ui.notify("Lecture seule : impossible de joindre un fichier.", type="warning", position="top")
            return False
        return True

    def attach_local_files(self, paths: list) -> None:
        """Fichiers du poste déposés sur l'éditeur, connus par leur chemin (client bureau)."""
        if not self._can_attach():
            return
        names = attach_local_files(self.ctx, self.item.id, paths, upload=self._upload_fn())
        if names:
            ui.notify(f"📎 {', '.join(names)} ajouté(s)", position="top")
            self._after_links_change()

    async def _uploaded(self, e: events.UploadEventArguments) -> None:
        if not self._can_attach():
            return
        data = await e.file.read()
        link = self.ctx.call(
            self._upload_fn(), self.item.id, e.file.name, io.BytesIO(data), e.file.content_type
        )
        if link is not None:
            ui.notify(f"📎 « {link.label} » ajouté", position="top")
            self._after_links_change()

    def _remove_link(self, link_id: int) -> None:
        if self.ctx.attempt(self.service.remove_link, link_id):
            self._after_links_change()

    def _after_links_change(self) -> None:
        self.item = self.service.get(self.item.id)
        self._flash_saved()
        self._page_changed()
        self._links()

    def _open_link(self, link) -> None:
        self.ctx.call(open_link, link.kind, link.target, self.ds)

    # --- notes ---

    def _notes(self, item: Any) -> None:
        with ui.column().classes("w-full gap-1"):
            with ui.row().classes("w-full items-baseline gap-2"):
                ui.label("📝 Notes").classes("font-semibold")
                ui.label("markdown · clic sur un lien pour l'ouvrir · [[ pour citer").classes(
                    "text-xs text-gray-500"
                )
            self.notes_editor = (
                MarkdownEditor(
                    item.notes,
                    placeholder="Écrire ici… « - » liste, « 1. » numérotée, « - [ ] » case à cocher, "
                    "**gras**, # titre, [[ lien vers une note / tâche / événement",
                    on_open_link=self._open_note_link,
                    on_ref_request=lambda: self.ref_links.pick(),
                )
                .classes("w-full")
                .mark("editor-notes")
            )
            self.ref_links = RefLinks(self.ctx, self.notes_editor, exclude=self._self_ref(item))
        self.notes_editor.on("update:value", lambda: self.ref_links.update(self.notes_editor.value or ""))
        self.notes_editor.on("update:value", self._save_notes, throttle=1.5, leading_events=False)
        self.notes_editor.on("blur", self._save_notes)

    def _self_ref(self, item: Any) -> str | None:
        return f"{self.kind}:{item.id}" if item is not None and item.id else None

    def _open_note_link(self, target: str, kind: str) -> None:
        """Clic sur un lien des notes : lien interne → l'élément (après avoir enregistré) ; une adresse
        reconnue comme web par le markdown est toujours ouverte ; sinon on devine (adresse web ou chemin)."""
        if kind == "ref" or rules.parse_ref(target) is not None:
            self._leave()
            open_ref(self.ctx, target)
            return
        link_kind = LinkKind.URL if kind == "url" else rules.detect_link_kind(target)
        self.ctx.call(open_link, link_kind, target, self.ds)

    def _save_notes(self) -> None:
        """Enregistre les notes si elles ont changé (frappe : au plus toutes les 1,5 s ; sortie du champ)."""
        if self.item is None or getattr(self, "notes_editor", None) is None:
            return
        if not getattr(self.item, "can_edit", True):
            return
        text = self.notes_editor.value or ""
        if text != self.item.notes:
            self._save(notes=text)

    def _dates_footer(self, item: Any, feminine: bool) -> None:
        e = "e" if feminine else ""
        with ui.column().classes("gap-0"):
            ui.label(f"Créé{e} le {fmt.local_datetime(item.created_at)}")
            ui.label(f"Modifié{e} le {fmt.local_datetime(item.updated_at)}")
            if item.owner_id != self.ctx.user.id:
                owner = next((u.display_name for u in self.ds.users_public() if u.id == item.owner_id), "?")
                ui.label(f"👤 Appartient à {owner}")


# ======================================================================================================
# Projet et tags (éditeurs de tâche / d'événement, page Notes)
# ======================================================================================================


def label_selects(ctx: UiContext, item: Any, *, on_project, on_tags) -> ui.select:
    """Listes « 📁 Projet » et « 🏷️ Tags » (création d'un tag en tapant son nom) ; renvoie celle des tags.

    ``on_project(id | None)`` ; ``on_tags(valeurs)`` (identifiants ou noms tapés, :func:`tag_ids_from`).
    Noms rendus distincts : un privé et un public d'un autre peuvent porter le même nom."""
    ds = ctx.ds
    visible_projects = ds.projects.list()
    project_names = rules.label_names(visible_projects)
    projects = {NO_PROJECT: "— Aucun projet —"}
    projects.update({p.id: f"{p.emoji} {project_names[p.id]}" for p in visible_projects})
    if item.project is not None and item.project.id not in projects:  # projet archivé
        projects[item.project.id] = f"{item.project.emoji} {item.project.name} (archivé)"
    all_tags = ds.tags.list()
    tag_names = rules.label_names(all_tags)
    tags = {t.id: tag_names[t.id] for t in all_tags}
    with ui.element("div").classes("grid grid-cols-1 sm:grid-cols-2 gap-3 w-full"):
        ui.select(
            projects,
            label="📁 Projet / sujet",
            value=item.project.id if item.project else NO_PROJECT,
            on_change=lambda e: on_project(e.value or None),
        ).props("outlined dense options-dense").mark("editor-project")
        tags_select = (
            ui.select(
                tags,
                label="🏷️ Tags (taper pour créer)",
                value=[t.id for t in item.tags],
                multiple=True,
                with_input=True,
                new_value_mode="add-unique",
                on_change=lambda e: on_tags(e.value),
            )
            .props("outlined dense use-chips options-dense")
            .mark("editor-tags")
        )
        color_tag_select(tags_select, {tag_names[t.id]: t.color for t in all_tags})
    return tags_select


def tag_ids_from(ctx: UiContext, values: list | None) -> tuple[list[int], bool]:
    """Identifiants des tags choisis ; un nom tapé désigne d'abord son propre tag (un public d'un autre peut
    porter le même nom), sinon le tag est créé (couleur loin de celles déjà posées). Renvoie aussi « un tag
    a été créé »."""
    ds = ctx.ds
    all_tags = sorted(ds.tags.list(), key=lambda t: t.owner_id == ctx.user.id)
    existing = {t.name.casefold(): t.id for t in all_tags}
    colors = {t.id: t.color for t in all_tags}
    avoid = [colors[v] for v in values or [] if isinstance(v, int) and v in colors]
    ids: list[int] = []
    created = False
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
            tag = ctx.call(ds.tags.create, TagIn(name=name, avoid_colors=avoid))
            if tag is not None:
                ids.append(tag.id)
                avoid.append(tag.color)
                created = True
    return ids, created


# ======================================================================================================
# Liens : ouverture selon le type et la plateforme (spécifications §4.4)
# ======================================================================================================


def _link_action(kind: LinkKind, ds) -> str:
    if kind is LinkKind.PATH and not ds.is_desktop:
        return "Cliquer pour copier le chemin dans le presse-papiers"
    return "Cliquer pour ouvrir"


def open_link(kind: LinkKind, target: str, ds) -> None:
    """Ouvre un lien. Client bureau : navigateur / application par défaut du poste (pièce jointe téléchargée
    puis ouverte) ; web : nouvel onglet, ou chemin copié dans le presse-papiers."""
    if ds.is_desktop:
        if kind is LinkKind.URL:
            ds.open_url(rules.normalize_url(target))
        elif kind is LinkKind.ATTACHMENT:
            ds.open_attachment(target)
            ui.notify("📎 Pièce jointe ouverte", position="top", timeout=1500)
        else:
            ds.open_path(target)
        return
    if kind is LinkKind.URL:
        ui.navigate.to(rules.normalize_url(target), new_tab=True)
    elif kind is LinkKind.ATTACHMENT:
        ui.navigate.to(ds.attachment_url(target), new_tab=True)
    else:
        ui.clipboard.write(target)
        ui.notify("📋 Chemin copié dans le presse-papiers", position="top")


def parse_time(value: str | None) -> time | None:
    if not value:
        return None
    try:
        return time.fromisoformat(value)
    except ValueError:
        return None


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.replace("/", "-"))
    except ValueError:
        return None
