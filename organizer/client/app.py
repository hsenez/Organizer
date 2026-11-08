"""Client bureau : la même interface que le site, servie **localement** (127.0.0.1) et affichée dans une
fenêtre native (pywebview), branchée sur l'API REST du serveur.

- ``/connect`` : adresse du serveur + identifiant + mot de passe → jeton API enregistré (jamais le mot de
  passe) ; reconnexion automatique aux lancements suivants.
- Les pages de l'application (``organizer.ui.pages``) reçoivent un ``UiContext`` sur ``RemoteDataSource``.
- **Verrou de la fenêtre** : le serveur local n'accepte que la fenêtre lancée (secret à usage par lancement,
  passé dans l'URL de départ puis gardé en cookie) ; un autre programme ou utilisateur du poste ne peut pas
  utiliser la session.
- 🔔 Notifications système des rappels (``notifications.ReminderNotifier``).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import multiprocessing
import os
import platform
import secrets
import socket
import sys
from collections.abc import Callable

import httpx
from fastapi import Request
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from nicegui import app, ui
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from organizer.client import system
from organizer.client.api import ApiClient
from organizer.client.config import ClientConfig, ConfigStore, normalize_server_url
from organizer.client.notifications import NotifiedLog, ReminderNotifier, make_sender
from organizer.client.remote import RemoteAccount, RemoteDataSource, RemoteTasks
from organizer.core.errors import InvalidOperation, NotAuthenticated, OrganizerError, ServerUnreachable
from organizer.core.schemas import LoginOut, TaskOut, UserOut
from organizer.ui.auth_shell import auth_shell
from organizer.ui.context import UiContext
from organizer.ui.pages import register_app_pages

log = logging.getLogger("organizer.client")

WINDOW_COOKIE = "organizer_window"
ENV_SECRET = "ORGANIZER_CLIENT_LAUNCH"
ENV_PORT = "ORGANIZER_CLIENT_PORT"


class _SetupStatus(BaseModel):
    needs_setup: bool


def device_name() -> str:
    """Nom de l'appareil affiché dans Réglages → 💻 Appareils."""
    return f"Client bureau · {platform.node() or 'poste'} ({platform.system()})"


class LaunchGuard(BaseHTTPMiddleware):
    """N'accepte que les requêtes de la fenêtre lancée par ce processus (voir la docstring du module)."""

    def __init__(self, app, secret: str) -> None:
        super().__init__(app)
        self.secret = secret

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/_nicegui"):  # ressources statiques et WebSocket
            return await call_next(request)
        key = request.query_params.get("launch")
        if key and secrets.compare_digest(key, self.secret):
            response = RedirectResponse(request.url.path or "/", status_code=303)
            response.set_cookie(WINDOW_COOKIE, self.secret, httponly=True, samesite="strict")
            return response
        if secrets.compare_digest(request.cookies.get(WINDOW_COOKIE, ""), self.secret):
            return await call_next(request)
        return PlainTextResponse("🔒 Accès réservé à la fenêtre Organizer de ce poste.", status_code=403)


