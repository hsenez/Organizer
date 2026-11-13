"""Intégration **macOS** du client bureau, exécutée dans le sous-processus de la fenêtre (Cocoa, pywebview).

- Nom « Organizer » dans la barre des menus et le Dock (``rename_app``, avant que pywebview ne crée
  l'application Cocoa) : sinon macOS affiche « Python » (le processus est l'interpréteur du venv).
- ⌘Q (ou « Quitter » dans le Dock) arrête vraiment Organizer ; fermer la fenêtre (bouton rouge, ⌘W) la
  cache seulement, comme sous Linux et Windows.
- Clic sur l'icône du Dock quand la fenêtre est cachée : elle réapparaît.
- **Raccourcis clavier globaux** : API Carbon ``RegisterEventHotKey`` (par ``ctypes``), la seule qui ne
  demande aucune autorisation (« Accessibilité », « Surveillance de l'entrée »). Les codes de touche sont
  ceux des **positions** d'un clavier américain : sur un clavier AZERTY, A/Q, Z/W et M sont ailleurs (O et
  N, utilisés par défaut, sont au même endroit).

Rien ici n'est indispensable : chaque étape qui échoue est journalisée sans bloquer la fenêtre.
"""

from __future__ import annotations

import ctypes
import functools
import logging
import threading
from collections.abc import Callable

log = logging.getLogger("organizer.client")

# Modificateurs Carbon (Events.h).
COMMAND, SHIFT, OPTION, CONTROL = 0x100, 0x200, 0x800, 0x1000
_MODIFIERS = {
    "ctrl": CONTROL,
    "control": CONTROL,
    "alt": OPTION,
    "option": OPTION,
    "opt": OPTION,
    "shift": SHIFT,
    "cmd": COMMAND,
    "command": COMMAND,
    "meta": COMMAND,
    "super": COMMAND,
    "win": COMMAND,
}
# Codes de touche virtuelle (kVK_ANSI_*, positions du clavier américain).
_KEYS = {
    **dict(zip("asdfhgzxcv", range(0x00, 0x0A), strict=True)),
    "b": 0x0B,
    **dict(zip("qweryt", range(0x0C, 0x12), strict=True)),
    **dict(zip("123465", range(0x12, 0x18), strict=True)),
    "9": 0x19,
    "7": 0x1A,
    "8": 0x1C,
    "0": 0x1D,
    "o": 0x1F,
    "u": 0x20,
    "i": 0x22,
    "p": 0x23,
    "l": 0x25,
    "j": 0x26,
    "k": 0x28,
    "n": 0x2D,
    "m": 0x2E,
    "enter": 0x24,
    "tab": 0x30,
    "space": 0x31,
}
_FUNCTION_KEYS = (0x7A, 0x78, 0x63, 0x76, 0x60, 0x61, 0x62, 0x64, 0x65, 0x6D, 0x67, 0x6F)  # F1 à F12

SIGNATURE = int.from_bytes(b"OrgZ", "big")  # identifie nos raccourcis parmi ceux du processus
KEYBOARD_CLASS = int.from_bytes(b"keyb", "big")
HOTKEY_PRESSED = 5
DIRECT_OBJECT = int.from_bytes(b"----", "big")
TYPE_HOTKEY_ID = int.from_bytes(b"hkid", "big")
NO_ERR, EVENT_NOT_HANDLED = 0, -9874
NS_TERMINATE_NOW = 1


def parse_hotkey(text: str) -> tuple[int, int] | None:
    """``"Ctrl+Alt+O"`` → ``(modificateurs Carbon, code de touche)`` ; None si illisible."""
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    if len(parts) < 2:
        return None
    modifiers = 0
    for part in parts[:-1]:
        if part not in _MODIFIERS:
            return None
        modifiers |= _MODIFIERS[part]
    key = parts[-1]
    if key in _KEYS:
        return modifiers, _KEYS[key]
    if key[0] == "f" and key[1:].isdigit() and 1 <= int(key[1:]) <= len(_FUNCTION_KEYS):
        return modifiers, _FUNCTION_KEYS[int(key[1:]) - 1]
    return None


# --- nom de l'application ----------------------------------------------------------------------------------


def rename_app(name: str = "Organizer") -> None:
    """Nom affiché dans la barre des menus : à appeler avant la création de ``NSApplication``."""
    from Foundation import NSBundle

    bundle = NSBundle.mainBundle()
    for info in (bundle.localizedInfoDictionary(), bundle.infoDictionary()):
        if info is not None:
            info["CFBundleName"] = name


# --- API Carbon (chargée seulement sous macOS) -------------------------------------------------------------


class EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


class EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)


@functools.cache
def _carbon():
    lib = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
    void_p, u32, status = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int32
    lib.GetEventDispatcherTarget.argtypes = []
    lib.GetEventDispatcherTarget.restype = void_p
    lib.InstallEventHandler.argtypes = [
        void_p,
        HANDLER,
        ctypes.c_ulong,
        ctypes.POINTER(EventTypeSpec),
        void_p,
        ctypes.POINTER(void_p),
    ]
    lib.InstallEventHandler.restype = status
    lib.RegisterEventHotKey.argtypes = [u32, u32, EventHotKeyID, void_p, u32, ctypes.POINTER(void_p)]
    lib.RegisterEventHotKey.restype = status
    lib.GetEventParameter.argtypes = [void_p, u32, u32, void_p, ctypes.c_ulong, void_p, void_p]
    lib.GetEventParameter.restype = status
    return lib


