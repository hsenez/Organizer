"""Client bureau sous macOS : raccourcis Carbon, lanceur AppleScript, installation (simulée sous Linux)."""

from __future__ import annotations

import json
import os
import plistlib
import stat
import sys
from pathlib import Path

import pytest

from organizer import ASSETS_DIR, versioning
from organizer.client import install_macos, macshell, notifications
from organizer.client.config import ConfigStore
from organizer.client.macshell import COMMAND, CONTROL, OPTION, SHIFT, parse_hotkey


def test_mac_hotkey_parsing():
    assert parse_hotkey("Ctrl+Alt+O") == (CONTROL | OPTION, 0x1F)
    assert parse_hotkey("ctrl + option + n") == (CONTROL | OPTION, 0x2D)
    assert parse_hotkey("Cmd+Shift+F5") == (COMMAND | SHIFT, 0x60)
    assert parse_hotkey("Meta+Alt+A") == (COMMAND | OPTION, 0x00)
    assert parse_hotkey("Ctrl+Alt+7") == (CONTROL | OPTION, 0x1A)
    assert parse_hotkey("Ctrl+Space") == (CONTROL, 0x31)
    for bad in ("O", "Hyper+O", "Ctrl+É", "Ctrl+F13", "Ctrl+Alt+"):
        assert parse_hotkey(bad) is None


def test_mac_key_codes_cover_letters_and_digits():
    """Chaque lettre et chiffre a son propre code de touche (table kVK_ANSI_*)."""
    codes = [parse_hotkey(f"Ctrl+{c}") for c in "abcdefghijklmnopqrstuvwxyz0123456789"]
    assert None not in codes and len({code for _, code in codes}) == 36


def test_update_command_per_platform():
    assert versioning.update_command("darwin") == "install/macos/update.sh"
    assert versioning.update_command("linux") == "install/linux/update.sh"
    assert versioning.update_command("win32") == r"install\windows\update.bat"


def test_osascript_notification_passes_texts_as_arguments():
    cmd = notifications.osascript_command('Rappel : « devis » "urgent"', "Échéance : demain")
    assert cmd[0] == "osascript" and cmd[-2:] == ['Rappel : « devis » "urgent"', "Échéance : demain"]
    assert "display notification (item 2 of argv) with title (item 1 of argv)" in cmd


def test_launcher_script_quotes_paths():
    script = install_macos.launcher_script('/Users/a b/"x"/.venv/bin/python', Path("/Users/a b/Organizer"))
    assert "on open location theURL" in script and "on run" in script
    assert 'quoted form of "/Users/a b/\\"x\\"/.venv/bin/python"' in script
    assert 'quoted form of "/Users/a b/Organizer/run_client.py"' in script
    assert script.count("do shell script") == 1 and '> /dev/null 2>&1 &"' in script


def test_bundle_info_declares_scheme_and_icon():
    info = install_macos.bundle_info(
        {"CFBundleExecutable": "applet", "CFBundleIconName": "applet", "CFBundleIconFile": "applet"}, "9.9.9"
    )
    assert info["CFBundleExecutable"] == "applet" and "CFBundleIconName" not in info
    assert info["CFBundleIconFile"] == "organizer" and info["CFBundleIdentifier"] == install_macos.BUNDLE_ID
    assert info["CFBundleURLTypes"][0]["CFBundleURLSchemes"] == ["organizer"]
    assert info["CFBundleShortVersionString"] == "9.9.9" and info["LSUIElement"] is True


def test_launch_agent_starts_hidden(tmp_path):
    agent = plistlib.loads(plistlib.dumps(install_macos.launch_agent("/v/bin/python", tmp_path)))
    assert agent["ProgramArguments"] == ["/v/bin/python", str(tmp_path / "run_client.py"), "--hidden"]
    assert agent["RunAtLoad"] is True and agent["Label"] == install_macos.AGENT_LABEL


def test_iconset_sources_exist():
    assert all((ASSETS_DIR / f"organizer-{size}.png").exists() for size in install_macos.ICONSET.values())


