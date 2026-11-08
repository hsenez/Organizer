"""Code exécuté **dans le sous-processus de la fenêtre native** (pywebview), au démarrage de la fenêtre
(``webview.start(func=setup_window)``, via ``app.native.start_args``).

- Fermer la fenêtre la **cache** : le client continue en arrière-plan (rappels, raccourcis) ; le processus
  principal en est informé (commande ``hidden``) pour l'indiquer à l'utilisateur.
- Méthodes ajoutées à la fenêtre, appelées depuis le processus principal par la file de commandes de
  NiceGUI : ``organizer_present(jeton)`` (afficher et mettre au premier plan), ``organizer_quit()``
  (fermer pour de bon). Elles renvoient None : une valeur serait prise pour une réponse par NiceGUI.
- Fichiers glissés depuis le système (Linux, GTK) : WebKitGTK ne donne à la page ni leur contenu ni leur
  adresse (``dataTransfer.files`` vide, adresses ``file://`` masquées). GTK, lui, les reçoit (signal
  ``drag-data-received``) : on les transmet à la page (``window.organizerNativeDrop``, voir
  ``organizer/ui/components/file_drop.js``), et le client lit les fichiers sur le poste.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import threading

from organizer.client import instance

QUIT = threading.Event()


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
    except ImportError:  # Windows (WinForms) : la fenêtre a une méthode Activate
        activate = getattr(native, "Activate", None)
        if callable(activate):
            activate()


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
        window.destroy()

    window.events.closing += on_closing
    window.organizer_present = organizer_present
    window.organizer_quit = organizer_quit
    _forward_dropped_files(window)
