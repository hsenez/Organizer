"""Notifications : qui est prévenu de quoi (partage, modification, suppression, conversion), regroupement des
actions rapprochées, lu / non lu, élément encore ouvrable."""

from __future__ import annotations

from datetime import date, time

from organizer.core.enums import LinkKind, Status
from organizer.core.schemas import EventCreate, EventPatch, LinkIn, ShareSpec, TaskCreate, TaskPatch


def kinds(sv):
    return [(n.kind, n.item_type, n.title) for n in sv.notifications.list()]


def test_sharing_and_changes_notify_the_others_only(alice, bob):
    task = alice.tasks.create(TaskCreate(title="Plombier"))
    assert bob.notifications.list() == []  # pas encore concerné
    alice.tasks.set_shares(task.id, [bob.actor.id])
    [shared] = bob.notifications.list()
    assert (shared.kind, shared.actor_name, shared.title, shared.read, shared.available) == (
        "share",
        "Alice",
        "Plombier",
        False,
        True,
    )
    assert alice.notifications.list() == []  # jamais pour soi-même

    bob.tasks.update(task.id, TaskPatch(status=Status.IN_PROGRESS))
    change = alice.notifications.list()[0]
    assert (change.kind, change.actor_name, change.item_id) == ("change", "Bob", task.id)
    assert "Statut" in change.text
    bob.tasks.add_link(task.id, LinkIn(kind=LinkKind.URL, target="exemple.fr"))
    assert alice.notifications.list()[0].text.startswith("Ajouter un lien")
    assert alice.notifications.unread_count() == 2

    alice.tasks.set_shares(task.id, [])
    assert bob.notifications.list()[0].kind == "unshare"
    assert not bob.notifications.list()[0].available  # plus visible


def test_rapid_identical_actions_are_merged(alice, bob):
    task = alice.tasks.create(TaskCreate(title="Notes"))
    alice.tasks.set_shares(task.id, [bob.actor.id])
    for text in ("a", "ab", "abc"):
        bob.tasks.update(task.id, TaskPatch(notes=text))
    assert len(alice.notifications.list()) == 1
    alice.notifications.mark_read()
    bob.tasks.update(task.id, TaskPatch(notes="abcd"))  # après lecture : nouvelle notification
    assert [n.read for n in alice.notifications.list()] == [False, True]


def test_events_delete_and_conversion(alice, bob):
    event = alice.agenda.create(
        EventCreate(title="Cinéma", start_date=date(2026, 11, 12), start_time=time(20))
    )
    alice.agenda.set_shares(event.id, [ShareSpec(user_id=bob.actor.id, can_edit=True)])
    assert kinds(bob) == [("share", "event", "Cinéma")]
    bob.agenda.update(event.id, EventPatch(location="Centre"))
    assert kinds(alice) == [("change", "event", "Cinéma")]
    # Conversion par la propriétaire : Bob voit une modification (ni nouveau partage, ni suppression).
    task = alice.agenda.to_task(event.id)
    latest = bob.notifications.list()[0]
    assert (latest.kind, latest.item_type, latest.item_id, latest.available) == (
        "change",
        "task",
        task.id,
        True,
    )
    alice.tasks.delete(task.id)
    latest = bob.notifications.list()[0]
    assert (latest.kind, latest.available) == ("delete", False)


def test_subtask_of_a_shared_task_concerns_the_parent_people(alice, bob):
    parent = alice.tasks.create(TaskCreate(title="Déménagement"))
    alice.tasks.set_shares(parent.id, [bob.actor.id])
    bob.tasks.create(TaskCreate(title="Cartons", parent_id=parent.id))
    latest = alice.notifications.list()[0]
    assert (latest.kind, latest.title) == ("change", "Cartons")


def test_mark_read_and_undo_does_not_notify(alice, bob):
    task = alice.tasks.create(TaskCreate(title="A"))
    alice.tasks.set_shares(task.id, [bob.actor.id])
    bob.tasks.update(task.id, TaskPatch(title="B"))
    bob.tasks.update(task.id, TaskPatch(urgency=4))
    ids = [n.id for n in alice.notifications.list()]
    assert alice.notifications.mark_read(ids[:1]) == 1
    assert alice.notifications.unread_count() == 1
    assert bob.notifications.unread_count() == 1 and bob.notifications.mark_read() == 0  # le partage
    bob.undo.undo()  # annuler ne prévient personne
    assert alice.notifications.unread_count() == 1
    assert alice.notifications.mark_read() == 0
