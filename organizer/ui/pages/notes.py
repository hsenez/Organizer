"""📝 Notes : liste à gauche (épinglées d'abord, recherche, « De qui ? »), note ouverte à droite.

Sur téléphone : la liste, puis la note en plein écran (bouton « ← Notes » pour revenir).

La note s'édite sur place : titre, emoji, projet, tags, texte markdown façon Obsidian avec barre de boutons,
cases à cocher triées (non cochées en haut), liens internes vers des notes / tâches / événements (« [[ »
ou « 🔗 Lier à… »), liens retour (« Cité dans »). Partage et « Public » pour le propriétaire ; lecture seule
sinon. Enregistrement automatique (texte : au plus toutes les 1,5 s pendant la frappe, et à la sortie).

**Modifiée ailleurs** (temps réel) : la note se met à jour si l'on n'est pas en train de taper ; sinon un
bandeau propose de recharger (les modifications de l'autre seraient écrasées par la prochaine frappe).

Adresse : ``/notes?note=<id>`` (ou ``new``) ; « 🔗 Copier le lien » donne l'adresse web complète.
"""

from __future__ import annotations

import time

from fastapi import Request
from fastapi.responses import Response
from nicegui import ui

from organizer.core import rules
from organizer.core.enums import LinkKind
from organizer.core.errors import OrganizerError
from organizer.core.schemas import NoteCreate, NoteFilter, NoteOut, NotePatch, ShareSpec
from organizer.ui import format as fmt
from organizer.ui.components.copy_link import copy_link_button
from organizer.ui.components.emoji_picker import emoji_button
from organizer.ui.components.item_editor import label_selects, open_link, tag_ids_from
from organizer.ui.components.markdown_editor import MarkdownEditor, markdown_toolbar
from organizer.ui.components.ownership import ownership_emoji, ownership_text
from organizer.ui.components.ref_links import RefLinks, as_ref, open_ref
from organizer.ui.components.sharing import public_switch, share_editor
from organizer.ui.components.tag_chips import tag_chip
from organizer.ui.components.viewport import writing_zone
from organizer.ui.context import UiContext
from organizer.ui.layout import app_frame, empty_state

SCOPES = {"all": "👥 Toutes", "mine": "👤 Les miennes", "shared": "🤝 Partagées avec moi"}
TYPING_SECONDS = 5.0  # une frappe plus récente : on ne remplace pas le texte sous les doigts
SNIPPET_LENGTH = 90


def page(make_context):
    def notes_page(request: Request):
        ctx = make_context(request)
        if isinstance(ctx, Response):
            return ctx
        with app_frame(
            ctx,
            "/notes",
            "Notes",
            open_task=request.query_params.get("task"),
            open_event=request.query_params.get("event"),
            wide=True,
        ):
            NotesView(ctx, request.query_params.get("note"))
        return None

    return notes_page


def snippet(text: str) -> str:
    """Début du texte, sans la syntaxe markdown la plus visible (pour la liste)."""
    for line in (text or "").splitlines():
        line = line.strip().lstrip("#>").strip()
        line = line.removeprefix("- [ ] ").removeprefix("- [x] ").removeprefix("- [X] ").lstrip("-*+ ")
        line = line.replace("**", "").replace("~~", "").replace("`", "")
        if line:
            return line if len(line) <= SNIPPET_LENGTH else line[: SNIPPET_LENGTH - 1] + "…"
    return ""


