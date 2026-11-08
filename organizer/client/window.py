"""Code exécuté **dans le sous-processus de la fenêtre native** (pywebview), au démarrage de la fenêtre
(``webview.start(func=setup_window)``, via ``app.native.start_args``).

- Fermer la fenêtre la **cache** : le client continue en arrière-plan (rappels, raccourcis) ; le processus
  principal en est informé (commande ``hidden``) pour l'indiquer à l'utilisateur.
- Méthodes ajoutées à la fenêtre, appelées depuis le processus principal par la file de commandes de
  NiceGUI : ``organizer_present(jeton)`` (afficher et mettre au premier plan), ``organizer_quit()``
  (fermer pour de bon). Elles renvoient None : une valeur serait prise pour une réponse par NiceGUI.
"""

from __future__ import annotations

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
