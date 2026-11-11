"""Intégration du client bureau au bureau **Linux** (appelée par ``install/linux/install.sh``).

    python -m organizer.client.install [--uninstall] [--no-autostart] [--no-shortcuts]
                                       [--show-key Ctrl+Alt+O] [--new-key Ctrl+Alt+N] [--reuse]

Les options choisies sont retenues (``install.json`` dans le dossier de configuration du client) ;
``--reuse`` les reprend (mise à jour : ``install/linux/update.sh``).

- Lanceur ``~/.local/share/applications/organizer.desktop`` (menu des applications), avec les actions
  « Nouvelle tâche » et « Quitter Organizer » (clic droit sur l'icône) ;
- icônes dans ``~/.local/share/icons/hicolor`` ;
- protocole ``organizer://`` (liens « Ouvrir dans le client bureau ») : ``MimeType`` du lanceur et
  ``xdg-mime default`` ;
- démarrage en arrière-plan à l'ouverture de session (``~/.config/autostart``) : rappels et raccourcis
  disponibles tout de suite ;
- **raccourcis clavier globaux** : sous Wayland, une application ne peut pas écouter le clavier hors de sa
  fenêtre ; on les déclare donc au bureau, qui lance la commande (transmise au client déjà lancé) :
  KDE Plasma (kglobalaccel, par D-Bus) ou GNOME (gsettings). Ailleurs, la commande à associer est affichée.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import contextlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from organizer import ASSETS_DIR, links
from organizer.client import system
from organizer.client.config import ConfigStore

APP_ID = "organizer"
SCHEME = links.SCHEME  # liens organizer://note/5
DESKTOP_FILE = f"{APP_ID}.desktop"
ASSETS = ASSETS_DIR
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
DEFAULT_KEYS = {"show": "Ctrl+Alt+O", "new_task": "Ctrl+Alt+N"}
# Action du fichier .desktop déclenchée par chaque raccourci (``_launch`` = l'application elle-même).
KDE_ACTIONS = {"show": ("_launch", "Organizer"), "new_task": ("new-task", "Nouvelle tâche")}
KDE_LEGACY_ACTIONS = ("open",)  # action d'une version intermédiaire, à nettoyer
# Drapeaux de setShortcutKeys. « Présent » est indispensable : un raccourci posé sans lui
# (setForeignShortcutKeys) est bien enregistré et répond à l'appel D-Bus invokeShortcut, mais Plasma 6
# l'ignore sur un vrai appui clavier, sauf s'il a déjà lu l'action dans le lanceur.
KDE_SET_PRESENT = 0x2
KDE_NO_AUTOLOADING = 0x4
GNOME_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
GNOME_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/organizer-{name}/"
OPTIONS_FILE = "install.json"


@dataclass
class Paths:
    data_home: Path
    config_home: Path

    @classmethod
    def from_env(cls) -> Paths:
        home = Path.home()
        return cls(
            Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share"),
            Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config"),
        )

    @property
    def applications(self) -> Path:
        return self.data_home / "applications"

    @property
    def icons(self) -> Path:
        return self.data_home / "icons" / "hicolor"

    @property
    def autostart(self) -> Path:
        return self.config_home / "autostart"


# --- fichiers .desktop -------------------------------------------------------------------------------------


def exec_arg(value: str) -> str:
    """Argument de la clé ``Exec`` d'un fichier .desktop (guillemets et échappements de la spécification)."""
    if value and not any(c in value for c in " \t\n\"'\\><~|&;$*?#()`"):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
    return f'"{escaped}"'


def command(python: str, root: Path, *args: str) -> str:
    return " ".join(exec_arg(a) for a in (python, str(root / "run_client.py"), *args))


