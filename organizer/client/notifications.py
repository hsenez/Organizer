"""🔔 Notifications système des rappels (client bureau).

Toutes les ``interval`` secondes, le client demande au serveur les suivis dont la date de rappel est
atteinte (``tasks.reminders_due``) et notifie **une fois par jour** chaque tâche concernée (journal
``notified.json``), si l'utilisateur a laissé l'option « Notifications système » activée. Un clic sur la
notification ouvre la tâche dans la fenêtre.

Envoi : bibliothèque ``desktop-notifier`` (Linux, Windows, macOS) ; à défaut, ``notify-send`` sous Linux.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import sys
from collections.abc import Awaitable, Callable
from datetime import date
from pathlib import Path

from organizer.core.errors import OrganizerError
from organizer.core.schemas import TaskOut
from organizer.ui import format as fmt

log = logging.getLogger("organizer.client")

GROUP_ABOVE = 3  # au-delà, une seule notification récapitulative


class NotifiedLog:
    """Tâches déjà notifiées aujourd'hui (le journal repart à zéro chaque jour)."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self, today: date) -> set[int]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        if data.get("date") != today.isoformat():
            return set()
        return {int(i) for i in data.get("ids", [])}

    def pick(self, tasks: list[TaskOut], today: date) -> list[TaskOut]:
        """Tâches pas encore notifiées aujourd'hui ; les enregistre comme notifiées."""
        done = self._load(today)
        new = [t for t in tasks if t.id not in done]
        if new:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            ids = sorted(done | {t.id for t in new})
            self.path.write_text(json.dumps({"date": today.isoformat(), "ids": ids}), encoding="utf-8")
        return new


def describe(tasks: list[TaskOut], today: date) -> list[tuple[str, str, int | None]]:
    """Notifications à envoyer : ``(titre, message, tâche à ouvrir au clic)``."""
    if len(tasks) > GROUP_ABOVE:
        lines = "\n".join(f"• {t.title}" for t in tasks[:6]) + ("\n…" if len(tasks) > 6 else "")
        return [(f"🔔 {len(tasks)} rappels", lines, None)]
    result = []
    for task in tasks:
        due = f"Échéance : {fmt.due_text(task.due_date, task.due_time, today)}" if task.due_date else ""
        result.append((f"🔔 Rappel : {task.title}", due or "Tâche à suivre", task.id))
    return result


Sender = Callable[[str, str, Callable[[], None] | None], Awaitable[None]]


def osascript_command(title: str, message: str) -> list[str]:
    """Notification macOS par AppleScript (textes passés en arguments : rien à échapper)."""
    script = ("on run argv", "display notification (item 2 of argv) with title (item 1 of argv)", "end run")
    return ["osascript", *(part for line in script for part in ("-e", line)), title, message]


def make_sender() -> Sender:
    """Fonction d'envoi d'une notification système (desktop-notifier, sinon notify-send, sinon journal).

    macOS : desktop-notifier n'y fonctionne que depuis une application signée (il resterait muet) ; on
    passe donc par ``osascript`` (pas d'action au clic)."""
    if sys.platform == "darwin" and shutil.which("osascript"):

        async def mac_send(title: str, message: str, on_clicked: Callable[[], None] | None) -> None:
            subprocess.Popen(
                osascript_command(title, message), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )

        return mac_send
    try:
        from desktop_notifier import DesktopNotifier, Icon

        if sys.platform.startswith("linux"):
            icon = Icon(name="appointment-soon")
        elif sys.platform == "win32":  # sinon Windows affiche l'icône de Python (identité « Organizer »)
            from organizer import ASSETS_DIR

            icon = Icon(path=ASSETS_DIR / "organizer-256.png")
        else:
            icon = None
        notifier = (
            DesktopNotifier(app_name="Organizer", app_icon=icon)
            if icon
            else DesktopNotifier(app_name="Organizer")
        )

        async def send(title: str, message: str, on_clicked: Callable[[], None] | None) -> None:
            await notifier.send(title=title, message=message, on_clicked=on_clicked)

        return send
    except ImportError:
        pass
    command = shutil.which("notify-send")

    async def fallback(title: str, message: str, on_clicked: Callable[[], None] | None) -> None:
        if command:
            subprocess.Popen([command, "--app-name=Organizer", title, message])
        else:
            log.info("%s — %s", title, message)

    return fallback


class ReminderNotifier:
    def __init__(
        self,
        fetch: Callable[[], tuple[bool, list[TaskOut]]],
        notified: NotifiedLog,
        send: Sender,
        *,
        open_task: Callable[[int], None] | None = None,
        interval: float = 300,
        today: Callable[[], date] = date.today,
    ) -> None:
        """``fetch`` (bloquant, exécuté dans un thread) renvoie ``(notifications activées, rappels)``."""
        self.fetch = fetch
        self.notified = notified
        self.send = send
        self.open_task = open_task
        self.interval = interval
        self.today = today

    async def check(self) -> list[TaskOut]:
        enabled, tasks = await asyncio.to_thread(self.fetch)
        if not enabled:
            return []
        new = self.notified.pick(tasks, self.today())
        for title, message, task_id in describe(new, self.today()):
            on_clicked = None
            if task_id is not None and self.open_task is not None:
                on_clicked = lambda task_id=task_id: self.open_task(task_id)  # noqa: E731
            await self.send(title, message, on_clicked)
        return new

    async def run(self, first_delay: float = 8) -> None:
        await asyncio.sleep(first_delay)
        while True:
            try:
                await self.check()
            except OrganizerError as exc:  # serveur injoignable, session expirée… : on réessaiera
                log.info("Rappels non vérifiés : %s", exc.message)
            except Exception:  # une notification ratée ne doit jamais arrêter la boucle
                log.exception("Erreur pendant la vérification des rappels")
            await asyncio.sleep(self.interval)
