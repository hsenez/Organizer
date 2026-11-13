"""Pages (simulateur NiceGUI) : réglages → 🔔 Notifications, rappel d'un événement dans l'éditeur, bouton
🔕 « Ne plus me notifier », rappels d'événements sur l'accueil."""

from __future__ import annotations

from datetime import date, time, timedelta

from nicegui.testing import User

from organizer.core.enums import NOTIFICATIONS_PREF, NotifyLevel
from organizer.core.schemas import EventCreate, NoteCreate, ShareSpec, TaskCreate
from tests.test_pages import data_dir, login, select_value, state  # noqa: F401  (data_dir : automatique)


def pref(sv):
    return sv.users.get_pref(sv.actor.id, NOTIFICATIONS_PREF)


async def test_settings_tab_saves_levels_and_reminders(user: User):
    sv = await login(user)
    await user.open("/settings?tab=reminders")  # ancien nom de l'onglet
    await user.should_see(marker="notify-level-task")
    await user.should_see("Partages seulement")  # légende des niveaux
    select_value(user, "notify-level-note", NotifyLevel.SHARES.value)
    assert pref(sv)["note"] == {"level": "shares", "desktop": True}
    assert pref(sv)["task"]["level"] == "all"  # les autres gardent « Tout »
    select_value(user, "notify-desktop-event", False)
    assert pref(sv)["event"] == {"level": "all", "desktop": False}
    assert pref(sv)["note"]["level"] == "shares"  # rien d'écrasé
    select_value(user, "notify-event-reminder", 15)
    assert pref(sv)["event_reminder"] == 15
    created = sv.agenda.create(EventCreate(title="Avec rappel", start_date=date(2026, 11, 20)))
    assert created.reminder_minutes == 15
    select_value(user, "notify-event-reminder", -1)
    assert pref(sv)["event_reminder"] is None
    select_value(user, "notify-desktop-reminders", False)
    assert not state().users.get(sv.actor.id).desktop_notifications


async def test_event_editor_reminder(user: User):
    sv = await login(user)
    event = sv.agenda.create(
        EventCreate(title="Dentiste", start_date=date(2026, 11, 12), start_time=time(14))
    )
    await user.open(f"/calendar?event={event.id}")
    await user.should_see(marker="editor-reminder")
    select_value(user, "editor-reminder", 60)
    assert sv.agenda.get(event.id).reminder_minutes == 60
    select_value(user, "editor-reminder", -1)
    assert sv.agenda.get(event.id).reminder_minutes is None


async def test_mute_button_on_shared_items_only(user: User):
    sv = await login(user)
    bob = state().services_for(state().users.create_user("bob", "motdepasse-12", "Bob", by=sv.actor))
    shared = bob.tasks.create(TaskCreate(title="De Bob"))
    bob.tasks.set_shares(shared.id, [sv.actor.id])
    alone = sv.tasks.create(TaskCreate(title="Seule"))
    await user.open(f"/?task={alone.id}")
    await user.should_see(marker="editor-copy-link")
    await user.should_not_see(marker="editor-mute")  # personne d'autre : rien à couper
    await user.open(f"/?task={shared.id}")
    await user.should_see(marker="editor-mute")
    user.find(marker="editor-mute").click()
    assert sv.notifications.muted("task", shared.id)
    user.find(marker="editor-mute").click()
    assert not sv.notifications.muted("task", shared.id)

    note = bob.notes.create(NoteCreate(title="Idées"))
    bob.notes.set_shares(note.id, [ShareSpec(user_id=sv.actor.id)])
    await user.open(f"/notes?note={note.id}")
    await user.should_see(marker="note-mute")
    user.find(marker="note-mute").click()
    assert sv.notifications.muted("note", note.id)


async def test_home_shows_event_reminders(user: User):
    sv = await login(user)
    tomorrow = date.today() + timedelta(days=1)
    due = sv.agenda.create(
        EventCreate(title="Rendez-vous", start_date=tomorrow, start_time=time(10), reminder_minutes=10080)
    )
    later = sv.agenda.create(
        EventCreate(title="Plus tard", start_date=tomorrow + timedelta(days=20), reminder_minutes=60)
    )
    await user.open("/")
    await user.should_see(marker=f"home-event-{due.id}")
    await user.should_not_see(marker=f"home-event-{later.id}")
    user.find(marker=f"home-event-{due.id}").click()
    await user.should_see(marker="editor-reminder")
