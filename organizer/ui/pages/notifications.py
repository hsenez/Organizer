"""🔔 Notifications : ce que les autres ont fait qui me concerne (partage, modification, suppression).

Les non lues sont mises en valeur (et comptées dans la bulle de la colonne de gauche) ; un clic ouvre
l'élément et marque la notification comme lue ; « Tout marquer comme lu ».
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import Response
from nicegui import ui

from organizer.core.schemas import NotificationOut
from organizer.ui import format as fmt
from organizer.ui.context import UiContext
from organizer.ui.layout import app_frame, empty_state

KINDS = {
    "share": ("🤝", "a partagé {item} avec vous"),
    "change": ("✏️", "a modifié {item}"),
    "unshare": ("🚫", "ne partage plus {item} avec vous"),
    "delete": ("🗑️", "a supprimé {item}"),
}
ITEM_EMOJI = {"task": "📋", "event": "📅"}


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
    return f"{n.actor_name} {phrase.format(item=f'« {n.title} »')}"


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
        if not n.available:
            return
        if n.item_type == "event":
            self.ctx.editor.open_event(n.item_id)
        else:
            self.ctx.editor.open(n.item_id)

    def _read_all(self) -> None:
        self.ctx.call(self.ctx.ds.notifications.mark_read)
        self.ctx.refresh()
