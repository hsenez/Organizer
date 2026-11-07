"""Pages propres au serveur web : connexion et création du premier compte ; branchement des pages de
l'application (``organizer/ui``) sur la source de données locale."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from nicegui import app, ui

from organizer.core.datasource import LocalDataSource
from organizer.core.errors import OrganizerError
from organizer.core.services.account import AccountService
from organizer.server.api.auth import check_credentials
from organizer.server.security import client_ip, describe_user_agent, request_auth
from organizer.server.state import AppState
from organizer.server.web_auth import safe_next
from organizer.ui.context import UiContext
from organizer.ui.pages import register_app_pages

PRIMARY = "#5c7cfa"


def _state() -> AppState:
    return app.state.organizer


def guard(request: Request) -> RedirectResponse | None:
    """Redirige vers /setup (aucun compte) ou /login (non connecté) ; None si l'accès est autorisé."""
    if _state().users.count() == 0:
        return RedirectResponse("/setup", status_code=303)
    if request_auth(request) is None:
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(f"/login?next={quote(target)}", status_code=303)
    return None


def _auth_shell(subtitle: str):
    """Fond dégradé + carte centrée ; renvoie la colonne où placer le formulaire."""
    ui.colors(primary=PRIMARY)
    ui.query("body").classes(
        "bg-gradient-to-br from-indigo-100 via-white to-sky-100 "
        "dark:from-slate-900 dark:via-slate-800 dark:to-indigo-950"
    )
    with ui.column().classes("w-full min-h-screen items-center justify-center p-4"):
        card = ui.card().classes("w-full max-w-sm p-6 gap-4 rounded-2xl shadow-xl")
        with card:
            with ui.column().classes("w-full items-center gap-1"):
                ui.label("📋").classes("text-5xl")
                ui.label("Organizer").classes("text-2xl font-bold")
                ui.label(subtitle).classes("text-sm text-gray-500 text-center")
            body = ui.column().classes("w-full gap-3")
    return body


def login_page(request: Request, next: str = "/", expired: int = 0):
    state = _state()
    if state.users.count() == 0:
        return RedirectResponse("/setup", status_code=303)
    if request_auth(request) is not None:
        return RedirectResponse(safe_next(next), status_code=303)
    ip = client_ip(request)
    device = describe_user_agent(request.headers.get("user-agent", ""))

    with _auth_shell("Connectez-vous pour retrouver vos tâches"):
        if expired:
            ui.label("⏱️ La connexion a expiré, veuillez réessayer.").classes("text-sm text-amber-700")
        username = (
            ui.input("👤 Identifiant").props("outlined autofocus autocomplete=username").classes("w-full")
        )
        password = (
            ui.input("🔑 Mot de passe", password=True, password_toggle_button=True)
            .props("outlined autocomplete=current-password")
            .classes("w-full")
        )
        remember = ui.checkbox("🍪 Se souvenir de moi", value=True).tooltip(
            f"Reste connecté {state.settings.remember_me_days} jours sur cet appareil"
        )
        error = ui.label().classes("w-full text-sm text-red-600")
        error.visible = False

        def submit() -> None:
            try:
                user = check_credentials(state, ip, username.value, password.value)
            except HTTPException as exc:
                error.set_text(f"❌ {exc.detail}")
                error.visible = True
                password.set_value("")
                return
            ticket = state.tickets.issue(user.id, persistent=remember.value, label=device)
            ui.navigate.to(f"/auth/complete?ticket={ticket}&next={quote(safe_next(next))}")

        username.on("keydown.enter", lambda: password.run_method("focus"))
        password.on("keydown.enter", submit)
        ui.button("Se connecter", on_click=submit).props("unelevated size=lg").classes("w-full rounded-lg")
    return None


def setup_page(request: Request):
    state = _state()
    if state.users.count() > 0:
        return RedirectResponse("/login", status_code=303)
    device = describe_user_agent(request.headers.get("user-agent", ""))

    with _auth_shell("Bienvenue ! Créez le compte administrateur pour commencer."):
        display = ui.input("😀 Votre nom").props("outlined autofocus").classes("w-full")
        username = (
            ui.input("👤 Identifiant de connexion").props("outlined autocomplete=username").classes("w-full")
        )
        password = (
            ui.input("🔑 Mot de passe", password=True, password_toggle_button=True)
            .props("outlined autocomplete=new-password")
            .classes("w-full")
        )
        confirm = (
            ui.input("🔑 Confirmer le mot de passe", password=True)
            .props("outlined autocomplete=new-password")
            .classes("w-full")
        )
        error = ui.label().classes("w-full text-sm text-red-600")
        error.visible = False

        def submit() -> None:
            if password.value != confirm.value:
                error.set_text("❌ Les deux mots de passe ne correspondent pas.")
                error.visible = True
                return
            try:
                user = state.users.create_user(username.value, password.value, display.value)
            except OrganizerError as exc:
                error.set_text(f"❌ {exc.message}")
                error.visible = True
                return
            ticket = state.tickets.issue(user.id, persistent=True, label=device)
            ui.navigate.to(f"/auth/complete?ticket={ticket}&next=/")

        confirm.on("keydown.enter", submit)
        ui.button("🚀 Créer mon compte", on_click=submit).props("unelevated size=lg").classes(
            "w-full rounded-lg"
        )
        ui.label("Ce compte pourra ensuite créer ceux des autres utilisateurs.").classes(
            "text-xs text-gray-500 text-center w-full"
        )
    return None


def server_context(request: Request) -> UiContext | RedirectResponse:
    """Fabrique de contexte des pages de l'application, côté serveur : cookie → LocalDataSource."""
    redirect = guard(request)
    if redirect is not None:
        return redirect
    auth = request_auth(request)
    state = _state()
    services = state.services_for(auth.user)
    account = AccountService(state.users, state.auth, auth.user.id, auth.session.id)
    return UiContext(
        LocalDataSource(services, auth.user, account), logout=lambda: ui.navigate.to("/auth/logout")
    )


def register_pages() -> None:
    """Enregistre les pages auprès de NiceGUI (appelé par ``organizer.server.app.build``)."""
    common = {"favicon": "📋", "dark": None}
    ui.page("/login", title="Connexion · Organizer", **common)(login_page)
    ui.page("/setup", title="Bienvenue · Organizer", **common)(setup_page)
    register_app_pages(server_context)
