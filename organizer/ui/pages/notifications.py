"""🔔 Notifications : ce que les autres ont fait qui me concerne (partage, modification, suppression).

Les non lues sont mises en valeur (et comptées dans la bulle de la colonne de gauche) ; un clic ouvre
l'élément et marque la notification comme lue ; « Tout marquer comme lu ».

Conflit de nom (un tag / projet public porte le nom de mon tag / projet privé) : boutons « Renommer » et
« Fusionner dans le public ».
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import Response
from nicegui import ui

from organizer.core.schemas import NotificationOut, ProjectPatch, TagPatch
from organizer.ui import format as fmt
from organizer.ui.context import UiContext
from organizer.ui.layout import app_frame, empty_state

KINDS = {
    "share": ("🤝", "a partagé {item} avec vous"),
    "change": ("✏️", "a modifié {item}"),
    "unshare": ("🚫", "ne partage plus {item} avec vous"),
    "delete": ("🗑️", "a supprimé {item}"),
    "conflict": ("⚠️", "a rendu public un {noun} du même nom que votre {noun} privé {item}"),
}
ITEM_EMOJI = {"task": "📋", "event": "📅", "note": "📝", "tag": "🏷️", "project": "📁"}
NOUNS = {"tag": "tag", "project": "projet"}


def page(make_context):
    def notifications_page(request: Request):
        ctx = make_context(request)
        if isinstance(ctx, Response):
            return ctx
        with app_frame(
            ctx,
            "/notifications",
            "Notifications",
            open_task=request.query_params.get("task"),
            open_event=request.query_params.get("event"),
        ):
            NotificationsView(ctx)
        return None

    return notifications_page


def describe(n: NotificationOut) -> str:
    """« Bob a modifié « Plombier » »."""
    _, phrase = KINDS.get(n.kind, KINDS["change"])
    return f"{n.actor_name} {phrase.format(item=f'« {n.title} »', noun=NOUNS.get(n.item_type, ''))}"


class NotificationsView:
    def __init__(self, ctx: UiContext):
        self.ctx = ctx
        with ui.row().classes("w-full items-center gap-2"):
            ui.label("🔔").classes("text-2xl")
            ui.label("Notifications").classes("text-2xl font-bold")
            ui.space()
            self.read_all = (
                ui.button("✔ Tout marquer comme lu", on_click=self._read_all)
                .props("flat no-caps")
                .mark("notifications-read-all")
            )
        ui.label(
            "Ce que les autres ont fait qui vous concerne : partages, modifications, suppressions."
        ).classes("text-sm text-gray-500 -mt-3")
        self.body = ui.refreshable(self._list)
        self.body()
        ctx.on_refresh(self.body.refresh)

    def _list(self) -> None:
        items = self.ctx.ds.notifications.list()
        self.read_all.set_enabled(any(not n.read for n in items))
        if not items:
            empty_state("🔕", "Aucune notification pour l'instant.")
            return
        with ui.column().classes("w-full gap-1"):
            for n in items:
                self._row(n)

    def _row(self, n: NotificationOut) -> None:
        emoji, _ = KINDS.get(n.kind, KINDS["change"])
        css = "notification-row w-full items-center gap-3 no-wrap px-3 py-2 rounded-lg"
        css += " notification-unread" if not n.read else ""
        css += " cursor-pointer" if n.available or not n.read else ""
        with ui.row().classes(css).on("click", lambda n=n: self._open(n)).mark(f"notification-{n.id}"):
            ui.label(emoji).classes("text-xl")
            with ui.column().classes("flex-1 min-w-0 gap-0"):
                ui.label(describe(n)).classes("notification-title truncate w-full")
                detail = f"{ITEM_EMOJI.get(n.item_type, '')} {n.text} · {fmt.ago(n.updated_at)}"
                ui.label(detail).classes("text-xs text-gray-500 truncate w-full")
            if n.kind == "conflict" and n.available:
                noun = NOUNS.get(n.item_type, "")
                # « click.stop » : le clic ne remonte pas à la ligne (qui rafraîchirait la page).
                ui.button(f"✏️ Renommer mon {noun}").on("click.stop", lambda _, n=n: self._rename(n)).props(
                    "flat dense no-caps"
                ).mark(f"notification-rename-{n.id}")
                ui.button("🔀 Fusionner dans le public").on(
                    "click.stop", lambda _, n=n: self._merge(n)
                ).props("flat dense no-caps").tooltip(
                    f"Remplacer partout votre {noun} privé par le public, puis le supprimer"
                ).mark(f"notification-merge-{n.id}")
            if not n.read:
                ui.element("span").classes("notification-dot").tooltip("Non lue")
            elif not n.available:
                ui.label("indisponible").classes("text-xs text-gray-400").tooltip(
                    "L'élément a été supprimé ou ne vous est plus partagé"
                )

    def _open(self, n: NotificationOut) -> None:
        if not n.read:
            self.ctx.call(self.ctx.ds.notifications.mark_read, [n.id])
            self.ctx.refresh()
        if not n.available or n.kind == "conflict":
            return
        if n.item_type == "event":
            self.ctx.editor.open_event(n.item_id)
        elif n.item_type == "note":
            ui.navigate.to(f"/notes?note={n.item_id}")
        else:
            self.ctx.editor.open(n.item_id)

    def _read_all(self) -> None:
        self.ctx.call(self.ctx.ds.notifications.mark_read)
        self.ctx.refresh()

    # --- conflit de nom : renommer, fusionner ---

    def _service(self, n: NotificationOut):
        return self.ctx.ds.projects if n.item_type == "project" else self.ctx.ds.tags

    def _done(self, n: NotificationOut, message: str) -> None:
        self.ctx.call(self.ctx.ds.notifications.mark_read, [n.id])
        ui.notify(message, position="top")
        self.ctx.refresh()

    def _rename(self, n: NotificationOut) -> None:
        noun = NOUNS.get(n.item_type, "")
        with ui.dialog() as dialog, ui.card().classes("w-[440px] max-w-[95vw] gap-3").mark("rename-dialog"):
            ui.label(f"✏️ Renommer votre {noun} privé « {n.title} »").classes("text-lg font-semibold")
            name = ui.input("Nouveau nom", value=f"{n.title} (perso)").props("outlined dense autofocus")
            name.classes("w-full").mark("rename-input")

            def save() -> None:
                value = (name.value or "").strip()
                if not value:
                    return
                patch = ProjectPatch(name=value) if n.item_type == "project" else TagPatch(name=value)
                if self.ctx.call(self._service(n).update, n.item_id, patch) is not None:
                    dialog.close()
                    self._done(n, f"✏️ Renommé en « {value} »")

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Annuler", on_click=dialog.close).props("flat")
                ui.button("Renommer", on_click=save).props("unelevated").mark("rename-save")
        dialog.open()

    def _merge(self, n: NotificationOut) -> None:
        target = self.ctx.call(self.ctx.ds.notifications.conflict_target, n.item_type, n.item_id)
        if target is None:
            ui.notify("Plus de conflit : rien à fusionner.", position="top")
            self.ctx.refresh()
            return
        if self.ctx.call(self._service(n).merge, n.item_id, target) is not None:
            self._done(n, "🔀 Fusionné dans le public (Ctrl+Z pour annuler)")
