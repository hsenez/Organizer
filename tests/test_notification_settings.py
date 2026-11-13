"""Réglages des notifications : niveaux par type d'élément, « ne plus me notifier » pour un élément,
rappels des événements, pop-ups du client bureau."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from organizer.client.notifications import (
    EventReminderLog,
    EventReminderNotifier,
    NotificationPopups,
    describe_events,
    describe_notifications,
    event_key,
)
from organizer.core import rules
from organizer.core.enums import NOTIFICATIONS_PREF, NotifyLevel
from organizer.core.errors import InvalidOperation, NotFound
from organizer.core.schemas import (
    EventCreate,
    EventPatch,
    NoteCreate,
    NotePatch,
    NotificationSettings,
    ShareSpec,
    TaskCreate,
    TaskPatch,
)

# --- règles pures -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("level", "kind", "owner", "expected"),
    [
        (NotifyLevel.NONE, "share", True, False),
        (NotifyLevel.NONE, "change", True, False),
        (NotifyLevel.SHARES, "share", False, True),
        (NotifyLevel.SHARES, "unshare", False, True),
        (NotifyLevel.SHARES, "delete", False, True),
        (NotifyLevel.SHARES, "change", True, False),
        (NotifyLevel.MINE, "change", True, True),
        (NotifyLevel.MINE, "change", False, False),
        (NotifyLevel.MINE, "delete", False, True),
        (NotifyLevel.ALL, "change", False, True),
    ],
)
def test_wants_notification(level, kind, owner, expected):
    assert rules.wants_notification(level, kind, is_owner=owner) is expected


def test_notification_settings_are_tolerant():
    assert rules.notification_settings(None) == NotificationSettings()
    assert rules.notification_settings("abîmé") == NotificationSettings()
    settings = rules.notification_settings(
        {"task": {"level": "inconnu"}, "note": {"level": "none", "desktop": False}, "event_reminder": "x"}
    )
    assert settings.task.level is NotifyLevel.ALL and settings.task.desktop  # valeur illisible : défaut
    assert settings.note.level is NotifyLevel.NONE and not settings.note.desktop
    assert settings.event_reminder is None
    assert rules.notification_settings({"event_reminder": 15}).event_reminder == 15
    assert rules.notification_settings({"event_reminder": 10**9}).event_reminder is None  # hors bornes
    assert settings.of("tag") is settings.task  # type inconnu : réglage des tâches


def test_event_reminder_moment():
    day = date(2026, 11, 10)
    assert rules.event_reminder_at(day, time(14, 30), None) is None
    assert rules.event_reminder_at(day, time(14, 30), 15) == datetime(2026, 11, 10, 14, 15)
    assert rules.event_reminder_at(day, None, 1440) == datetime(2026, 11, 9, 9, 0)  # journée : depuis 9 h
    due = lambda now: rules.event_reminder_due(day, time(14), day, time(15), 60, now)  # noqa: E731
    assert not due(datetime(2026, 11, 10, 12, 59))
    assert due(datetime(2026, 11, 10, 13, 0)) and due(datetime(2026, 11, 10, 14, 59))
    assert not due(datetime(2026, 11, 10, 15, 0))  # fini
    assert rules.event_reminder_due(day, None, day, None, 0, datetime(2026, 11, 10, 23, 59))
    assert not rules.event_reminder_due(day, None, day, None, 0, datetime(2026, 11, 11, 0, 0))


# --- niveaux ------------------------------------------------------------------------------------------------


def save_pref(sv, value):
    sv.users.set_pref(sv.actor.id, NOTIFICATIONS_PREF, value)


def set_levels(sv, **levels):
    save_pref(sv, {key: {"level": value, "desktop": True} for key, value in levels.items()})


def shared_task(alice, bob, title="Commun"):
    task = alice.tasks.create(TaskCreate(title=title))
    alice.tasks.set_shares(task.id, [bob.actor.id])
    return task


def test_levels_filter_what_is_recorded(alice, bob):
    set_levels(bob, task="shares")
    task = shared_task(alice, bob)
    assert [n.kind for n in bob.notifications.list()] == ["share"]
    alice.tasks.update(task.id, TaskPatch(title="Commun (modifié)"))
    assert len(bob.notifications.list()) == 1  # pas les modifications

    set_levels(bob, task="mine")  # la tâche est à Alice : toujours rien
    alice.tasks.update(task.id, TaskPatch(notes="texte"))
    assert len(bob.notifications.list()) == 1
    mine = bob.tasks.create(TaskCreate(title="À Bob"))
    bob.tasks.set_shares(mine.id, [alice.actor.id])
    alice.tasks.update(mine.id, TaskPatch(notes="vu"))
    latest = bob.notifications.list()[0]
    assert (latest.kind, latest.title) == ("change", "À Bob")

    set_levels(bob, task="all")
    alice.tasks.update(task.id, TaskPatch(notes="encore"))
    assert bob.notifications.list()[0].title == "Commun (modifié)"

    set_levels(bob, task="none")
    alice.tasks.delete(task.id)
    assert bob.notifications.list()[0].kind != "delete"


def test_levels_are_per_item_type(alice, bob):
    set_levels(bob, task="none", note="all")
    shared_task(alice, bob)
    note = alice.notes.create(NoteCreate(title="Idées"))
    alice.notes.set_shares(note.id, [ShareSpec(user_id=bob.actor.id)])
    assert [(n.kind, n.item_type) for n in bob.notifications.list()] == [("share", "note")]
    event = alice.agenda.create(EventCreate(title="Réunion", start_date=date(2026, 11, 12)))
    alice.agenda.set_shares(event.id, [ShareSpec(user_id=bob.actor.id)])
    assert bob.notifications.list()[0].item_type == "event"  # événements : « Tout » par défaut


def test_mine_level_counts_the_parent_task(alice, bob):
    """Une sous-tâche d'une tâche de Bob est « à lui » pour le niveau ✏️ Mes éléments."""
    set_levels(bob, task="mine")
    parent = bob.tasks.create(TaskCreate(title="Parent"))
    bob.tasks.set_shares(parent.id, [alice.actor.id])
    child = alice.tasks.create(TaskCreate(title="Enfant", parent_id=parent.id))
    before = len(bob.notifications.list())
    alice.tasks.update(child.id, TaskPatch(notes="fait"))
    assert len(bob.notifications.list()) == before + 1


