"""Intégration à Windows (client bureau), **dans le sous-processus de la fenêtre** : raccourcis clavier
globaux, icône dans la zone de notification, mise au premier plan.

Bibliothèque standard seulement (``ctypes``) : pas de dépendance ajoutée.

- **Raccourcis globaux** : ``RegisterHotKey``. Avant, ils étaient portés par les raccourcis ``.lnk`` du menu
  Démarrer : l'Explorateur lançait un nouveau ``pythonw`` qui transmettait la commande au client, puis la
  fenêtre demandait le premier plan… que Windows refuse souvent à un processus qui n'a pas reçu l'appui
  (« rien ne se passe », bug rencontré). Ici, c'est le processus de la fenêtre qui reçoit ``WM_HOTKEY`` :
  Windows lui accorde alors le droit de passer au premier plan. Un raccourci déjà pris (par un ``.lnk``
  d'une ancienne installation, ou un autre logiciel) est signalé dans le journal.
- **Zone de notification** : ``Shell_NotifyIconW`` ; clic → afficher, clic droit → menu (Ouvrir, Nouvelle
  tâche, Quitter). L'icône est remise si l'Explorateur redémarre (message ``TaskbarCreated``).
- Tout tourne dans un fil dédié qui a sa propre boucle de messages et une fenêtre cachée.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger("organizer.client")

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
_MODIFIERS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT, "win": MOD_WIN}
_NAMED_KEYS = {"space": 0x20, "enter": 0x0D, "tab": 0x09, "home": 0x24, "end": 0x23, "insert": 0x2D}

WM_DESTROY, WM_CLOSE, WM_NULL, WM_HOTKEY = 0x0002, 0x0010, 0x0000, 0x0312
WM_LBUTTONUP, WM_RBUTTONUP, WM_APP = 0x0202, 0x0205, 0x8000
WM_TRAY = WM_APP + 1
NIM_ADD, NIM_DELETE = 0, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x1, 0x2, 0x4
SW_RESTORE, SW_SHOW = 9, 5

MENU_SHOW, MENU_NEW, MENU_QUIT = 1, 2, 3


def parse_hotkey(text: str) -> tuple[int, int] | None:
    """``"Ctrl+Alt+O"`` → ``(modificateurs, code de touche virtuelle)`` ; None si illisible."""
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    if len(parts) < 2:
        return None
    modifiers = 0
    for part in parts[:-1]:
        if part not in _MODIFIERS:
            return None
        modifiers |= _MODIFIERS[part]
    key = parts[-1]
    if len(key) == 1 and key.isascii() and key.isalnum():
        return modifiers, ord(key.upper())
    if key[0] == "f" and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return modifiers, 0x6F + int(key[1:])
    if key in _NAMED_KEYS:
        return modifiers, _NAMED_KEYS[key]
    return None


# --- appels Windows (chargés seulement sous Windows) --------------------------------------------------------


def _api():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    lresult = ctypes.c_ssize_t
    wndproc = ctypes.WINFUNCTYPE(lresult, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", wndproc),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("hWnd", wintypes.HWND),
            ("uID", wintypes.UINT),
            ("uFlags", wintypes.UINT),
            ("uCallbackMessage", wintypes.UINT),
            ("hIcon", wintypes.HICON),
            ("szTip", wintypes.WCHAR * 128),
            ("dwState", wintypes.DWORD),
            ("dwStateMask", wintypes.DWORD),
            ("szInfo", wintypes.WCHAR * 256),
            ("uVersion", wintypes.UINT),
            ("szInfoTitle", wintypes.WCHAR * 64),
            ("dwInfoFlags", wintypes.DWORD),
            ("guidItem", ctypes.c_byte * 16),
            ("hBalloonIcon", wintypes.HICON),
        ]

    signatures = {
        user32: {
            "DefWindowProcW": (lresult, [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]),
            "RegisterClassW": (wintypes.ATOM, [ctypes.POINTER(WNDCLASSW)]),
            "CreateWindowExW": (
                wintypes.HWND,
                [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
                + [ctypes.c_int] * 4
                + [wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID],
            ),
            "DestroyWindow": (wintypes.BOOL, [wintypes.HWND]),
            "RegisterHotKey": (wintypes.BOOL, [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]),
            "UnregisterHotKey": (wintypes.BOOL, [wintypes.HWND, ctypes.c_int]),
            "GetMessageW": (
                wintypes.BOOL,
                [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT],
            ),
            "TranslateMessage": (wintypes.BOOL, [ctypes.POINTER(wintypes.MSG)]),
            "DispatchMessageW": (lresult, [ctypes.POINTER(wintypes.MSG)]),
            "PostMessageW": (wintypes.BOOL, [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]),
            "PostQuitMessage": (None, [ctypes.c_int]),
            "RegisterWindowMessageW": (wintypes.UINT, [wintypes.LPCWSTR]),
            "LoadImageW": (
                wintypes.HANDLE,
                [
                    wintypes.HINSTANCE,
                    wintypes.LPCWSTR,
                    wintypes.UINT,
                    ctypes.c_int,
                    ctypes.c_int,
                    wintypes.UINT,
                ],
            ),
            "GetSystemMetrics": (ctypes.c_int, [ctypes.c_int]),
            "CreatePopupMenu": (wintypes.HMENU, []),
            "AppendMenuW": (
                wintypes.BOOL,
                [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR],
            ),
            "DestroyMenu": (wintypes.BOOL, [wintypes.HMENU]),
            "TrackPopupMenu": (
                wintypes.BOOL,
                [
                    wintypes.HMENU,
                    wintypes.UINT,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    wintypes.HWND,
                    wintypes.LPVOID,
                ],
            ),
            "GetCursorPos": (wintypes.BOOL, [ctypes.POINTER(wintypes.POINT)]),
            "SetForegroundWindow": (wintypes.BOOL, [wintypes.HWND]),
            "GetForegroundWindow": (wintypes.HWND, []),
            "ShowWindow": (wintypes.BOOL, [wintypes.HWND, ctypes.c_int]),
            "IsIconic": (wintypes.BOOL, [wintypes.HWND]),
            "IsWindowVisible": (wintypes.BOOL, [wintypes.HWND]),
            "GetWindow": (wintypes.HWND, [wintypes.HWND, wintypes.UINT]),
            "GetClassNameW": (ctypes.c_int, [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]),
            "GetWindowThreadProcessId": (wintypes.DWORD, [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]),
            "AttachThreadInput": (wintypes.BOOL, [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]),
            "BringWindowToTop": (wintypes.BOOL, [wintypes.HWND]),
            "AllowSetForegroundWindow": (wintypes.BOOL, [wintypes.DWORD]),
        },
        shell32: {"Shell_NotifyIconW": (wintypes.BOOL, [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)])},
        kernel32: {
            "GetModuleHandleW": (wintypes.HMODULE, [wintypes.LPCWSTR]),
            "GetCurrentThreadId": (wintypes.DWORD, []),
            "GetCurrentProcessId": (wintypes.DWORD, []),
        },
    }
    for dll, functions in signatures.items():
        for name, (restype, argtypes) in functions.items():
            function = getattr(dll, name)
            function.restype, function.argtypes = restype, argtypes
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.restype, user32.EnumWindows.argtypes = wintypes.BOOL, [enum_proc, wintypes.LPARAM]
    return ctypes, wintypes, user32, shell32, kernel32, wndproc, WNDCLASSW, NOTIFYICONDATAW, enum_proc


def allow_foreground_for_others() -> None:
    """Appelé par un lancement qui transmet sa commande : il cède son droit au premier plan au client."""
    if sys.platform != "win32":
        return
    try:
        _api()[2].AllowSetForegroundWindow(0xFFFFFFFF)  # ASFW_ANY
    except (OSError, AttributeError):
        pass


def main_windows(exclude: int = 0) -> list[int]:
    """Fenêtres principales (WinForms, de premier niveau, sans propriétaire) de ce processus."""
    ctypes, wintypes, user32, _, kernel32, *_rest, enum_proc = _api()
    pid = kernel32.GetCurrentProcessId()
    found: list[int] = []

    def visit(hwnd, _lparam) -> bool:
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and hwnd != exclude and not user32.GetWindow(hwnd, 4):  # GW_OWNER
            name = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, name, 64)
            if name.value.startswith("WindowsForms"):
                found.append(hwnd)
        return True

    user32.EnumWindows(enum_proc(visit), 0)
    return found


def bring_to_front(exclude: int = 0) -> bool:
    """Restaure et met au premier plan la fenêtre du client ; True si Windows l'a accepté."""
    _, _, user32, _, kernel32, *_ = _api()
    ok = False
    for hwnd in main_windows(exclude):
        if not user32.IsWindowVisible(hwnd):
            continue
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        if user32.SetForegroundWindow(hwnd):
            ok = True
            continue
        # Refusé (verrou de premier plan) : on s'attache un instant à la file d'entrée de la fenêtre active.
        foreground = user32.GetForegroundWindow()
        theirs = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
        ours = kernel32.GetCurrentThreadId()
        if theirs and theirs != ours and user32.AttachThreadInput(ours, theirs, True):
            try:
                user32.BringWindowToTop(hwnd)
                ok = bool(user32.SetForegroundWindow(hwnd))
            finally:
                user32.AttachThreadInput(ours, theirs, False)
    return ok