class NotesView:
    def __init__(self, ctx: UiContext, initial: str | None):
        self.ctx = ctx
        self.note: NoteOut | None = None
        self.scope = "all"
        self.text = ""
        self.last_edit = 0.0  # dernière frappe dans le texte (time.monotonic)
        self.editor: MarkdownEditor | None = None
        self.ref_links: RefLinks | None = None
        ctx.open_note = self.select
        ctx.new_note = self.new
        with ui.row().classes("notes-page w-full page-fill-grow no-wrap gap-4 items-stretch") as self.root:
            with ui.column().classes("notes-list gap-2"):
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    ui.label("📝").classes("text-2xl")
                    ui.label("Notes").classes("text-2xl font-bold flex-1")
                    ui.button("➕ Nouvelle", on_click=self.new).props(
                        "unelevated no-caps color=primary"
                    ).mark("notes-new")
                search = (
                    ui.input(placeholder="🔍 Rechercher…")
                    .props("outlined dense clearable")
                    .classes("w-full")
                    .mark("notes-search")
                )
                search.on(
                    "update:model-value",
                    lambda: self._filter(text=search.value or ""),
                    throttle=0.25,
                    leading_events=False,
                )
                ui.select(SCOPES, value=self.scope, on_change=lambda e: self._filter(scope=e.value)).props(
                    "outlined dense options-dense"
                ).classes("w-full").mark("notes-scope")
                self.list_box = ui.column().classes("notes-items w-full gap-1")
            self.view_box = ui.column().classes("notes-view gap-3")
        self._render_list(self.ctx.ds.notes.list(self._flt()))
        ctx.on_refresh(self._on_refresh)
        if initial == "new":
            self.new()
        elif initial and initial.isdigit():
            self.select(int(initial))
        else:
            self._render_view()

    # ==================================================================================================
    # Liste
    # ==================================================================================================

    def _flt(self) -> NoteFilter:
        return NoteFilter(text=self.text, scope=self.scope)

    def _filter(self, *, text: str | None = None, scope: str | None = None) -> None:
        if text is not None:
            self.text = text
        if scope is not None:
            self.scope = scope
        self._render_list(self.ctx.ds.notes.list(self._flt()))

    def _render_list(self, notes: list[NoteOut]) -> None:
        self.list_box.clear()
        with self.list_box:
            if not notes:
                empty_state("📭", "Aucune note." if not self.text else "Aucune note ne correspond.")
            for note in notes:
                self._row(note)

    def _row(self, note: NoteOut) -> None:
        selected = self.note is not None and self.note.id == note.id
        with (
            ui.column()
            .classes("note-row w-full gap-0 px-3 py-2 rounded-lg cursor-pointer")
            .classes("note-row-selected" if selected else "")
            .on("click", lambda n=note: self.select(n.id))
            .mark(f"note-row-{note.id}")
        ):
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.label(note.emoji).classes("text-xl")
                ui.label(note.title).classes("font-semibold flex-1 truncate")
                if note.pinned:
                    ui.label("📌").classes("text-sm").tooltip("Épinglée")
                share = ownership_emoji(note, self.ctx)
                if share:
                    ui.label(share).classes("text-sm").tooltip(ownership_text(note, self.ctx))
            text = snippet(note.notes)
            with ui.row().classes("w-full items-center gap-2 no-wrap text-xs text-gray-500"):
                ui.label(fmt.ago(note.updated_at)).classes("shrink-0")
                if text:
                    ui.label(text).classes("truncate")

    # ==================================================================================================
    # Note ouverte
    # ==================================================================================================

    def select(self, note_id: int) -> None:
        """Ouvre une note (liste, lien interne, ``?note=``)."""
        self._save_text()
        note = self.ctx.call(self.ctx.ds.notes.get, note_id)
        if note is None:
            return
        self.note = note
        self.last_edit = 0.0
        self._render_view()
        self._render_list(self.ctx.ds.notes.list(self._flt()))
        self._set_url(f"/notes?note={note.id}")

    def new(self) -> None:
        """Nouvelle note : créée tout de suite (« Sans titre »), titre sélectionné pour être tapé."""
        self._save_text()
        note = self.ctx.call(self.ctx.ds.notes.create, NoteCreate(title="Sans titre"))
        if note is None:
            return
        self.note = note
        self.last_edit = 0.0
        self._render_view(focus_title=True)
        self._render_list(self.ctx.ds.notes.list(self._flt()))
        self.ctx.refresh(light=True)
        self._set_url(f"/notes?note={note.id}")

    def _set_url(self, path: str) -> None:
        """Adresse de la page sans la recharger (le bouton cliqué a pu disparaître : contexte = la page)."""
        with self.root:
            ui.navigate.history.replace(path)

    def _close(self) -> None:
        """« ← Notes » (téléphone) : retour à la liste."""
        self._save_text()
        self.note = None
        self._render_view()
        self._render_list(self.ctx.ds.notes.list(self._flt()))
        self._set_url("/notes")

    def _render_view(self, focus_title: bool = False) -> None:
        self.view_box.clear()
        self.editor = None
        self.ref_links = None
        if self.note is not None:
            self.root.classes(add="has-note")
        else:
            self.root.classes(remove="has-note")
        with self.view_box:
            note = self.note
            if note is None:
                empty_state("📝", "Choisissez une note à gauche, ou créez-en une avec « ➕ Nouvelle ».")
                return
            self.stale = ui.row().classes("notes-stale w-full items-center gap-2 rounded-lg px-3 py-2")
            self.stale.set_visibility(False)
            with self.stale:
                ui.label("✏️ Cette note a été modifiée ailleurs.").classes("text-sm flex-1")
                ui.button("↻ Recharger", on_click=self._reload).props("flat dense no-caps").mark(
                    "notes-reload"
                )
            self._header(note, focus_title)
            if note.can_edit:
                # Téléphone : repliés derrière le bouton « Projet, tags, partage » (texte en haut).
                with ui.column().classes("note-details w-full gap-3") as self.details:
                    self._details(note)
            else:
                self._read_only_details(note)
            self._text(note)
            self._backlinks(note)
            self._footer(note)

    def _header(self, note: NoteOut, focus_title: bool) -> None:
        with ui.row().classes("w-full items-center gap-1 no-wrap"):
            ui.button(icon="arrow_back", on_click=self._close).props("flat round dense").classes(
                "notes-back"
            ).tooltip("Retour à la liste").mark("notes-back")
            if note.can_edit:
                emoji_button(self.ctx, note.emoji, lambda e: self._save(emoji=e)).mark("note-emoji")
                title = (
                    ui.input(value=note.title)
                    .props("borderless dense")
                    .classes("note-title flex-1 text-2xl font-bold")
                    .mark("note-title")
                )

                def save_title() -> None:
                    value = (title.value or "").strip()
                    if not value:
                        title.set_value(self.note.title)
                    elif value != self.note.title:
                        self._save(title=value, list_changed=True)

                title.on("blur", save_title)
                title.on("keydown.enter.prevent", lambda: title.run_method("blur"))
                if focus_title:
                    title.run_method("select")
            else:
                ui.label(note.emoji).classes("text-3xl")
                ui.label(note.title).classes("text-2xl font-bold flex-1 truncate").mark("note-title")
            if note.can_edit:
                ui.button(
                    icon="tune", on_click=lambda: self.details.classes(toggle="note-details-open")
                ).props("flat round dense").classes("notes-details-toggle").tooltip(
                    "Projet, tags, partage"
                ).mark("note-details-toggle")
            self._pin_button(note)
            self._copy_button(note)
            if note.can_delete:
                ui.button(icon="delete_outline", on_click=self._delete).props("flat round dense").tooltip(
                    "Supprimer la note (Ctrl+Z pour annuler)"
                ).mark("note-delete")

    def _pin_button(self, note: NoteOut) -> None:
        button = ui.button(icon="push_pin", on_click=lambda: self._pin(not self.note.pinned))
        button.props(f"flat round dense {'color=primary' if note.pinned else 'color=grey-6'}")
        button.tooltip("Désépingler" if note.pinned else "Épingler en haut de ma liste").mark("note-pin")

    def _copy_button(self, note: NoteOut) -> None:
        copy_link_button(self.ctx, "note", note.id, mark="note-copy-link")

    def _details(self, note: NoteOut) -> None:
        label_selects(
            self.ctx,
            note,
            on_project=lambda value: self._save(project_id=value),
            on_tags=self._tags_changed,
        )
        if note.owner_id != self.ctx.user.id:
            return
        people = len(note.shares)
        caption = ("📢 Publique" if note.is_public else "🔒 Privée") + (
            f" · partagée avec {people} personne{'s' if people > 1 else ''}" if people else ""
        )
        with ui.expansion("👥 Partage", caption=caption).classes("w-full note-sharing").mark("note-sharing"):
            public_switch(
                "📢 Publique — visible (en lecture seule) par tous les comptes",
                note.is_public,
                lambda value: self._save(is_public=value, rebuild=True, list_changed=True),
            ).mark("note-public")
            share_editor(self.ctx, note.shares, self._share)

    def _read_only_details(self, note: NoteOut) -> None:
        with ui.row().classes("w-full items-center gap-1.5"):
            ui.label(f"👁️ Lecture seule · {ownership_text(note, self.ctx)}").classes(
                "text-sm text-gray-500"
            ).mark("note-read-only")
            if note.project:
                ui.label(f"{note.project.emoji} {note.project.name}").classes("chip")
            for tag in note.tags:
                tag_chip(tag.name, tag.color)

    def _text(self, note: NoteOut) -> None:
        editable = note.can_edit
        with ui.column().classes("w-full gap-1") as box:
            if editable:
                writing_zone(box)  # téléphone : clavier sorti, seuls le texte et la barre restent à l'écran
            self.editor = MarkdownEditor(
                note.notes,
                placeholder="Écrire ici… - liste, 1. numérotée, - [ ] case à cocher, # titre, "
                "[[ lien vers une note / tâche / événement",
                on_open_link=self._open_link,
                on_ref_request=(lambda: self.ref_links.pick()) if editable else None,
                readonly=not editable,
                sort_checks=True,
            )
            self.editor.classes("note-text w-full").mark("note-text")
        if editable:
            with box:
                markdown_toolbar(self.editor, on_ref=lambda: self.ref_links.pick()).move(target_index=0)
        self.ref_links = RefLinks(self.ctx, self.editor, exclude=f"note:{note.id}")
        if editable:
            self.editor.on("update:value", self._typed)
            self.editor.on("update:value", self._save_text, throttle=1.5, leading_events=False)
            self.editor.on("blur", self._left_text)

    def _backlinks(self, note: NoteOut) -> None:
        found = self.ctx.call(self.ctx.ds.notes.backlinks, f"note:{note.id}") or []
        if not found:
            return
        with ui.row().classes("w-full items-center gap-1.5").mark("note-backlinks"):
            ui.label("🔗 Cité dans").classes("text-sm text-gray-500 mr-1")
            for ref in found:
                ui.button(f"{ref.emoji} {ref.title}", on_click=lambda r=ref.ref: self._open_ref(r)).props(
                    "flat dense no-caps size=sm"
                ).classes("chip").mark(f"backlink-{ref.kind}-{ref.id}")

    def _footer(self, note: NoteOut) -> None:
        with ui.row().classes("w-full items-center gap-3 text-xs text-gray-500 pb-16"):
            ui.label(f"Créée le {fmt.local_datetime(note.created_at)}")
            ui.label(f"Modifiée le {fmt.local_datetime(note.updated_at)}").mark("note-updated")
            if note.owner_id != self.ctx.user.id:
                ui.label(f"👤 Appartient à {self.ctx.user_names().get(note.owner_id, '?')}")

    # ==================================================================================================
    # Enregistrement
    # ==================================================================================================

    def _save(self, *, rebuild: bool = False, list_changed: bool = False, **fields) -> bool:
        if self.note is None:
            return False
        updated = self.ctx.call(self.ctx.ds.notes.update, self.note.id, NotePatch(**fields))
        if updated is None:
            self._reload()
            return False
        self.note = updated
        self.ctx.refresh(light=True)
        if rebuild:
            self._render_view()
        if list_changed or rebuild or fields.keys() & {"emoji", "title"}:
            self._render_list(self.ctx.ds.notes.list(self._flt()))
        return True

    def _typed(self) -> None:
        self.last_edit = time.monotonic()
        if self.ref_links is not None and self.editor is not None:
            self.ref_links.update(self.editor.value or "")

    def _left_text(self) -> None:
        self._save_text()
        self.last_edit = 0.0  # plus en train de taper : une modification d'ailleurs peut s'afficher

    def _save_text(self) -> None:
        if self.note is None or self.editor is None or not self.note.can_edit:
            return
        text = self.editor.value or ""
        if text != self.note.notes:
            self._save(notes=text, list_changed=True)

    def _tags_changed(self, values: list) -> None:
        ids, created = tag_ids_from(self.ctx, values)
        if sorted(ids) != sorted(t.id for t in self.note.tags) or created:
            self._save(tag_ids=ids, rebuild=created)

    def _share(self, shares: list[ShareSpec]) -> None:
        updated = self.ctx.call(self.ctx.ds.notes.set_shares, self.note.id, shares)
        if updated is not None:
            self.note = updated
            self.ctx.refresh(light=True)
            self._render_view()
            self._render_list(self.ctx.ds.notes.list(self._flt()))

    def _pin(self, pinned: bool) -> None:
        updated = self.ctx.call(self.ctx.ds.notes.set_pinned, self.note.id, pinned)
        if updated is not None:
            self.note = updated
            self.ctx.refresh(light=True)
            self._render_view()
            self._render_list(self.ctx.ds.notes.list(self._flt()))

    def _delete(self) -> None:
        title = self.note.title
        if self.ctx.attempt(self.ctx.ds.notes.delete, self.note.id):
            with self.root:
                ui.notify(f"🗑️ Note « {title} » supprimée — Ctrl+Z pour annuler", position="top")
            self.note = None
            self.ctx.refresh(light=True)
            self._render_view()
            self._render_list(self.ctx.ds.notes.list(self._flt()))
            self._set_url("/notes")

    # ==================================================================================================
    # Liens, temps réel
    # ==================================================================================================

    def _open_link(self, target: str, kind: str) -> None:
        if kind == "ref" or as_ref(target) is not None:
            self._open_ref(target)
            return
        link_kind = LinkKind.URL if kind == "url" else rules.detect_link_kind(target)
        self.ctx.call(open_link, link_kind, target, self.ctx.ds)

    def _open_ref(self, target: str) -> None:
        self._save_text()
        open_ref(self.ctx, target)

    def _reload(self) -> None:
        """Relit la note ouverte (bandeau « modifiée ailleurs », échec d'un enregistrement)."""
        if self.note is None:
            return
        try:
            self.note = self.ctx.ds.notes.get(self.note.id)
        except OrganizerError:
            self.note = None
        self.last_edit = 0.0
        self._render_view()

    def _on_refresh(self) -> None:
        """Après Ctrl+Z, une modification d'un autre écran… : liste relue, note ouverte mise à jour."""
        self._render_list(self.ctx.ds.notes.list(self._flt()))
        if self.note is None:
            return
        try:
            fresh = self.ctx.ds.notes.get(self.note.id)
        except OrganizerError:
            self.note = None  # supprimée, ou plus visible
            self._render_view()
            return
        if fresh == self.note:
            if self.ref_links is not None:
                self.ref_links.reload()  # un élément cité a pu être renommé
            return
        if time.monotonic() - self.last_edit < TYPING_SECONDS and fresh.notes != (self.editor.value or ""):
            self.stale.set_visibility(True)  # on tape : pas de texte remplacé sous les doigts
            return
        self.note = fresh
        self._render_view()