# --- ne plus me notifier pour un élément ------------------------------------------------------------------


def test_mute_an_item(alice, bob):
    task = shared_task(alice, bob)
    other = shared_task(alice, bob, "Autre")
    assert not bob.notifications.muted("task", task.id)
    assert bob.notifications.set_muted("task", task.id, True) is True
    assert bob.notifications.muted("task", task.id)
    count = len(bob.notifications.list())
    alice.tasks.update(task.id, TaskPatch(notes="silence"))
    assert len(bob.notifications.list()) == count
    alice.tasks.update(other.id, TaskPatch(notes="bruit"))  # les autres éléments notifient toujours
    assert len(bob.notifications.list()) == count + 1
    child = alice.tasks.create(TaskCreate(title="Sous-tâche", parent_id=task.id))
    alice.tasks.update(child.id, TaskPatch(notes="x"))  # couper la tâche coupe aussi ses sous-tâches
    assert len(bob.notifications.list()) == count + 1
    assert not alice.notifications.muted("task", task.id)  # personnel

    bob.undo.undo()  # annulable comme une épingle
    assert not bob.notifications.muted("task", task.id)
    bob.undo.redo()
    assert bob.notifications.muted("task", task.id)
    assert bob.notifications.set_muted("task", task.id, False) is False


def test_mute_needs_a_visible_item_and_is_forgotten_with_it(alice, bob, engine):
    from sqlmodel import Session, select

    from organizer.core.models import ItemMute

    private = alice.tasks.create(TaskCreate(title="Privée"))
    with pytest.raises(NotFound):
        bob.notifications.set_muted("task", private.id, True)
    with pytest.raises(InvalidOperation):
        bob.notifications.muted("tag", 1)
    note = alice.notes.create(NoteCreate(title="Note"))
    alice.notes.set_shares(note.id, [ShareSpec(user_id=bob.actor.id)])
    event = alice.agenda.create(EventCreate(title="Fête", start_date=date(2026, 11, 20)))
    alice.agenda.set_shares(event.id, [ShareSpec(user_id=bob.actor.id)])
    task = shared_task(alice, bob)
    for kind, item_id in (("note", note.id), ("event", event.id), ("task", task.id)):
        bob.notifications.set_muted(kind, item_id, True)
    alice.notes.delete(note.id)
    alice.agenda.delete(event.id)
    alice.tasks.delete(task.id)
    with Session(engine) as s:
        assert s.exec(select(ItemMute)).all() == []  # un identifiant peut resservir : rien ne reste
    alice.undo.undo()  # la tâche revient… et son « ne plus me notifier » aussi
    assert bob.notifications.muted("task", task.id)


