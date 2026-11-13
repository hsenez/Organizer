"""Intégration du client bureau à **macOS** (appelée par ``install/macos/install.sh``).

    python -m organizer.client.install_macos [--uninstall] [--no-autostart] [--no-shortcuts]
                                             [--show-key Ctrl+Alt+O] [--new-key Ctrl+Alt+N] [--reuse]

Options retenues comme sous Linux (``install.json`` dans le dossier de configuration du client) ;
``--reuse`` les reprend (mise à jour : ``install/macos/update.sh``).

- Application ``~/Applications/Organizer.app`` (Launchpad, Spotlight, Finder ; on peut la glisser dans le
  Dock) : un **lanceur AppleScript** compilé par ``osacompile`` (présent sur tout Mac, sans Xcode). Il lance
  ``run_client.py`` du venv puis s'arrête aussitôt ; si Organizer tourne déjà, la commande lui est
  transmise. Une application AppleScript sait recevoir les liens ``organizer://`` (macOS les envoie par un
  événement Apple ``open location``, jamais en argument), d'où ce choix plutôt qu'un simple script shell.
- Icône : ``organizer.icns`` fabriquée par ``iconutil`` à partir des PNG du projet ; l'application est
  ensuite resignée localement (``codesign -s -``) puisque son ``Info.plist`` a changé.
- Démarrage en arrière-plan à l'ouverture de session : agent ``~/Library/LaunchAgents/<id>.plist``
  (``run_client.py --hidden``), lu par launchd à la prochaine session.
- Raccourcis clavier globaux : enregistrés par Organizer lui-même quand il tourne (``macshell``) ; on ne
  fait ici que les mémoriser dans ``client.json``.
"""

from __future__ import annotations

import argparse
import plistlib
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import organizer
from organizer import ASSETS_DIR, links
from organizer.client import install, macshell, system
from organizer.client.config import ConfigStore

APP_NAME = "Organizer"
BUNDLE_ID = "fr.organizer.client"
AGENT_LABEL = f"{BUNDLE_ID}.autostart"
SCHEME = links.SCHEME
DEFAULT_KEYS = install.DEFAULT_KEYS
LSREGISTER = (
    "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
)
# Fichiers d'un « iconset » (nom attendu par iconutil → taille du PNG du projet).
ICONSET = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
}


@dataclass
class Paths:
    home: Path

    @classmethod
    def from_env(cls) -> Paths:
        return cls(Path.home())

    @property
    def app(self) -> Path:
        return self.home / "Applications" / f"{APP_NAME}.app"

    @property
    def agent(self) -> Path:
        return self.home / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"


# --- contenu des fichiers (fonctions pures, testées sous Linux) --------------------------------------------


def applescript_literal(value: str) -> str:
    """Chaîne AppleScript entre guillemets."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def launcher_script(python: str, root: Path) -> str:
    """Source AppleScript du lanceur : ``run`` (double-clic) et ``open location`` (lien organizer://)."""
    command = (
        f'"PYTHONUTF8=1 " & quoted form of {applescript_literal(python)} & " " & '
        f"quoted form of {applescript_literal(str(root / 'run_client.py'))}"
    )
    return "\n".join(
        [
            "-- Lanceur d'Organizer, généré par install/macos/install.sh (réécrit à chaque mise à jour).",
            "on run",
            '\tlaunchOrganizer("")',
            "end run",
            "",
            "on open location theURL",
            "\tlaunchOrganizer(quoted form of theURL)",
            "end open location",
            "",
            "on launchOrganizer(extraArgs)",
            # « & » final : le client continue seul, le lanceur se termine tout de suite.
            f'\tdo shell script {command} & " " & extraArgs & " > /dev/null 2>&1 &"',
            "end launchOrganizer",
            "",
        ]
    )


def bundle_info(info: dict, version: str = organizer.__version__) -> dict:
    """``Info.plist`` produit par osacompile, complété : identifiant, nom, icône, protocole organizer://."""
    info = dict(info)
    info.pop("CFBundleIconName", None)  # sinon macOS prend l'icône d'AppleScript (Assets.car)
    info.update(
        {
            "CFBundleIdentifier": BUNDLE_ID,
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleIconFile": "organizer",
            "CFBundleShortVersionString": version,
            "CFBundleURLTypes": [
                {"CFBundleURLName": f"{APP_NAME} ({SCHEME}://)", "CFBundleURLSchemes": [SCHEME]}
            ],
            # Le lanceur ne vit qu'un instant : pas d'icône qui sautille dans le Dock.
            "LSUIElement": True,
        }
    )
    return info


def launch_agent(python: str, root: Path) -> dict:
    """Agent launchd : Organizer démarre en arrière-plan à l'ouverture de session."""
    return {
        "Label": AGENT_LABEL,
        "ProgramArguments": [python, str(root / "run_client.py"), "--hidden"],
        "WorkingDirectory": str(root),
        "EnvironmentVariables": {"PYTHONUTF8": "1"},
        "RunAtLoad": True,
        "ProcessType": "Interactive",
        "LimitLoadToSessionType": "Aqua",  # session graphique seulement
    }


def shortcut_config(args: argparse.Namespace) -> dict[str, str]:
    """Raccourcis à mémoriser dans ``client.json`` (vides avec ``--no-shortcuts`` : aucun n'est posé)."""
    if args.no_shortcuts:
        return {"show": "", "new_task": ""}
    return {"show": args.show_key, "new_task": args.new_key}


# --- fabrication de l'application --------------------------------------------------------------------------


def _run(*cmd: str) -> bool:
    try:
        return subprocess.run(cmd, check=False, capture_output=True, timeout=120).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def make_icns(target: Path, work: Path) -> bool:
    iconset = work / "organizer.iconset"
    iconset.mkdir()
    for name, size in ICONSET.items():
        source = ASSETS_DIR / f"organizer-{size}.png"
        if source.exists():
            shutil.copyfile(source, iconset / name)
    return _run("iconutil", "-c", "icns", "-o", str(target), str(iconset))


def build_app(paths: Paths, python: str, root: Path) -> list[str]:
    """Construit ``Organizer.app`` (remplace l'ancienne) ; renvoie les avertissements."""
    warnings = []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        app = work / f"{APP_NAME}.app"
        # Source passé ligne à ligne (« -e ») : pas d'ambiguïté de codage pour un chemin accentué.
        lines = [arg for line in launcher_script(python, root).splitlines() for arg in ("-e", line)]
        result = subprocess.run(
            ["osacompile", "-o", str(app), *lines], check=False, capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"osacompile a échoué : {result.stderr.strip()}")
        contents = app / "Contents"
        plist = contents / "Info.plist"
        plist.write_bytes(plistlib.dumps(bundle_info(plistlib.loads(plist.read_bytes()))))
        (contents / "Resources" / "Assets.car").unlink(missing_ok=True)
        if not make_icns(contents / "Resources" / "organizer.icns", work):
            warnings.append("icône non créée (iconutil)")
        if not _run("codesign", "--force", "--deep", "--sign", "-", str(app)):
            warnings.append("signature locale impossible (codesign)")
        remove_app(paths)
        paths.app.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(app), str(paths.app))
    if Path(LSREGISTER).exists():  # protocole organizer:// et icône pris en compte tout de suite
        _run(LSREGISTER, "-f", str(paths.app))
    return warnings


