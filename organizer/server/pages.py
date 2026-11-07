"""Pages web de l'étape 2 : connexion, création du premier compte, accueil provisoire.

Les vraies pages de l'application (accueil, liste, kanbans…) arrivent à l'étape 3 dans ``organizer/ui``.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from nicegui import app, ui

from organizer.core.enums import DueBucket
from organizer.core.errors import OrganizerError
from organizer.core.schemas import TaskFilter
from organizer.server.api.auth import check_credentials
from organizer.server.security import client_ip, describe_user_agent, request_auth
from organizer.server.state import AppState
from organizer.server.web_auth import safe_next

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


def home_page(request: Request):
    redirect = guard(request)
    if redirect is not None:
        return redirect
    auth = request_auth(request)
    user = auth.user
    sv = _state().services_for(user)
    ui.colors(primary=PRIMARY)

    with ui.header().classes(
        "items-center justify-between bg-white dark:bg-slate-900 text-gray-800 dark:text-gray-100 shadow-sm"
    ):
        ui.label("📋 Organizer").classes("text-xl font-bold")
        with ui.row().classes("items-center gap-2"):
            ui.label(f"{'👑 ' if user.is_admin else ''}{user.display_name}").classes("text-sm")
            ui.button("Déconnexion", icon="logout", on_click=lambda: ui.navigate.to("/auth/logout")).props(
                "flat dense no-caps"
            )

    open_tasks = [t for t in sv.tasks.list(TaskFilter(include_subtasks=True)) if not t.status.is_closed]
    overdue = sv.tasks.list(TaskFilter(due=[DueBucket.OVERDUE], include_subtasks=True))
    reminders = sv.tasks.reminders_due()

    with ui.column().classes("w-full max-w-3xl mx-auto p-4 gap-4"):
        ui.label(f"Bonjour {user.display_name} 👋").classes("text-2xl font-semibold")
        with ui.row().classes("w-full gap-4"):
            for emoji, label, value, tip in (
                ("📌", "Tâches ouvertes", len(open_tasks), "Tâches ni finies ni annulées"),
                ("⚠️", "En retard", len([t for t in overdue if not t.status.is_closed]), "Échéance dépassée"),
                ("🔔", "Rappels", len(reminders), "Suivis dont la date de rappel est atteinte"),
            ):
                with ui.card().classes("flex-1 min-w-[140px] items-center rounded-xl").tooltip(tip):
                    ui.label(emoji).classes("text-3xl")
                    ui.label(str(value)).classes("text-3xl font-bold")
                    ui.label(label).classes("text-sm text-gray-500")
        with ui.card().classes("w-full rounded-xl bg-amber-50 dark:bg-amber-950"):
            ui.label("🚧 Interface en construction").classes("text-lg font-semibold")
            ui.markdown(
                "Le serveur, la connexion et l'API sont en place (**étape 2**). L'interface complète — "
                "accueil, liste, kanbans, matrice, éditeur — arrive à l'**étape 3**.\n\n"
                "En attendant, l'API est documentée et testable ici : [📖 /docs](/docs)."
            )
        with ui.expansion("💻 Appareils connectés", icon="devices").classes("w-full"):
            for session in _state().auth.list_sessions(user.id, current_id=auth.session.id):
                ui.label(
                    f"{'🟢 ' if session.current else ''}{session.label or session.kind} — "
                    f"{'jeton client bureau' if session.kind == 'api' else 'navigateur'}, "
                    f"vu le {session.last_seen_at:%d/%m à %H:%M} (UTC)"
                ).classes("text-sm")
    return None


def register_pages() -> None:
    """Enregistre les pages auprès de NiceGUI (appelé par ``organizer.server.app.build``)."""
    common = {"favicon": "📋", "dark": None}
    ui.page("/login", title="Connexion · Organizer", **common)(login_page)
    ui.page("/setup", title="Bienvenue · Organizer", **common)(setup_page)
    ui.page("/", title="Organizer", **common)(home_page)
