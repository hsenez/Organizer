"""Code exécuté **dans le sous-processus de la fenêtre native** (pywebview), au démarrage de la fenêtre
(``webview.start(func=setup_window)``, via ``app.native.start_args``).

- Fermer la fenêtre la **cache** : le client continue en arrière-plan (rappels, raccourcis) ; le processus
  principal en est informé (commande ``hidden``) pour l'indiquer à l'utilisateur.
- Méthodes ajoutées à la fenêtre, appelées depuis le processus principal par la file de commandes de
  NiceGUI : ``organizer_present(jeton)`` (afficher et mettre au premier plan), ``organizer_quit()``
  (fermer pour de bon). Elles renvoient None : une valeur serait prise pour une réponse par NiceGUI.
- macOS (``macshell``) : nom « Organizer » dans le Dock, ⌘Q quitte, clic sur le Dock réaffiche,
  raccourcis globaux (API Carbon).
- Fichiers glissés depuis le système (Linux, GTK) : WebKitGTK ne donne à la page ni leur contenu ni leur
  adresse (``dataTransfer.files`` vide, adresses ``file://`` masquées). GTK, lui, les reçoit (signal
  ``drag-data-received``) : on les transmet à la page (``window.organizerNativeDrop``, voir
  ``organizer/ui/components/file_drop.js``), et le client lit les fichiers sur le poste.
"""

from __future__ import annotations

import json
import logging
import multiprocessing
import os
import sys
import threading

from organizer.client import instance

log = logging.getLogger("organizer.client")

QUIT = threading.Event()
SHELL = None  # raccourcis globaux, zone de notification / Dock (``winshell.Shell``, ``macshell.Shell``)
DEFAULT_KEYS = {"show": "Ctrl+Alt+O", "new_task": "Ctrl+Alt+N"}


def _parent_alive() -> bool:
    parent = multiprocessing.parent_process()
    return parent is None or parent.is_alive()


def _tell_parent(action: str) -> None:
    port, secret = os.environ.get(instance.ENV_PORT), os.environ.get(instance.ENV_SECRET)
    if port and secret:
        threading.Thread(target=instance.send, args=(int(port), secret, action), daemon=True).start()


def _raise_native(window, token: str | None) -> None:
    """Premier plan selon la plateforme (sous Wayland, il faut le jeton d'activation du lanceur)."""
    native = getattr(window, "native", None)
    try:
        from gi.repository import GLib

        def present() -> bool:
            if token:
                native.set_startup_id(token)
            native.present()
            return False

        GLib.idle_add(present)
    except ImportError:
        if (
            sys.platform == "win32"
        ):  # appels Windows directs (Form.Activate hors du fil de l'interface : refusé)
            from organizer.client import winshell

            winshell.bring_to_front(SHELL.hwnd if SHELL is not None else 0)


def file_uris(uris: list[str] | None, text: str | None = None) -> list[str]:
    """Adresses ``file://`` d'un glisser-déposer GTK (liste d'adresses, ou texte « une par ligne »)."""
    items = list(uris or []) or (text or "").splitlines()
    return [item.strip() for item in items if item.strip().startswith("file://")]


def _forward_dropped_files(window) -> None:
    """Relaie à la page les adresses des fichiers glissés sur la fenêtre (GTK seulement)."""
    try:
        from gi.repository import GLib
        from webview.platforms.gtk import BrowserView
    except ImportError:  # Windows : WebView2 donne les fichiers à la page
        return

    def on_data(widget, _context, _x, _y, data, _info, _time) -> bool:
        uris = file_uris(data.get_uris(), data.get_text())
        if uris:
            code = f"window.organizerNativeDrop && window.organizerNativeDrop({json.dumps(uris)})"
            if hasattr(widget, "evaluate_javascript"):  # WebKitGTK ≥ 2.40
                widget.evaluate_javascript(code, -1, None, None, None, None, None)
            else:
                widget.run_javascript(code, None, None, None)
        return False  # WebKit poursuit son propre traitement (événements dragover / drop de la page)

    def connect(tries: int = 50) -> bool:
        view = BrowserView.instances.get(window.uid)
        if view is None:
            if tries > 0:
                GLib.timeout_add(200, connect, tries - 1)
            return False
        view.webview.connect("drag-data-received", on_data)
        return False

    GLib.idle_add(connect)


def setup_window() -> None:
    import webview

    window = webview.windows[0]

    def on_closing() -> bool:
        if QUIT.is_set() or not _parent_alive():
            return True
        window.hide()
        _tell_parent("hidden")
        return False  # annule la fermeture

    def organizer_present(token: str | None = None) -> None:
        window.show()
        window.restore()
        _raise_native(window, token)

    def organizer_quit() -> None:
        QUIT.set()
        if SHELL is not None:
            SHELL.stop()
        window.destroy()

    window.events.closing += on_closing
    window.organizer_present = organizer_present
    window.organizer_quit = organizer_quit
    _forward_dropped_files(window)
    if sys.platform == "win32":
        _start_windows_shell(organizer_present)
    elif sys.platform == "darwin":
        _start_macos_shell(organizer_present)


def _shortcut_keys() -> dict[str, str]:
    """Raccourcis globaux choisis à l'installation (``client.json``) ; une valeur vide en retire un."""
    from organizer.client import system
    from organizer.client.config import ConfigStore

    keys = dict(DEFAULT_KEYS)
    try:
        keys.update(ConfigStore(system.config_dir()).load().shortcuts)
    except Exception:
        log.exception("Raccourcis non lus")
    return {name: keys[name] for name in ("show", "new_task") if keys.get(name)}


def _start_macos_shell(present) -> None:
    """Raccourcis globaux, ⌘Q et clic sur le Dock (macOS, voir ``macshell``)."""
    global SHELL
    try:
        from PyObjCTools import AppHelper

        from organizer.client import macshell
    except ImportError:
        log.exception("Intégration macOS indisponible")
        return

    def new_task() -> None:
        present()
        _tell_parent("new-task")

    SHELL = macshell.Shell(
        _shortcut_keys(), {"show": present, "new_task": new_task}, on_quit=QUIT.set, on_reopen=present
    )
    # Fil principal (boucle Cocoa) : exécuté une fois la fenêtre créée et la boucle lancée.
    AppHelper.callAfter(SHELL.start)


def _start_windows_shell(present) -> None:
    """Raccourcis clavier globaux et icône de la zone de notification (Windows, voir ``winshell``)."""
    global SHELL
    from organizer import ASSETS_DIR
    from organizer.client import winshell

    def new_task() -> None:
        present()  # tout de suite, tant que ce processus a le droit de passer au premier plan
        _tell_parent("new-task")

    SHELL = winshell.Shell(
        _shortcut_keys(),
        {"show": present, "new_task": new_task, "quit": lambda: _tell_parent("quit")},
        ASSETS_DIR / "organizer.ico",
    )
    try:
        SHELL.start()
    except Exception:  # jamais bloquant pour la fenêtre
        log.exception("Intégration Windows indisponible")