def remove_app(paths: Paths) -> None:
    if paths.app.exists():
        if Path(LSREGISTER).exists():
            _run(LSREGISTER, "-u", str(paths.app))
        shutil.rmtree(paths.app)


def install_agent(paths: Paths, python: str, root: Path) -> None:
    paths.agent.parent.mkdir(parents=True, exist_ok=True)
    paths.agent.write_bytes(plistlib.dumps(launch_agent(python, root)))


# --- programme ---------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m organizer.client.install_macos")
    parser.add_argument("--uninstall", action="store_true", help="retirer l'application et le démarrage auto")
    parser.add_argument("--no-autostart", action="store_true", help="ne pas démarrer avec la session")
    parser.add_argument("--no-shortcuts", action="store_true", help="pas de raccourcis clavier globaux")
    parser.add_argument("--show-key", default=DEFAULT_KEYS["show"], help="ouvrir Organizer (Ctrl+Alt+O)")
    parser.add_argument("--new-key", default=DEFAULT_KEYS["new_task"], help="nouvelle tâche (Ctrl+Alt+N)")
    parser.add_argument(
        "--reuse", action="store_true", help="reprendre les options de la dernière installation"
    )
    args = parser.parse_args(argv)
    if sys.platform != "darwin":
        print("Ce module s'occupe de macOS ; sous Linux : install/linux/install.sh.")
        return 1
    paths = Paths.from_env()
    root = Path(__file__).resolve().parents[2]

    if args.uninstall:
        remove_app(paths)
        paths.agent.unlink(missing_ok=True)
        print(f"🗑️ {paths.app} et le démarrage automatique retirés.")
        return 0

    if args.reuse:
        install.reuse_options(system.config_dir(), args)
    if not args.no_shortcuts:
        for combo in (args.show_key, args.new_key):
            if macshell.parse_hotkey(combo) is None:  # erreur claire avant d'écrire quoi que ce soit
                print(f"❌ Raccourci non pris en charge : {combo} (ex. Ctrl+Alt+O, Cmd+Shift+F5)")
                return 1
    python = sys.executable
    warnings = build_app(paths, python, root)
    print(f"✅ Application « {APP_NAME} » : {paths.app} (Launchpad, Spotlight)")
    for warning in warnings:
        print(f"⚠️ {warning}")
    print(f"✅ Les liens {SCHEME}://… (« Ouvrir dans le client bureau ») ouvrent Organizer")
    if args.no_autostart:
        paths.agent.unlink(missing_ok=True)
        print("ℹ️ Pas de démarrage automatique")
    else:
        install_agent(paths, python, root)
        print("✅ Démarrage en arrière-plan à l'ouverture de session")
    install.save_options(system.config_dir(), args)
    store = ConfigStore(system.config_dir())
    config = store.load()
    config.shortcuts = shortcut_config(args)
    store.save(config)
    if args.no_shortcuts:
        print("ℹ️ Pas de raccourcis clavier globaux")
    else:
        print(f"✅ Raccourcis : {args.show_key} ouvre Organizer, {args.new_key} crée une tâche")
    return 0


if __name__ == "__main__":
    sys.exit(main())