def test_muted_note_stays_silent(alice, bob):
    note = alice.notes.create(NoteCreate(title="Liste"))
    alice.notes.set_shares(note.id, [ShareSpec(user_id=bob.actor.id)])
    bob.notifications.set_muted("note", note.id, True)
    count = len(bob.notifications.list())
    alice.notes.update(note.id, NotePatch(notes="- [ ] pain"))
    assert len(bob.notifications.list()) == count


def test_list_after_returns_new_unread_only(alice, bob):
    task = shared_task(alice, bob)
    [first] = bob.notifications.list()
    assert bob.notifications.list(after=first.id) == []
    alice.tasks.update(task.id, TaskPatch(title="Changé"))
    new = bob.notifications.list(after=first.id)
    assert [n.kind for n in new] == ["change"]
    bob.notifications.mark_read()
    assert bob.notifications.list(after=0) == []


# --- rappels des événements -------------------------------------------------------------------------------


def test_event_reminders(alice, bob, users):
    day = date(2026, 11, 10)
    event = alice.agenda.create(
        EventCreate(title="Dentiste", start_date=day, start_time=time(14), reminder_minutes=60)
    )
    assert event.reminder_minutes == 60
    assert alice.agenda.reminders_due(datetime(2026, 11, 10, 12, 0)) == []
    assert [e.id for e in alice.agenda.reminders_due(datetime(2026, 11, 10, 13, 5))] == [event.id]
    assert alice.agenda.reminders_due(datetime(2026, 11, 10, 15, 0)) == []  # fini
    assert bob.agenda.reminders_due(datetime(2026, 11, 10, 13, 5)) == []  # pas concerné
    alice.agenda.set_shares(event.id, [ShareSpec(user_id=bob.actor.id, can_edit=False)])
    assert len(bob.agenda.reminders_due(datetime(2026, 11, 10, 13, 5))) == 1  # partagé : rappelé aussi
    public = alice.agenda.create(
        EventCreate(title="Public", start_date=day, start_time=time(14), reminder_minutes=60, is_public=True)
    )
    assert public.id not in [e.id for e in bob.agenda.reminders_due(datetime(2026, 11, 10, 13, 5))]
    updated = alice.agenda.update(event.id, EventPatch(reminder_minutes=None))
    assert updated.reminder_minutes is None and alice.agenda.reminders_due(datetime(2026, 11, 10, 13, 5)) == [
        alice.agenda.get(public.id)
    ]
    assert alice.undo.status().undo_label.startswith("Changer le rappel")