# --- installation complète, avec de faux outils macOS -------------------------------------------------------


def _fake_tools(folder: Path) -> None:
    """``osacompile`` (squelette d'application), ``iconutil`` et ``codesign`` factices."""
    tools = {
        "osacompile": """#!/usr/bin/env python3
import plistlib, sys
from pathlib import Path
out = Path(sys.argv[sys.argv.index("-o") + 1])
(out / "Contents" / "MacOS").mkdir(parents=True)
(out / "Contents" / "Resources").mkdir()
(out / "Contents" / "MacOS" / "applet").write_text("binaire")
(out / "Contents" / "Resources" / "Assets.car").write_text("icône AppleScript")
lines = [sys.argv[i + 1] for i, arg in enumerate(sys.argv) if arg == "-e"]
(out / "Contents" / "Resources" / "main.applescript").write_text("\\n".join(lines))
(out / "Contents" / "Info.plist").write_bytes(plistlib.dumps(
    {"CFBundleExecutable": "applet", "CFBundleIconName": "applet", "CFBundleName": "launcher"}))
""",
        "iconutil": """#!/usr/bin/env python3
import sys
from pathlib import Path
Path(sys.argv[sys.argv.index("-o") + 1]).write_text("icns")
""",
        "codesign": "#!/bin/sh\nexit 0\n",
    }
    folder.mkdir()
    for name, text in tools.items():
        path = folder / name
        path.write_text(text)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def mac_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    _fake_tools(tmp_path / "bin")
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    monkeypatch.setenv("ORGANIZER_CLIENT_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(install_macos.Paths, "from_env", classmethod(lambda cls: cls(home)))
    return install_macos.Paths(home)


def test_install_builds_app_agent_and_options(mac_home, tmp_path, capsys):
    assert install_macos.main(["--show-key", "Cmd+Alt+O"]) == 0
    contents = mac_home.app / "Contents"
    info = plistlib.loads((contents / "Info.plist").read_bytes())
    assert info["CFBundleIdentifier"] == install_macos.BUNDLE_ID and "CFBundleIconName" not in info
    assert (contents / "Resources" / "organizer.icns").exists()
    assert not (contents / "Resources" / "Assets.car").exists()
    assert "run_client.py" in (contents / "Resources" / "main.applescript").read_text()
    assert plistlib.loads(mac_home.agent.read_bytes())["ProgramArguments"][-1] == "--hidden"
    config = ConfigStore(tmp_path / "config").load()
    assert config.shortcuts == {"show": "Cmd+Alt+O", "new_task": "Ctrl+Alt+N"}
    assert "✅ Raccourcis : Cmd+Alt+O" in capsys.readouterr().out

    # Mise à jour : mêmes options (--reuse), l'application est remplacée.
    assert install_macos.main(["--reuse", "--no-autostart"]) == 0
    saved = json.loads((tmp_path / "config" / "install.json").read_text(encoding="utf-8"))
    assert saved["show_key"] == "Cmd+Alt+O" and saved["no_autostart"] is False
    assert mac_home.agent.exists() and mac_home.app.exists()

    assert install_macos.main(["--no-autostart", "--no-shortcuts"]) == 0
    assert not mac_home.agent.exists()
    assert ConfigStore(tmp_path / "config").load().shortcuts == {"show": "", "new_task": ""}

    assert install_macos.main(["--uninstall"]) == 0
    assert not mac_home.app.exists() and not mac_home.agent.exists()


def test_install_rejects_unknown_shortcut(mac_home, capsys):
    assert install_macos.main(["--new-key", "Hyper+N"]) == 1
    assert "non pris en charge" in capsys.readouterr().out and not mac_home.app.exists()


def test_install_refuses_other_systems(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert install_macos.main([]) == 1


def test_shell_without_keys_registers_nothing():
    shell = macshell.Shell({}, {}, on_quit=lambda: None, on_reopen=lambda: None)
    shell._register_hotkeys()  # aucun appel à Carbon quand il n'y a rien à poser
    assert shell.registered == {}
