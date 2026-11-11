"""Indicateur « 🏠 réseau local / 🌍 Internet », dans le coin bas gauche de chaque page, avec une infobulle
qui explique ce que cela veut dire (et donc pourquoi l'application est plus ou moins rapide)."""

from __future__ import annotations

from nicegui import ui

from organizer.ui.context import Connection, UiContext

REFRESH_SECONDS = 3.0  # client bureau : la route peut changer (arrivée à la maison, départ)


def desktop_connection(local: bool, address: str, reason: str = "") -> Connection:
    target = "/settings?tab=connection"
    if local:
        return Connection(
            True,
            f"🏠 Réseau local : ce poste joint directement le serveur ({address}). Rapide (≈ 20 ms par "
            "action). Cliquer pour les réglages de connexion.",
            target,
        )
    why = f" ({reason})" if reason else ""
    return Connection(
        False,
        f"🌍 Par Internet : ce poste passe par l'adresse publique du serveur ({address}){why}, ≈ 0,3 s par "
        "action. À la maison, il bascule tout seul sur le réseau local. Cliquer pour les réglages de "
        "connexion.",
        target,
    )


def web_connection(local: bool, address: str, local_urls: list[str]) -> Connection:
    if local:
        return Connection(
            True, f"🏠 Réseau local : cette page vient directement du serveur ({address}). Rapide."
        )
    faster = f" À la maison, l'adresse {local_urls[0]} est plus rapide." if local_urls else ""
    return Connection(
        False,
        f"🌍 Par Internet : cette page passe par {address} (Cloudflare), un peu plus lente.{faster}",
    )


def connection_badge(ctx: UiContext) -> None:
    if ctx.connection is None:
        return
    get = ctx.connection
    with ui.page_sticky(position="bottom-left", x_offset=14, y_offset=14).classes("app-sticky"):
        badge = ui.button(color=None).props("round dense unelevated").classes("connection-badge")
        badge.mark("connection-badge")
        with badge:
            tip = ui.tooltip().classes("text-sm max-w-xs")
    state: dict = {"current": None}

    def update() -> None:
        current = get()
        if current == state["current"]:
            return
        state["current"] = current
        badge.set_text("🏠" if current.local else "🌍")
        badge.props(f'aria-label="{"Réseau local" if current.local else "Par Internet"}"')
        badge.classes(
            add="connection-local" if current.local else "connection-internet",
            remove="connection-internet" if current.local else "connection-local",
        )
        tip.set_text(current.tooltip)

    def clicked() -> None:
        current = state["current"]
        if current is not None and current.target:
            ui.navigate.to(current.target)

    badge.on_click(clicked)
    update()
    if ctx.connection_live:
        ui.timer(REFRESH_SECONDS, update)
