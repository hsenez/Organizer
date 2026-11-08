"""Client bureau : la même interface que le site, servie **localement** (127.0.0.1) et affichée dans une
fenêtre native (pywebview), branchée sur l'API REST du serveur.

- ``/connect`` : adresse du serveur + identifiant + mot de passe → jeton API enregistré (jamais le mot de
  passe) ; reconnexion automatique aux lancements suivants.
- Les pages de l'application (``organizer.ui.pages``) reçoivent un ``UiContext`` sur ``RemoteDataSource``.
- **Verrou de la fenêtre** : le serveur local n'accepte que la fenêtre lancée (secret à usage par lancement,
  passé dans l'URL de départ puis gardé en cookie) ; un autre programme ou utilisateur du poste ne peut pas
  utiliser la session.
- 🔔 Notifications système des rappels (``notifications.ReminderNotifier``).
- **Arrière-plan** : fermer la fenêtre la cache (``window.py``) ; une seule instance par utilisateur, que
  les lancements suivants (lanceur, raccourcis clavier globaux) pilotent par ``/_organizer/control/<action>``
  (``instance.py``) : ``show``, ``new-task``, ``quit``.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import logging.handlers
import multiprocessing
import os
import platform
import secrets
import socket
import sys
import time
from collections.abc import Callable
from pathlib import Path

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from nicegui import Client, app, ui
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from organizer import ASSETS_DIR, FAVICON, versioning
from organizer.client import instance, system, window
from organizer.client.api import ApiClient
from organizer.client.config import ClientConfig, ConfigStore, normalize_server_url
from organizer.client.live import EventListener
from organizer.client.notifications import NotifiedLog, ReminderNotifier, make_sender
from organizer.client.remote import RemoteAccount, RemoteDataSource, RemoteTasks
from organizer.core.errors import (
    InvalidOperation,
    NotAuthenticated,
    NotFound,
    OrganizerError,
    ServerUnreachable,
)
from organizer.core.events import ChangeEvent
from organizer.core.schemas import LoginOut, TaskOut, UserOut
from organizer.ui.auth_shell import auth_shell
from organizer.ui.context import UiContext
from organizer.ui.live import LiveRefresh
from organizer.ui.pages import register_app_pages

log = logging.getLogger("organizer.client")

WINDOW_COOKIE = "organizer_window"
ENV_SECRET = instance.ENV_SECRET
ENV_PORT = instance.ENV_PORT
ASSETS = ASSETS_DIR
DEFAULT_SHORTCUTS = {"show": "Ctrl+Alt+O", "new_task": "Ctrl+Alt+N"}


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
        path = request.url.path
        # Ressources statiques et WebSocket ; commandes à distance (elles vérifient leur propre secret).
        if path.startswith("/_nicegui") or path.startswith(instance.CONTROL_PATH):
            return await call_next(request)
        key = request.query_params.get("launch")
        if key and secrets.compare_digest(key, self.secret):
            rest = "&".join(f"{k}={v}" for k, v in request.query_params.items() if k != "launch")
            response = RedirectResponse((path or "/") + (f"?{rest}" if rest else ""), status_code=303)
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
        self._pages: list[tuple[Client, UiContext]] = []  # pages ouvertes (la fenêtre n'en montre qu'une)
        self._version: tuple[float, versioning.VersionCheck | None] = (0.0, None)
        self._hidden_hint_shown = False

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
        origin = secrets.token_hex(8)
        ctx = UiContext(RemoteDataSource(api, user, origin=origin), logout=self.logout)
        LiveRefresh(ctx, ui.context.client, origin)
        ctx.extra_settings["connection"] = ("🔌 Connexion", self.connection_settings)
        ctx.quit = self.quit
        result = self.version_check()
        if result is not None and not result.ok:
            ctx.banner = (versioning.message(result, sys.platform), result.blocking)
        self._pages = [(c, x) for c, x in self._pages if c.id in Client.instances]
        self._pages.append((ui.context.client, ctx))
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

    def version_check(self, max_age: float = 600) -> versioning.VersionCheck | None:
        """Compare ce poste au serveur (résultat gardé ``max_age`` secondes) ; None si on ne sait pas."""
        checked_at, result = self._version
        if result is not None and time.monotonic() - checked_at < max_age:
            return result
        api = self.api
        if api is None:
            return None
        try:
            data = api.call("GET", "/version", dict, auth=False)
            result = versioning.check(
                str(data["version"]), int(data["api"]), installed=versioning.installed_version()
            )
        except NotFound:  # serveur antérieur à la route /version
            result = versioning.check(None, None, installed=versioning.installed_version())
        except (OrganizerError, KeyError, TypeError, ValueError):
            return None
        self._version = (time.monotonic(), result)
        return result

    def connection_settings(self, ctx: UiContext) -> None:
        """Onglet de réglages « 🔌 Connexion » (client bureau)."""
        with ui.card().classes("w-full gap-3"):
            ui.label("🔌 Connexion au serveur").classes("text-lg font-semibold")
            with ui.column().classes("gap-1 text-sm"):
                ui.label(f"🖧 Serveur : {self.config.server}").mark("connection-server")
                ui.label(f"👤 Compte : {ctx.user.display_name} ({self.config.username})")
                ui.label(f"🖥️ Cet appareil : {device_name()}")
                result = self.version_check()
                server_version = result.server if result and result.server else "?"
                installed = result.installed if result and result.installed else None
                running = versioning.__version__ + (f" (installée : {installed})" if installed else "")
                ui.label(f"🏷️ Versions : ce poste {running} · serveur {server_version}").mark(
                    "connection-versions"
                )
                if result is not None and not result.ok:
                    ui.label(versioning.message(result, sys.platform)).classes("text-amber-700")
                ui.label(f"🔄 Mise à jour de ce poste : {versioning.update_command(sys.platform)}").classes(
                    "text-gray-500"
                )
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
        self.show_window()
        self._in_page(lambda ctx: ctx.editor.open(task_id), f"/?task={task_id}")

    # --- fenêtre et commandes à distance ---

    def _window_call(self, method: str, *args) -> bool:
        """Appelle une méthode ajoutée à la fenêtre native par ``window.setup_window`` (file de NiceGUI)."""
        from nicegui.native import native as native_module

        if app.native.main_window is None or native_module.method_queue is None:
            return False
        native_module.method_queue.put((method, args, {}))
        return True

    def _in_page(self, action: Callable[[UiContext], None], fallback_path: str) -> None:
        """Exécute ``action`` dans la page affichée par la fenêtre, sinon y ouvre ``fallback_path``."""
        for client, ctx in reversed(self._pages):
            if client.id in Client.instances and client.has_socket_connection and ctx.editor is not None:
                with client:
                    action(ctx)
                return
        url = f"http://127.0.0.1:{self.port}{fallback_path}"
        if app.native.main_window is not None:
            app.native.main_window.load_url(url)
        else:
            system.open_url(url)

    def show_window(self, activation_token: str | None = None) -> None:
        if not self._window_call("organizer_present", activation_token):
            self._in_page(lambda ctx: ui.run_javascript("window.focus()"), "/")

    def new_task(self, activation_token: str | None = None) -> None:
        self.show_window(activation_token)
        self._in_page(lambda ctx: ctx.editor.open_new(), "/?task=new")

    def quit(self) -> None:
        """Arrête vraiment le client (fenêtre, serveur local, rappels)."""
        if not self._window_call("organizer_quit"):
            app.shutdown()

    async def _window_hidden(self) -> None:
        if self._hidden_hint_shown:
            return
        self._hidden_hint_shown = True
        keys = {**DEFAULT_SHORTCUTS, **self.config.shortcuts}
        await make_sender()(
            "📋 Organizer reste ouvert en arrière-plan",
            f"Rouvrir : {keys['show']} · Nouvelle tâche : {keys['new_task']}\n"
            "Pour quitter : menu du compte → ⏻ Quitter Organizer.",
            None,
        )

    async def control(self, action: str, request: Request) -> Response:
        """Commandes envoyées par un autre lancement (``instance.forward``) ou par la fenêtre."""
        secret = request.headers.get(instance.SECRET_HEADER, "")
        if not self.launch_secret or not secrets.compare_digest(secret, self.launch_secret):
            return PlainTextResponse("Accès refusé.", status_code=403)
        try:
            token = (await request.json()).get("activation_token")
        except ValueError:
            token = None
        log.info("Commande reçue : %s", action)
        if action == "show":
            self.show_window(token)
        elif action == "new-task":
            self.new_task(token)
        elif action == "quit":
            self.quit()
        elif action == "hidden":
            await self._window_hidden()
        elif action != "ping":
            return PlainTextResponse("Commande inconnue.", status_code=404)
        return JSONResponse({"ok": True})

    def start_notifier(self) -> None:
        notifier = ReminderNotifier(
            self._fetch_reminders,
            NotifiedLog(self.store.directory / "notified.json"),
            make_sender(),
            open_task=self._open_task,
        )
        self._notifier_task = asyncio.get_running_loop().create_task(notifier.run())

    # --- installation ---

    def _dispatch_change(self, event: ChangeEvent | None) -> None:
        """Modification reçue du serveur (fil du flux SSE) → pages ouvertes."""
        for _client, ctx in list(self._pages):
            if ctx.live is not None:
                ctx.live.notify(event)

    def start_live(self) -> None:
        self.listener = EventListener(lambda: self.api, self._dispatch_change)
        self.listener.start()

    def install(
        self, *, notifications: bool = True, single_instance: bool = False, live: bool = True
    ) -> None:
        common = {"favicon": FAVICON, "dark": None}
        ui.page("/connect", title="Connexion · Organizer", **common)(self.connect_page)
        register_app_pages(self.context)
        app.on_page_exception(self.page_error)
        app.add_api_route(f"{instance.CONTROL_PATH}/{{action}}", self.control, methods=["POST"])
        if self.launch_secret:
            app.add_middleware(LaunchGuard, secret=self.launch_secret)
        if notifications:
            app.on_startup(self.start_notifier)
        if live:
            app.on_startup(self.start_live)
            app.on_shutdown(lambda: self.listener.stop())
        if single_instance and self.launch_secret and self.port:
            app.on_startup(lambda: instance.write(self.store.directory, self.port, self.launch_secret))
            app.on_shutdown(lambda: instance.remove(self.store.directory))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _setup_logging(directory: Path) -> None:
    handlers: list[logging.Handler] = []
    with contextlib.suppress(OSError):
        directory.mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.handlers.RotatingFileHandler(
                directory / "client.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"
            )
        )
    if sys.stderr is not None:  # pythonw (Windows) : pas de console
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s", handlers=handlers
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # pas une ligne par requête


def _icon(ext: str) -> str | None:
    path = ASSETS / f"organizer.{ext}"
    return str(path) if path.exists() else None


def main(args: argparse.Namespace) -> None:
    """Démarre le client (voir ``launcher.run``, qui analyse la ligne de commande)."""
    is_main = multiprocessing.current_process().name == "MainProcess"
    directory = system.config_dir()
    if is_main:
        _setup_logging(directory)

    # La fenêtre native tourne dans un sous-processus qui réimporte ``run_client.py`` : le secret et le port
    # sont transmis par l'environnement pour être identiques des deux côtés.
    if is_main and ENV_SECRET not in os.environ:
        os.environ[ENV_SECRET] = secrets.token_urlsafe(24)
        os.environ[ENV_PORT] = str(args.port or _free_port())
    secret, port = os.environ[ENV_SECRET], int(os.environ[ENV_PORT])
    start_url = f"http://127.0.0.1:{port}/?launch={secret}" + ("&task=new" if args.new_task else "")

    client = DesktopClient(ConfigStore(directory), launch_secret=secret, port=port)
    client.install(single_instance=True)
    native = not args.browser
    if native:
        app.native.window_args["url"] = start_url
        app.native.window_args["min_size"] = (420, 520)
        app.native.window_args["hidden"] = bool(args.hidden)
        app.native.start_args["func"] = window.setup_window
        if sys.platform.startswith("linux"):
            if "PYWEBVIEW_GUI" not in os.environ:
                app.native.start_args["gui"] = "gtk"  # sinon pywebview essaie d'abord Qt (non installé)
            if _icon("png"):
                app.native.start_args["icon"] = _icon("png")
            if not is_main:
                # Identifiant de l'application sous Wayland (= nom du fichier .desktop) : icône et
                # regroupement corrects dans la barre des tâches.
                with contextlib.suppress(ImportError, ValueError):
                    from gi.repository import GLib

                    GLib.set_prgname("organizer")
                    GLib.set_application_name("Organizer")
    elif is_main and not args.hidden:
        app.on_startup(lambda: system.open_url(start_url))
        print(f"Organizer (client) : {start_url}", flush=True)
    ui.run(
        host="127.0.0.1",
        port=port,
        native=native,
        window_size=(1400, 900) if native else None,
        title="Organizer",
        favicon=(_icon("ico") if sys.platform == "win32" else None) or FAVICON,
        dark=None,
        language="fr",
        reload=False,
        show=False,
        show_welcome_message=False,
    )