def desktop_entry(python: str, root: Path, *, autostart: bool = False) -> str:
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Name=Organizer",
        "GenericName=Organiseur de tâches",
        "Comment=Tâches, kanbans et matrice d'Eisenhower",
        # « %u » : lien organizer://… reçu du système (protocole déclaré par MimeType).
        f"Exec={command(python, root, '--hidden') if autostart else command(python, root) + ' %u'}",
        f"Icon={APP_ID}",
        "Terminal=false",
        "Categories=Office;ProjectManagement;",
        "Keywords=tâches;todo;kanban;eisenhower;organiseur;",
        f"StartupWMClass={APP_ID}",
        "SingleMainWindow=true",
    ]
    if autostart:
        lines += ["X-GNOME-Autostart-enabled=true", "X-KDE-autostart-after=panel"]
    else:
        lines += [
            f"MimeType=x-scheme-handler/{SCHEME};",
            "Actions=new-task;quit;",
            "",
            "[Desktop Action new-task]",
            "Name=Nouvelle tâche",
            f"Exec={command(python, root, '--new-task')}",
            "",
            "[Desktop Action quit]",
            "Name=Quitter Organizer",
            f"Exec={command(python, root, '--quit')}",
        ]
    return "\n".join(lines) + "\n"


def install_files(paths: Paths, python: str, root: Path, *, autostart: bool) -> list[Path]:
    written = []
    for size in ICON_SIZES:
        source = ASSETS / f"organizer-{size}.png"
        if source.exists():
            target = paths.icons / f"{size}x{size}" / "apps" / f"{APP_ID}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            written.append(target)
    if (ASSETS / "organizer.svg").exists():
        target = paths.icons / "scalable" / "apps" / f"{APP_ID}.svg"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ASSETS / "organizer.svg", target)
        written.append(target)
    paths.applications.mkdir(parents=True, exist_ok=True)
    launcher = paths.applications / DESKTOP_FILE
    launcher.write_text(desktop_entry(python, root), encoding="utf-8")
    launcher.chmod(0o755)
    written.append(launcher)
    autostart_file = paths.autostart / DESKTOP_FILE
    if autostart:
        paths.autostart.mkdir(parents=True, exist_ok=True)
        autostart_file.write_text(desktop_entry(python, root, autostart=True), encoding="utf-8")
        written.append(autostart_file)
    else:
        autostart_file.unlink(missing_ok=True)
    return written


def remove_files(paths: Paths) -> None:
    for size in ICON_SIZES:
        (paths.icons / f"{size}x{size}" / "apps" / f"{APP_ID}.png").unlink(missing_ok=True)
    (paths.icons / "scalable" / "apps" / f"{APP_ID}.svg").unlink(missing_ok=True)
    (paths.applications / DESKTOP_FILE).unlink(missing_ok=True)
    (paths.autostart / DESKTOP_FILE).unlink(missing_ok=True)


def refresh_caches(paths: Paths) -> None:
    """Prévient le bureau des nouveaux fichiers (menus, icônes) ; chaque outil est facultatif."""
    for cmd in (
        ["update-desktop-database", "-q", str(paths.applications)],
        ["gtk-update-icon-cache", "-q", "-t", "-f", str(paths.icons)],
        ["kbuildsycoca6"],
        ["kbuildsycoca5"],
    ):
        if shutil.which(cmd[0]):
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run(cmd, check=False, capture_output=True, timeout=60)


def register_scheme() -> bool:
    """Fait d'Organizer l'application des liens ``organizer://`` (``~/.config/mimeapps.list``)."""
    if not shutil.which("xdg-mime"):
        return False
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        result = subprocess.run(
            ["xdg-mime", "default", DESKTOP_FILE, f"x-scheme-handler/{SCHEME}"],
            check=False,
            capture_output=True,
            timeout=30,
        )
        return result.returncode == 0
    return False


# --- raccourcis clavier ------------------------------------------------------------------------------------

_QT_MODIFIERS = {
    "ctrl": 0x04000000,
    "control": 0x04000000,
    "alt": 0x08000000,
    "shift": 0x02000000,
    "meta": 0x10000000,
    "super": 0x10000000,
    "win": 0x10000000,
}
_GNOME_MODIFIERS = {
    "ctrl": "<Control>",
    "control": "<Control>",
    "alt": "<Alt>",
    "shift": "<Shift>",
    "meta": "<Super>",
    "super": "<Super>",
    "win": "<Super>",
}


def _split(combo: str) -> tuple[list[str], str]:
    parts = [p.strip() for p in combo.split("+") if p.strip()]
    if not parts:
        raise ValueError("Raccourci vide.")
    *mods, key = parts
    unknown = [m for m in mods if m.lower() not in _QT_MODIFIERS]
    if unknown:
        raise ValueError(f"Touche de modification inconnue : {unknown[0]}")
    if not mods:
        raise ValueError(
            f"Un raccourci global a besoin d'au moins une touche Ctrl / Alt / Maj / Méta : {combo}"
        )
    return mods, key


