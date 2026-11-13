"""🔔 Notifications système du client bureau (pop-ups).

- **Rappels des suivis** (``ReminderNotifier``) : toutes les 5 minutes, les suivis dont la date de rappel
  est atteinte (``tasks.reminders_due``), notifiés **une fois par jour** chacun (journal ``notified.json``).
- **Rappels des événements** (``EventReminderNotifier``) : chaque minute, les événements dont le rappel
  est atteint à l'heure du poste (``agenda.reminders_due``), notifiés **une fois** (journal
  ``notified-events.json`` ; de nouveau si l'événement est déplacé ou son rappel changé).
  Ces deux rappels suivent l'option « Pop-up sur le bureau pour les rappels » du compte.
- **Nouvelles notifications** (``NotificationPopups``) : celles de la page 🔔 Notifications apparues
  depuis le démarrage du client, pour les types dont la case « Pop-up sur le bureau » est cochée
  (réglages → 🔔 Notifications) ; vérifiées chaque minute et dès qu'un autre utilisateur modifie quelque
  chose (temps réel). Un clic ouvre l'élément et marque la notification comme lue.

Un clic sur une notification ouvre l'élément dans la fenêtre.

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
from datetime import date, datetime
from pathlib import Path

from organizer.core import rules
from organizer.core.enums import NOTIFY_ITEM_TYPES
from organizer.core.errors import OrganizerError
from organizer.core.schemas import EventOut, NotificationOut, NotificationSettings, TaskOut
from organizer.ui import format as fmt
from organizer.ui.pages.notifications import KINDS
from organizer.ui.pages.notifications import describe as describe_notification

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
        await repeat(self.check, self.interval, first_delay=first_delay, what="rappels")


async def repeat(
    check: Callable[[], Awaitable[object]],
    interval: float,
    *,
    first_delay: float = 8,
    wake: asyncio.Event | None = None,
    what: str = "notifications",
) -> None:
    """Appelle ``check`` toutes les ``interval`` secondes (plus tôt si ``wake`` est levé), sans jamais
    s'arrêter sur une erreur."""
    await asyncio.sleep(first_delay)
    while True:
        try:
            await check()
        except OrganizerError as exc:  # serveur injoignable, session expirée… : on réessaiera
            log.info("%s non vérifié(e)s : %s", what, exc.message)
        except Exception:  # une notification ratée ne doit jamais arrêter la boucle
            log.exception("Erreur pendant la vérification : %s", what)
        if wake is None:
            await asyncio.sleep(interval)
        else:
            try:
                await asyncio.wait_for(wake.wait(), interval)
            except TimeoutError:
                pass
            wake.clear()


# --- rappels des événements ---------------------------------------------------------------------------------


def event_key(event: EventOut) -> str:
    """Identité d'un rappel : un événement déplacé, ou dont le rappel a changé, est rappelé de nouveau."""
    return f"{event.id}:{event.start_date}T{event.start_time}:{event.reminder_minutes}"


class EventReminderLog:
    """Rappels d'événements déjà notifiés (gardés jusqu'à la fin de l'événement)."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def pick(self, events: list[EventOut], now: datetime) -> list[EventOut]:
        """Événements pas encore notifiés ; les enregistre (et oublie ceux qui sont finis)."""
        known = {k: v for k, v in self._load().items() if v > now.isoformat()}
        new = [e for e in events if event_key(e) not in known]
        for event in new:
            known[event_key(event)] = rules.event_end_at(event.end_date, event.end_time).isoformat()
        if new or len(known) != len(self._load()):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(known), encoding="utf-8")
        return new


def describe_events(events: list[EventOut], today: date) -> list[tuple[str, str, int | None]]:
    """``(titre, message, événement à ouvrir au clic)``."""
    if len(events) > GROUP_ABOVE:
        lines = "\n".join(f"• {e.title}" for e in events[:6]) + ("\n…" if len(events) > 6 else "")
        return [(f"⏰ {len(events)} événements", lines, None)]
    result = []
    for event in events:
        when = fmt.event_range(event.start_date, event.start_time, event.end_date, event.end_time)
        where = f"\n📍 {event.location}" if event.location else ""
        result.append((f"⏰ {event.title}", f"{when}{where}", event.id))
    return result


class EventReminderNotifier:
    def __init__(
        self,
        fetch: Callable[[datetime], tuple[bool, list[EventOut]]],
        log_: EventReminderLog,
        send: Sender,
        *,
        open_event: Callable[[int], None] | None = None,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        """``fetch(maintenant)`` (bloquant) renvoie ``(rappels activés, événements dont le rappel est
        atteint)``."""
        self.fetch = fetch
        self.log = log_
        self.send = send
        self.open_event = open_event
        self.now = now

    async def check(self) -> list[EventOut]:
        now = self.now()
        enabled, events = await asyncio.to_thread(self.fetch, now)
        if not enabled:
            return []
        new = self.log.pick(events, now)
        for title, message, event_id in describe_events(new, now.date()):
            on_clicked = None
            if event_id is not None and self.open_event is not None:
                on_clicked = lambda event_id=event_id: self.open_event(event_id)  # noqa: E731
            await self.send(title, message, on_clicked)
        return new


# --- nouvelles notifications --------------------------------------------------------------------------------


def describe_notifications(
    items: list[NotificationOut],
) -> list[tuple[str, str, NotificationOut | None]]:
    """``(titre, message, notification à ouvrir au clic)`` ; au-delà de 3, un récapitulatif."""
    if len(items) > GROUP_ABOVE:
        lines = "\n".join(f"• {describe_notification(n)}" for n in items[:6]) + (
            "\n…" if len(items) > 6 else ""
        )
        return [(f"🔔 {len(items)} nouvelles notifications", lines, None)]
    return [(f"{KINDS.get(n.kind, KINDS['change'])[0]} {describe_notification(n)}", n.text, n) for n in items]


class NotificationPopups:
    """Pop-up pour chaque nouvelle notification (types choisis dans les réglages)."""

    def __init__(
        self,
        fetch: Callable[[int], tuple[NotificationSettings, list[NotificationOut]]],
        send: Sender,
        *,
        open_notification: Callable[[NotificationOut], None] | None = None,
    ) -> None:
        """``fetch(après)`` (bloquant) renvoie ``(réglages, notifications non lues de numéro > après)``."""
        self.fetch = fetch
        self.send = send
        self.open_notification = open_notification
        self.last_id: int | None = None  # None : pas encore de point de départ

    async def check(self) -> list[NotificationOut]:
        settings, items = await asyncio.to_thread(self.fetch, self.last_id or 0)
        first = self.last_id is None
        self.last_id = max([self.last_id or 0, *(n.id for n in items)])
        if first:  # au démarrage : les notifications déjà là restent dans la page, sans pop-up
            return []
        wanted = [n for n in items if n.item_type in NOTIFY_ITEM_TYPES and settings.of(n.item_type).desktop]
        wanted.sort(key=lambda n: n.id)
        for title, message, item in describe_notifications(wanted):
            on_clicked = None
            if item is not None and self.open_notification is not None:
                on_clicked = lambda item=item: self.open_notification(item)  # noqa: E731
            await self.send(title, message, on_clicked)
        return wanted