class Shell:
    """Raccourcis globaux et icône de la zone de notification (fil dédié)."""

    def __init__(
        self,
        hotkeys: dict[str, str],
        actions: dict[str, Callable[[], None]],
        icon: Path | None,
        tooltip: str = "Organizer",
    ) -> None:
        """``hotkeys`` : ``{"show": "Ctrl+Alt+O", "new_task": …}`` ; ``actions`` : show, new_task, quit."""
        self.hotkeys = hotkeys
        self.actions = actions
        self.icon = icon
        self.tooltip = tooltip
        self.hwnd = 0
        self.registered: dict[int, str] = {}
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="organizer-winshell", daemon=True)
        self._thread.start()
        self._ready.wait(5)

    def stop(self) -> None:
        """Retire l'icône et les raccourcis (sinon une icône fantôme reste jusqu'au survol)."""
        if self.hwnd:
            _api()[2].PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            if self._thread is not None and self._thread is not threading.current_thread():
                self._thread.join(2)

    def _do(self, name: str) -> None:
        action = self.actions.get(name)
        if action is None:
            return
        try:
            action()
        except Exception:  # une action ratée ne doit pas arrêter la boucle de messages
            log.exception("Action « %s » de la zone de notification", name)

    def _run(self) -> None:
        ctypes, wintypes, user32, shell32, kernel32, wndproc, WNDCLASSW, NOTIFYICONDATAW, _ = _api()
        instance = kernel32.GetModuleHandleW(None)
        taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.uID = 1
        data.uFlags = NIF_MESSAGE | NIF_TIP | NIF_ICON
        data.uCallbackMessage = WM_TRAY
        data.szTip = self.tooltip[:127]
        if self.icon is not None and self.icon.is_file():
            size = user32.GetSystemMetrics(49)  # SM_CXSMICON
            data.hIcon = user32.LoadImageW(
                None, str(self.icon), 1, size, size, 0x10
            )  # IMAGE_ICON, LOADFROMFILE

        def menu() -> None:
            handle = user32.CreatePopupMenu()
            user32.AppendMenuW(handle, 0, MENU_SHOW, "📋 Ouvrir Organizer")
            user32.AppendMenuW(handle, 0, MENU_NEW, "➕ Nouvelle tâche")
            user32.AppendMenuW(handle, 0x800, 0, None)  # MF_SEPARATOR
            user32.AppendMenuW(handle, 0, MENU_QUIT, "⏻ Quitter Organizer")
            point = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(point))
            user32.SetForegroundWindow(self.hwnd)  # sinon le menu ne se ferme pas en cliquant ailleurs
            choice = user32.TrackPopupMenu(
                handle, 0x0100 | 0x0080 | 0x0002, point.x, point.y, 0, self.hwnd, None
            )
            user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
            user32.DestroyMenu(handle)
            self._do({MENU_SHOW: "show", MENU_NEW: "new_task", MENU_QUIT: "quit"}.get(choice, ""))

        def proc(hwnd, message, wparam, lparam):
            if message == WM_HOTKEY:
                self._do(self.registered.get(wparam, ""))
                return 0
            if message == WM_TRAY:
                if lparam == WM_LBUTTONUP:
                    self._do("show")
                elif lparam == WM_RBUTTONUP:
                    menu()
                return 0
            if message == taskbar_created and taskbar_created:  # Explorateur redémarré
                shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data))
                return 0
            if message == WM_DESTROY:
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))
                for ident in self.registered:
                    user32.UnregisterHotKey(hwnd, ident)
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)

        callback = wndproc(proc)  # gardé vivant pendant toute la boucle
        cls = WNDCLASSW()
        cls.lpfnWndProc = callback
        cls.hInstance = instance
        cls.lpszClassName = f"OrganizerShell{os.getpid()}"
        user32.RegisterClassW(ctypes.byref(cls))
        self.hwnd = user32.CreateWindowExW(
            0, cls.lpszClassName, "Organizer", 0, 0, 0, 0, 0, None, None, instance, None
        )
        if not self.hwnd:
            log.warning("Zone de notification indisponible (erreur %s)", ctypes.get_last_error())
            self._ready.set()
            return
        data.hWnd = self.hwnd
        if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)):
            log.warning("Icône de la zone de notification refusée")
        for ident, (name, text) in enumerate(self.hotkeys.items(), start=1):
            parsed = parse_hotkey(text or "")
            if parsed is None:
                log.warning("Raccourci illisible : %r", text)
                continue
            modifiers, key = parsed
            if user32.RegisterHotKey(self.hwnd, ident, modifiers | MOD_NOREPEAT, key):
                self.registered[ident] = name
            else:
                log.warning(
                    "Raccourci %s déjà pris par un autre programme (erreur %s)", text, ctypes.get_last_error()
                )
        self._ready.set()
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        self.hwnd = 0