def qt_keycode(combo: str) -> int:
    """« Ctrl+Alt+O » → code de touche Qt (format de kglobalaccel)."""
    mods, key = _split(combo)
    code = 0
    for mod in mods:
        code |= _QT_MODIFIERS[mod.lower()]
    if len(key) == 1 and key.isascii() and key.isalnum():
        return code | ord(key.upper())
    if key.upper().startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 35:
        return code | (0x01000030 + int(key[1:]) - 1)
    raise ValueError(f"Touche non prise en charge : {key} (lettre, chiffre ou F1 à F35)")


def gnome_binding(combo: str) -> str:
    """« Ctrl+Alt+O » → « <Control><Alt>o » (format de gsettings)."""
    mods, key = _split(combo)
    qt_keycode(combo)  # même validation
    return "".join(_GNOME_MODIFIERS[m.lower()] for m in mods) + key.lower()


def desktop_kind() -> str:
    desktops = os.environ.get("XDG_CURRENT_DESKTOP", "").upper().split(":")
    if "KDE" in desktops:
        return "kde"
    if any(d in desktops for d in ("GNOME", "UNITY", "BUDGIE", "CINNAMON")):
        return "gnome"
    return "other"


async def _kde_call(calls: list[tuple[str, tuple]]) -> list:
    from dbus_fast.aio import MessageBus

    bus = await MessageBus().connect()
    try:
        node = await bus.introspect("org.kde.kglobalaccel", "/kglobalaccel")
        accel = bus.get_proxy_object("org.kde.kglobalaccel", "/kglobalaccel", node).get_interface(
            "org.kde.KGlobalAccel"
        )
        return [await getattr(accel, f"call_{method}")(*args) for method, args in calls]
    finally:
        bus.disconnect()


def kde_register(keys: dict[str, str], component: str = DESKTOP_FILE) -> None:
    """Déclare les raccourcis à kglobalaccel ; lève RuntimeError si KDE a dû en attribuer un autre
    (combinaison déjà prise)."""
    calls: list[tuple[str, tuple]] = [("unregister", (component, a)) for a in KDE_LEGACY_ACTIONS]
    wanted = {}
    for name, combo in keys.items():
        action, friendly = KDE_ACTIONS[name]
        action_id = [component, action, "Organizer", friendly]
        wanted[len(calls) + 1] = combo
        calls += [
            ("do_register", (action_id,)),
            ("set_shortcut_keys", (action_id, [[[qt_keycode(combo)]]], KDE_SET_PRESENT | KDE_NO_AUTOLOADING)),
        ]
    results = asyncio.run(_kde_call(calls))
    for index, combo in wanted.items():
        granted = [code for (seq,) in (results[index] or []) for code in seq]
        if qt_keycode(combo) not in granted:
            raise RuntimeError(f"{combo} est déjà utilisé par une autre application")


def kde_unregister(component: str = DESKTOP_FILE) -> None:
    actions = [action for action, _ in KDE_ACTIONS.values()] + list(KDE_LEGACY_ACTIONS)
    asyncio.run(_kde_call([("unregister", (component, action)) for action in actions]))


def _gsettings(*args: str) -> str:
    return subprocess.run(["gsettings", *args], check=True, capture_output=True, text=True).stdout.strip()


def _gnome_list() -> list[str]:
    raw = _gsettings("get", GNOME_SCHEMA, "custom-keybindings").removeprefix("@as ")
    return list(ast.literal_eval(raw or "[]"))


def gnome_register(keys: dict[str, str], commands: dict[str, str]) -> None:
    paths = _gnome_list()
    for name, combo in keys.items():
        path = GNOME_PATH.format(name=name.replace("_", "-"))
        if path not in paths:
            paths.append(path)
        schema = f"{GNOME_SCHEMA}.custom-keybinding:{path}"
        _gsettings("set", schema, "name", "Organizer — " + KDE_ACTIONS[name][1])
        _gsettings("set", schema, "command", commands[name])
        _gsettings("set", schema, "binding", gnome_binding(combo))
    _gsettings("set", GNOME_SCHEMA, "custom-keybindings", str(paths))