# --- délégué de l'application : ⌘Q et clic sur le Dock -----------------------------------------------------

_CALLBACKS: dict[str, Callable[[], None]] = {}


@functools.cache
def _delegate_class():
    from webview.platforms.cocoa import BrowserView

    class OrganizerAppDelegate(BrowserView.AppDelegate):
        def applicationShouldTerminate_(self, app):
            _CALLBACKS.get("quit", lambda: None)()
            return NS_TERMINATE_NOW  # sans demander aux fenêtres (fermer = cacher)

        def applicationShouldHandleReopen_hasVisibleWindows_(self, app, visible):
            if not visible and "reopen" in _CALLBACKS:
                threading.Thread(target=_CALLBACKS["reopen"], daemon=True).start()
            return True

    return OrganizerAppDelegate


def install_app_delegate(on_quit: Callable[[], None], on_reopen: Callable[[], None]) -> None:
    """Remplace le délégué de pywebview (fil principal, une fois la fenêtre créée)."""
    from webview.platforms.cocoa import BrowserView

    _CALLBACKS.update(quit=on_quit, reopen=on_reopen)
    delegate = _delegate_class().alloc().init()
    BrowserView._shared_app_delegate = delegate  # gardé en vie (et réutilisé par pywebview)
    BrowserView.app.setDelegate_(delegate)


# --- ensemble ----------------------------------------------------------------------------------------------


class Shell:
    """Raccourcis globaux et délégué d'application ; ``start`` s'exécute sur le fil principal (Cocoa)."""

    def __init__(
        self,
        keys: dict[str, str],
        actions: dict[str, Callable[[], None]],
        *,
        on_quit: Callable[[], None],
        on_reopen: Callable[[], None],
    ) -> None:
        self.keys, self.actions = keys, actions
        self.on_quit, self.on_reopen = on_quit, on_reopen
        self.registered: dict[int, str] = {}
        self._handler = None  # rappel ctypes, à garder en vie
        self._refs: list[ctypes.c_void_p] = []

    def start(self) -> None:
        try:
            install_app_delegate(self.on_quit, self.on_reopen)
        except Exception:
            log.exception("macOS : ⌘Q et clic sur le Dock non pris en charge")
        try:
            self._register_hotkeys()
        except Exception:
            log.exception("macOS : raccourcis clavier globaux indisponibles")

    def stop(self) -> None:
        """Les raccourcis disparaissent avec le processus ; on cesse seulement d'y répondre."""
        self.actions = {}

    def _register_hotkeys(self) -> None:
        if not self.keys:
            return
        api = _carbon()
        target = api.GetEventDispatcherTarget()
        spec = EventTypeSpec(KEYBOARD_CLASS, HOTKEY_PRESSED)
        self._handler = HANDLER(self._on_event)
        handler_ref = ctypes.c_void_p()
        status = api.InstallEventHandler(
            target, self._handler, 1, ctypes.byref(spec), None, ctypes.byref(handler_ref)
        )
        if status != NO_ERR:
            raise OSError(f"InstallEventHandler : erreur {status}")
        for index, (name, combo) in enumerate(self.keys.items(), start=1):
            parsed = parse_hotkey(combo)
            if parsed is None:
                log.warning("Raccourci illisible : %s", combo)
                continue
            modifiers, code = parsed
            ref = ctypes.c_void_p()
            status = api.RegisterEventHotKey(
                code, modifiers, EventHotKeyID(SIGNATURE, index), target, 0, ctypes.byref(ref)
            )
            if status != NO_ERR:
                log.warning("Raccourci %s indisponible (erreur %s : déjà pris ?)", combo, status)
                continue
            self._refs.append(ref)
            self.registered[index] = name
        log.info("macOS : raccourcis globaux %s", ", ".join(self.keys[n] for n in self.registered.values()))

    def _on_event(self, _call, event, _data) -> int:
        try:
            hotkey = EventHotKeyID()
            status = _carbon().GetEventParameter(
                event, DIRECT_OBJECT, TYPE_HOTKEY_ID, None, ctypes.sizeof(hotkey), None, ctypes.byref(hotkey)
            )
            name = (
                self.registered.get(hotkey.id) if status == NO_ERR and hotkey.signature == SIGNATURE else None
            )
            action = self.actions.get(name) if name else None
            if action is None:
                return EVENT_NOT_HANDLED
            # Hors du fil principal : les méthodes de pywebview y renvoient elles-mêmes leur travail.
            threading.Thread(target=action, daemon=True).start()
            return NO_ERR
        except Exception:  # une exception ne doit jamais remonter dans la boucle Cocoa
            log.exception("Raccourci global")
            return EVENT_NOT_HANDLED