def test_default_event_reminder_from_settings(alice):
    plain = alice.agenda.create(EventCreate(title="Sans", start_date=date(2026, 11, 12)))
    assert plain.reminder_minutes is None  # par défaut : pas de rappel
    save_pref(alice, {"event_reminder": 30})
    default = alice.agenda.create(EventCreate(title="Avec", start_date=date(2026, 11, 12)))
    assert default.reminder_minutes == 30
    explicit = alice.agenda.create(
        EventCreate(title="Choisi", start_date=date(2026, 11, 12), reminder_minutes=None)
    )
    assert explicit.reminder_minutes is None  # fourni explicitement : respecté


# --- client bureau : pop-ups --------------------------------------------------------------------------------


def _event(event_id: int, start: datetime, minutes: int = 15, title: str = "Réunion"):
    from organizer.core.schemas import EventOut

    end = start + timedelta(hours=1)
    return EventOut(
        id=event_id,
        owner_id=1,
        title=title,
        notes="",
        created_at=start,
        updated_at=start,
        start_date=start.date(),
        start_time=start.time(),
        end_date=end.date(),
        end_time=end.time(),
        all_day=False,
        reminder_minutes=minutes,
        display_color="#000000",
    )


async def test_event_reminder_notifier(tmp_path):
    start = datetime(2026, 11, 10, 14, 0)
    events = [_event(1, start)]
    sent, opened = [], []

    async def send(title, message, on_clicked):
        sent.append((title, message, on_clicked))

    clock = {"now": datetime(2026, 11, 10, 13, 50)}
    notifier = EventReminderNotifier(
        lambda now: (True, events),
        EventReminderLog(tmp_path / "notified-events.json"),
        send,
        open_event=opened.append,
        now=lambda: clock["now"],
    )
    assert [e.id for e in await notifier.check()] == [1]
    assert sent[0][0] == "⏰ Réunion" and "14:00" in sent[0][1]
    sent[0][2]()
    assert opened == [1]
    clock["now"] = datetime(2026, 11, 10, 13, 55)
    assert await notifier.check() == []  # une seule fois
    events[0] = _event(1, start + timedelta(hours=1))  # déplacé : rappelé de nouveau
    assert len(await notifier.check()) == 1
    assert event_key(events[0]) != event_key(_event(1, start))
    clock["now"] = datetime(2026, 11, 11, 9, 0)
    events.clear()  # rappel passé : le serveur ne le renvoie plus
    assert await notifier.check() == []
    assert EventReminderLog(tmp_path / "notified-events.json")._load() == {}  # événements finis oubliés
    many = [_event(i, start, title=f"E{i}") for i in range(5)]
    assert describe_events(many, start.date())[0][0] == "⏰ 5 événements"


async def test_notification_popups(alice, bob):
    sent, opened = [], []

    async def send(title, message, on_clicked):
        sent.append((title, message, on_clicked))

    def fetch(after):
        return rules.notification_settings(
            bob.users.get_pref(bob.actor.id, NOTIFICATIONS_PREF)
        ), bob.notifications.list(after=after)

    popups = NotificationPopups(fetch, send, open_notification=opened.append)
    task = shared_task(alice, bob)
    assert await popups.check() == [] and sent == []  # au démarrage : rien de déjà là
    alice.tasks.update(task.id, TaskPatch(title="Renommée"))
    [new] = await popups.check()
    assert sent[0][0].startswith("✏️ Alice a modifié") and sent[0][1].startswith("Renommer")
    sent[0][2]()
    assert opened == [new]
    assert await popups.check() == []  # pas deux fois
    save_pref(bob, {"task": {"level": "all", "desktop": False}})
    alice.tasks.update(task.id, TaskPatch(notes="silence sur le bureau"))
    assert await popups.check() == [] and len(sent) == 1  # notifiée dans la page, sans pop-up
    assert len(describe_notifications(bob.notifications.list() * 2)) == 1  # au-delà de 3 : récapitulatif
