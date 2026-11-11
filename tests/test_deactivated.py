"""Compte désactivé : ses tâches, événements et notes disparaissent pour les autres, sauf pour ceux qui
peuvent les modifier (qui peuvent alors aussi les supprimer) ; une réactivation fait tout revenir."""

from __future__ import annotations

from datetime import date

import pytest

from organizer.core.errors import Forbidden, NotFound
from organizer.core.schemas import (
    AdminUserPatch,
    EventCreate,
    NoteCreate,
    ShareSpec,
    TaskCreate,
)
from organizer.core.services import Services

D = date(2026, 11, 12)


@pytest.fixture
def carol(engine, users, alice, settings, clock) -> Services:
    user = users.create_user("carol", "motdepasse-12", "Carol", by=alice.actor)
    return Services.for_user(engine, user.id, settings=settings, today=clock)


def set_active(users, alice, sv, active: bool) -> None:
    users.admin_update(alice.actor, sv.actor.id, AdminUserPatch(is_active=active))


def test_events_and_notes(users, alice, bob, carol):
    """Bob désactivé : Alice (modifiable) garde ses éléments et peut les supprimer ; Carol (lecture seule)
    et le public ne les voient plus."""
    public_event = bob.agenda.create(EventCreate(title="Public", start_date=D, is_public=True))
    shared_event = bob.agenda.create(EventCreate(title="Partagé", start_date=D))
    bob.agenda.set_shares(
        shared_event.id,
        [ShareSpec(user_id=alice.actor.id, can_edit=True), ShareSpec(user_id=carol.actor.id, can_edit=False)],
    )
    public_note = bob.notes.create(NoteCreate(title="Publique", is_public=True))
    shared_note = bob.notes.create(NoteCreate(title="Partagée"))
    bob.notes.set_shares(
        shared_note.id,
        [ShareSpec(user_id=alice.actor.id, can_edit=True), ShareSpec(user_id=carol.actor.id, can_edit=False)],
    )
    assert {e.title for e in carol.agenda.list()} == {"Public", "Partagé"}

    set_active(users, alice, bob, False)
    assert [e.title for e in alice.agenda.list()] == ["Partagé"]
    assert carol.agenda.list() == [] and carol.notes.list() == []
    assert [n.title for n in alice.notes.list()] == ["Partagée"]
    with pytest.raises(NotFound):
        carol.notes.get(shared_note.id)
    with pytest.raises(NotFound):
        alice.agenda.get(public_event.id)
    assert alice.notes.get(shared_note.id).can_delete

    set_active(users, alice, bob, True)  # réactivé : tout revient
    assert {e.title for e in carol.agenda.list()} == {"Public", "Partagé"}
    assert {n.title for n in carol.notes.list()} == {"Publique", "Partagée"}

    set_active(users, alice, bob, False)
    alice.agenda.delete(shared_event.id)
    alice.notes.delete(shared_note.id)
    assert alice.agenda.list() == [] and alice.notes.list() == []
    assert public_note.id


def test_tasks_can_be_deleted_by_those_who_share_them(users, alice, bob, carol):
    task = bob.tasks.create(TaskCreate(title="Commune"))
    bob.tasks.set_shares(task.id, [alice.actor.id])
    seen = alice.tasks.get(task.id)
    assert not seen.can_delete
    with pytest.raises(Forbidden):
        alice.tasks.delete(task.id)
    with pytest.raises(NotFound):
        carol.tasks.get(task.id)  # jamais partagée avec Carol

    set_active(users, alice, bob, False)
    assert alice.tasks.get(task.id).can_delete  # une tâche partagée est toujours modifiable : elle reste
    alice.tasks.delete(task.id)
    with pytest.raises(NotFound):
        alice.tasks.get(task.id)


def test_notification_no_longer_opens_a_hidden_item(users, alice, bob, carol):
    note = bob.notes.create(NoteCreate(title="Idées"))
    bob.notes.set_shares(
        note.id, [ShareSpec(user_id=alice.actor.id), ShareSpec(user_id=carol.actor.id, can_edit=False)]
    )
    assert alice.notifications.list()[0].available and carol.notifications.list()[0].available
    set_active(users, alice, bob, False)
    assert alice.notifications.list()[0].available
    assert not carol.notifications.list()[0].available