def gnome_unregister() -> None:
    mine = {GNOME_PATH.format(name=n.replace("_", "-")) for n in KDE_ACTIONS}
    _gsettings("set", GNOME_SCHEMA, "custom-keybindings", str([p for p in _gnome_list() if p not in mine]))


# --- options retenues --------------------------------------------------------------------------------------


def save_options(directory: Path, args: argparse.Namespace) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    options = {k: getattr(args, k) for k in ("no_autostart", "no_shortcuts", "show_key", "new_key")}
    (directory / OPTIONS_FILE).write_text(json.dumps(options, ensure_ascii=False, indent=2), encoding="utf-8")


def reuse_options(directory: Path, args: argparse.Namespace) -> None:
    """Reprend les options de la dernière installation (celles de la ligne de commande sinon)."""
    try:
        saved = json.loads((directory / OPTIONS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for key in ("no_autostart", "no_shortcuts", "show_key", "new_key"):
        if key in saved:
            setattr(args, key, saved[key])


# --- programme ---------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m organizer.client.install")
    parser.add_argument("--uninstall", action="store_true", help="retirer lanceur, icônes et raccourcis")
    parser.add_argument("--no-autostart", action="store_true", help="ne pas démarrer avec la session")
    parser.add_argument("--no-shortcuts", action="store_true", help="ne pas déclarer de raccourcis clavier")
    parser.add_argument("--show-key", default=DEFAULT_KEYS["show"], help="ouvrir Organizer (Ctrl+Alt+O)")
    parser.add_argument("--new-key", default=DEFAULT_KEYS["new_task"], help="nouvelle tâche (Ctrl+Alt+N)")
    parser.add_argument(
        "--reuse", action="store_true", help="reprendre les options de la dernière installation"
    )
    args = parser.parse_args(argv)
    if not sys.platform.startswith("linux"):
        print("Ce module s'occupe de Linux ; sous Windows, utilisez install\\windows\\install.bat.")
        return 1
    paths = Paths.from_env()
    root = Path(__file__).resolve().parents[2]
    kind = desktop_kind()

    if args.uninstall:
        with contextlib.suppress(Exception):
            if kind == "kde":
                kde_unregister()
            elif kind == "gnome":
                gnome_unregister()
        remove_files(paths)
        refresh_caches(paths)
        print("🗑️ Lanceur, icônes, démarrage automatique et raccourcis retirés.")
        return 0

    if args.reuse:
        reuse_options(system.config_dir(), args)
    keys = {"show": args.show_key, "new_task": args.new_key}
    for combo in keys.values():
        qt_keycode(combo)  # erreur claire avant d'écrire quoi que ce soit
    python = sys.executable
    install_files(paths, python, root, autostart=not args.no_autostart)
    save_options(system.config_dir(), args)
    refresh_caches(paths)
    print(f"✅ Lanceur « Organizer » ajouté au menu des applications ({paths.applications / DESKTOP_FILE})")
    if register_scheme():
        print(f"✅ Les liens {SCHEME}://… (« Ouvrir dans le client bureau ») ouvrent Organizer")
    else:
        print(f"⚠️ Liens {SCHEME}://… non déclarés (xdg-mime introuvable)")
    print(
        "✅ Démarrage en arrière-plan à l'ouverture de session"
        if not args.no_autostart
        else "ℹ️ Pas de démarrage automatique"
    )

    if not args.no_shortcuts:
        commands = {"show": command(python, root, "--show"), "new_task": command(python, root, "--new-task")}
        try:
            if kind == "kde":
                kde_register(keys)
            elif kind == "gnome":
                gnome_register(keys, commands)
            else:
                raise RuntimeError("bureau non reconnu")
        except Exception as exc:
            print(f"⚠️ Raccourcis non déclarés ({exc}). Associez-les dans les réglages du bureau :")
            for name, combo in keys.items():
                print(f"   {combo:<14} → {commands[name]}")
        else:
            print(f"✅ Raccourcis : {keys['show']} ouvre Organizer, {keys['new_task']} crée une tâche")
            store = ConfigStore(system.config_dir())
            config = store.load()
            config.shortcuts = keys
            store.save(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