class DesktopClient:
    """État du client bureau (un par processus) : configuration, connexion à l'API, notifications.

    ``http_factory`` (tests) : fabrique le client httpx d'une adresse de serveur.
    """

    def __init__(
        self,
        store: ConfigStore,
        *,
        http_factory: Callable[[str], httpx.Client] | None = None,
        launch_secret: str | None = None,
        port: int | None = None,
    ) -> None:
        self.store = store
        self.config = store.load()
        self.http_factory = http_factory
        self.launch_secret = launch_secret
        self.port = port
        self._api: ApiClient | None = None

    # --- connexion ---

    def new_api(self, server: str, token: str | None = None) -> ApiClient:
        http = self.http_factory(server) if self.http_factory else None
        return ApiClient(server, token, http=http)

    @property
    def api(self) -> ApiClient | None:
        """Client de l'API du serveur configuré, ou None si ce poste n'est pas connecté."""
        if not (self.config.server and self.config.token):
            return None
        if self._api is None or (self._api.base_url, self._api.token) != (
            self.config.server,
            self.config.token,
        ):
            self._api = self.new_api(self.config.server, self.config.token)
        return self._api

    def login(self, server_text: str, username: str, password: str) -> UserOut:
        """Se connecte au serveur et enregistre le jeton ; lève ``ValueError`` / ``OrganizerError``."""
        server = normalize_server_url(server_text)
        if not username.strip() or not password:
            raise InvalidOperation("Indiquez l'identifiant et le mot de passe.")
        api = self.new_api(server)
        if api.call("GET", "/setup", _SetupStatus, auth=False).needs_setup:
            raise InvalidOperation(
                f"Ce serveur n'a encore aucun compte : ouvrez {server}/setup dans un navigateur pour créer "
                "le compte administrateur."
            )
        body = {"username": username.strip(), "password": password, "device_name": device_name()}
        result = api.call("POST", "/auth/login", LoginOut, json=body, auth=False)
        self.config = ClientConfig(server=server, username=username.strip(), token=result.token)
        self.store.save(self.config)
        return result.user

    def forget_token(self) -> None:
        self.config.token = None
        self.store.save(self.config)

    def logout(self) -> None:
        """Déconnecte ce poste (le jeton est révoqué sur le serveur s'il est joignable)."""
        api = self.api
        if api is not None:
            with contextlib.suppress(OrganizerError):
                api.call("POST", "/auth/logout")
        self.forget_token()
        ui.navigate.to("/connect")

    # --- pages ---

    def context(self, request: Request) -> UiContext | Response:
        """Fabrique de contexte des pages de l'application (comme ``server_context`` côté serveur)."""
        api = self.api
        if api is None:
            return RedirectResponse("/connect", status_code=303)
        try:
            user = RemoteAccount(api).me()
        except NotAuthenticated:
            self.forget_token()
            return RedirectResponse("/connect?expired=1", status_code=303)
        except ServerUnreachable:
            return RedirectResponse("/connect?offline=1", status_code=303)
        ctx = UiContext(RemoteDataSource(api, user), logout=self.logout)
        ctx.extra_settings["connection"] = ("🔌 Connexion", self.connection_settings)
        return ctx

    def connect_page(self, request: Request) -> None:
        params = request.query_params
        with auth_shell("Connectez ce poste à votre serveur Organizer"):
            if params.get("offline"):
                ui.label(
                    f"🔌 Le serveur {self.config.server} ne répond pas. Vérifiez qu'il est démarré et que ce "
                    "poste est sur le même réseau."
                ).classes("text-sm text-amber-700")
                ui.button("🔄 Réessayer", on_click=lambda: ui.navigate.to("/")).props(
                    "outline no-caps"
                ).classes("w-full").mark("connect-retry")
            elif params.get("expired"):
                ui.label("⏱️ La connexion a expiré ou a été révoquée : reconnectez-vous.").classes(
                    "text-sm text-amber-700"
                )
            server = (
                ui.input(
                    "🖧 Adresse du serveur",
                    value=self.config.server,
                    placeholder="raspberrypi.local ou 192.168.1.20",
                )
                .props("outlined autofocus")
                .classes("w-full")
                .mark("connect-server")
            )
            username = (
                ui.input("👤 Identifiant", value=self.config.username)
                .props("outlined autocomplete=username")
                .classes("w-full")
                .mark("connect-username")
            )
            password = (
                ui.input("🔑 Mot de passe", password=True, password_toggle_button=True)
                .props("outlined autocomplete=current-password")
                .classes("w-full")
                .mark("connect-password")
            )
            error = ui.label().classes("w-full text-sm text-red-600").mark("connect-error")
            error.visible = False

            def submit() -> None:
                try:
                    self.login(server.value or "", username.value or "", password.value or "")
                except (ValueError, OrganizerError) as exc:
                    error.set_text(f"❌ {getattr(exc, 'message', None) or exc}")
                    error.visible = True
                    password.set_value("")
                    return
                ui.navigate.to("/")

            server.on("keydown.enter", lambda: username.run_method("focus"))
            username.on("keydown.enter", lambda: password.run_method("focus"))
            password.on("keydown.enter", submit)
            ui.button("Se connecter", on_click=submit).props("unelevated size=lg").classes(
                "w-full rounded-lg"
            ).mark("connect-submit")
            ui.label(
                "Seul un jeton de connexion est conservé sur ce poste (pas le mot de passe) ; vous pouvez le "
                "révoquer dans Réglages → 💻 Appareils."
            ).classes("text-xs text-gray-500 text-center w-full")

    def connection_settings(self, ctx: UiContext) -> None:
        """Onglet de réglages « 🔌 Connexion » (client bureau)."""
        with ui.card().classes("w-full gap-3"):
            ui.label("🔌 Connexion au serveur").classes("text-lg font-semibold")
            with ui.column().classes("gap-1 text-sm"):
                ui.label(f"🖧 Serveur : {self.config.server}").mark("connection-server")
                ui.label(f"👤 Compte : {ctx.user.display_name} ({self.config.username})")
                ui.label(f"🖥️ Cet appareil : {device_name()}")
                ui.label(f"📂 Configuration : {self.store.path}").classes("text-gray-500")
            with ui.row().classes("gap-2"):
                ui.button(
                    "🌐 Ouvrir dans le navigateur", on_click=lambda: system.open_url(self.config.server)
                ).props("outline no-caps")
                ui.button("🔔 Tester une notification", on_click=self._test_notification).props(
                    "outline no-caps"
                )
                ui.button("🚪 Se déconnecter / changer de serveur", on_click=self.logout).props(
                    "outline no-caps color=negative"
                ).mark("connection-logout")

    async def _test_notification(self) -> None:
        await make_sender()("🔔 Organizer", "Les notifications fonctionnent sur ce poste.", None)

    def page_error(self, exc: Exception) -> None:
        """Page affichée quand une page échoue (le plus souvent : serveur devenu injoignable)."""
        with auth_shell("Oups…"):
            if isinstance(exc, OrganizerError):
                ui.label(exc.message).classes("text-sm text-amber-700")
            else:
                ui.label(f"😵 Erreur inattendue : {exc}").classes("text-sm text-red-600")
            ui.button("🔄 Réessayer", on_click=lambda: ui.navigate.to("/")).props(
                "unelevated no-caps"
            ).classes("w-full")
            ui.button("🔌 Connexion", on_click=lambda: ui.navigate.to("/connect")).props(
                "flat no-caps"
            ).classes("w-full")

    # --- rappels ---

    def _fetch_reminders(self) -> tuple[bool, list[TaskOut]]:
        api = self.api
        if api is None:
            return False, []
        if not RemoteAccount(api).me().desktop_notifications:
            return False, []
        return True, RemoteTasks(api).reminders_due()

    def _open_task(self, task_id: int) -> None:
        url = f"http://127.0.0.1:{self.port}/?task={task_id}"
        window = app.native.main_window
        if window is not None:
            window.load_url(url)
            window.restore()
            window.show()
        else:
            system.open_url(url)

    def start_notifier(self) -> None:
        notifier = ReminderNotifier(
            self._fetch_reminders,
            NotifiedLog(self.store.directory / "notified.json"),
            make_sender(),
            open_task=self._open_task,
        )
        self._notifier_task = asyncio.get_running_loop().create_task(notifier.run())

    # --- installation ---

    def install(self, *, notifications: bool = True) -> None:
        common = {"favicon": "📋", "dark": None}
        ui.page("/connect", title="Connexion · Organizer", **common)(self.connect_page)
        register_app_pages(self.context)
        app.on_page_exception(self.page_error)
        if self.launch_secret:
            app.add_middleware(LaunchGuard, secret=self.launch_secret)
        if notifications:
            app.on_startup(self.start_notifier)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Organizer — client bureau")
    parser.add_argument(
        "--browser", action="store_true", help="ouvrir dans le navigateur au lieu d'une fenêtre"
    )
    parser.add_argument("--port", type=int, default=None, help="port local (par défaut : un port libre)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s : %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # pas une ligne par requête

    # La fenêtre native tourne dans un sous-processus qui réimporte ce module : le secret et le port sont
    # transmis par l'environnement pour être identiques des deux côtés.
    if multiprocessing.current_process().name == "MainProcess" and ENV_SECRET not in os.environ:
        os.environ[ENV_SECRET] = secrets.token_urlsafe(24)
        os.environ[ENV_PORT] = str(args.port or _free_port())
    secret, port = os.environ[ENV_SECRET], int(os.environ[ENV_PORT])
    start_url = f"http://127.0.0.1:{port}/?launch={secret}"

    client = DesktopClient(ConfigStore(system.config_dir()), launch_secret=secret, port=port)
    client.install()
    native = not args.browser
    if native:
        app.native.window_args["url"] = start_url
        app.native.window_args["min_size"] = (420, 520)
        if sys.platform.startswith("linux") and "PYWEBVIEW_GUI" not in os.environ:
            app.native.start_args["gui"] = "gtk"  # sinon pywebview essaie d'abord Qt (non installé)
    elif multiprocessing.current_process().name == "MainProcess":
        app.on_startup(lambda: system.open_url(start_url))
        print(f"Organizer (client) : {start_url}", flush=True)
    ui.run(
        host="127.0.0.1",
        port=port,
        native=native,
        window_size=(1400, 900) if native else None,
        title="Organizer",
        favicon="📋",
        dark=None,
        language="fr",
        reload=False,
        show=False,
        show_welcome_message=False,
    )
