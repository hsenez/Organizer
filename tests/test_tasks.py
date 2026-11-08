"""Tâches : attributs, rappels, sous-tâches, visibilité, filtres, liens."""

from __future__ import annotations

from datetime import date, time, timedelta

import pytest

from organizer.core.enums import DueBucket, Importance, LinkKind, Status, TaskKind, Urgency
from organizer.core.errors import Forbidden, InvalidOperation, NotFound
from organizer.core.schemas import (
    LinkIn,
    LinkPatch,
    ProjectIn,
    TagIn,
    TaskCreate,
    TaskFilter,
    TaskPatch,
    TaskSort,
)

from .conftest import TODAY


def titles(tasks):
    return [t.title for t in tasks]


# --- attributs de base ------------------------------------------------------------------------------------


def test_create_with_defaults(alice):
    task = alice.tasks.create(TaskCreate(title="  Écrire la spec  "))
    assert task.title == "Écrire la spec"
    assert task.importance is Importance.NORMAL
    assert task.urgency is Urgency.SOON
    assert task.status is Status.NOT_STARTED
    assert task.kind is TaskKind.TODO
    assert task.reminder_date is None
    assert task.can_delete


def test_completed_at_follows_status(alice):
    task = alice.tasks.create(TaskCreate(title="T"))
    done = alice.tasks.update(task.id, TaskPatch(status=Status.DONE))
    assert done.completed_at is not None
    reopened = alice.tasks.update(task.id, TaskPatch(status=Status.PAUSED))
    assert reopened.completed_at is None


def test_patch_only_touches_given_fields(alice):
    task = alice.tasks.create(TaskCreate(title="T", due_date=TODAY, notes="abc"))
    updated = alice.tasks.update(task.id, TaskPatch(importance=Importance.CRITICAL))
    assert updated.due_date == TODAY and updated.notes == "abc"
    cleared = alice.tasks.update(task.id, TaskPatch(due_date=None))
    assert cleared.due_date is None


def test_clearing_due_date_clears_time(alice):
    task = alice.tasks.create(TaskCreate(title="RDV", due_date=TODAY, due_time=time(14, 30)))
    assert alice.tasks.get(task.id).due_time == time(14, 30)
    cleared = alice.tasks.update(task.id, TaskPatch(due_date=None))
    assert cleared.due_time is None


def test_required_fields_cannot_be_nulled(alice):
    task = alice.tasks.create(TaskCreate(title="T"))
    with pytest.raises(InvalidOperation):
        alice.tasks.update(task.id, TaskPatch(title=None))
    with pytest.raises(InvalidOperation):
        alice.tasks.update(task.id, TaskPatch(title="   "))


# --- rappels (type Suivi) ---------------------------------------------------------------------------------


def test_followup_gets_default_offset_and_follows_due_date(alice):
    due = TODAY + timedelta(days=10)
    task = alice.tasks.create(TaskCreate(title="Relancer", kind=TaskKind.FOLLOWUP, due_date=due))
    assert task.reminder_offset_days == 2
    assert task.reminder_date == due - timedelta(days=2)
    moved = alice.tasks.update(task.id, TaskPatch(due_date=due + timedelta(days=5)))
    assert moved.reminder_date == due + timedelta(days=3)


def test_manual_reminder_then_back_to_offset(alice):
    due = TODAY + timedelta(days=10)
    task = alice.tasks.create(TaskCreate(title="Relancer", kind=TaskKind.FOLLOWUP, due_date=due))
    manual = alice.tasks.update(task.id, TaskPatch(reminder_date=TODAY + timedelta(days=1)))
    assert manual.reminder_offset_days is None
    assert manual.reminder_date == TODAY + timedelta(days=1)
    moved = alice.tasks.update(task.id, TaskPatch(due_date=due + timedelta(days=5)))
    assert moved.reminder_date == TODAY + timedelta(days=1)  # le rappel manuel ne suit pas
    back = alice.tasks.update(task.id, TaskPatch(reminder_offset_days=3))
    assert back.reminder_date == due + timedelta(days=2)


def test_switching_todo_to_followup_sets_offset(alice):
    task = alice.tasks.create(TaskCreate(title="T", due_date=TODAY + timedelta(days=4)))
    followup = alice.tasks.update(task.id, TaskPatch(kind=TaskKind.FOLLOWUP))
    assert followup.reminder_date == TODAY + timedelta(days=2)


def test_reminders_due(alice, clock):
    alice.tasks.create(
        TaskCreate(title="Bientôt", kind=TaskKind.FOLLOWUP, due_date=TODAY + timedelta(days=1))
    )
    alice.tasks.create(TaskCreate(title="Loin", kind=TaskKind.FOLLOWUP, due_date=TODAY + timedelta(days=20)))
    alice.tasks.create(TaskCreate(title="Simple", due_date=TODAY))
    closed = alice.tasks.create(TaskCreate(title="Fini", kind=TaskKind.FOLLOWUP, due_date=TODAY))
    alice.tasks.update(closed.id, TaskPatch(status=Status.DONE))
    assert titles(alice.tasks.reminders_due()) == ["Bientôt"]
    clock.value = TODAY + timedelta(days=18)
    assert titles(alice.tasks.reminders_due()) == ["Bientôt", "Loin"]


# --- sous-tâches ------------------------------------------------------------------------------------------


@pytest.fixture
def project(alice):
    return alice.projects.create(ProjectIn(name="Maison", emoji="🏠"))


def test_subtask_inherits_from_parent_unless_given(alice, project):
    parent = alice.tasks.create(
        TaskCreate(
            title="Parent",
            importance=Importance.CRITICAL,
            urgency=Urgency.PRESSING,
            due_date=TODAY,
            project_id=project.id,
        )
    )
    sub = alice.tasks.create(TaskCreate(title="Sous", parent_id=parent.id))
    assert (sub.importance, sub.urgency, sub.due_date) == (Importance.CRITICAL, Urgency.PRESSING, TODAY)
    assert sub.project.id == project.id
    assert sub.parent_title == "Parent"
    explicit = alice.tasks.create(
        TaskCreate(title="Sous 2", parent_id=parent.id, importance=Importance.MINOR)
    )
    assert explicit.importance is Importance.MINOR


def test_only_one_level_of_subtasks(alice):
    parent = alice.tasks.create(TaskCreate(title="P"))
    sub = alice.tasks.create(TaskCreate(title="S", parent_id=parent.id))
    with pytest.raises(InvalidOperation):
        alice.tasks.create(TaskCreate(title="SS", parent_id=sub.id))


def test_progress_ignores_cancelled(alice):
    parent = alice.tasks.create(TaskCreate(title="P"))
    a = alice.tasks.create(TaskCreate(title="a", parent_id=parent.id))
    b = alice.tasks.create(TaskCreate(title="b", parent_id=parent.id))
    alice.tasks.create(TaskCreate(title="c", parent_id=parent.id))
    alice.tasks.update(a.id, TaskPatch(status=Status.DONE))
    alice.tasks.update(b.id, TaskPatch(status=Status.CANCELLED))
    p = alice.tasks.get(parent.id)
    assert (p.subtask_count, p.subtask_total, p.subtask_done) == (3, 2, 1)
    assert p.has_subtasks


def test_starting_subtask_starts_parent(alice):
    parent = alice.tasks.create(TaskCreate(title="P"))
    sub = alice.tasks.create(TaskCreate(title="S", parent_id=parent.id))
    alice.tasks.update(sub.id, TaskPatch(status=Status.IN_PROGRESS))
    assert alice.tasks.get(parent.id).status is Status.IN_PROGRESS


def test_starting_subtask_does_not_touch_paused_parent(alice):
    parent = alice.tasks.create(TaskCreate(title="P", status=Status.PAUSED))
    sub = alice.tasks.create(TaskCreate(title="S", parent_id=parent.id))
    alice.tasks.update(sub.id, TaskPatch(status=Status.IN_PROGRESS))
    assert alice.tasks.get(parent.id).status is Status.PAUSED


def test_due_after_parent_warning(alice):
    parent = alice.tasks.create(TaskCreate(title="P", due_date=TODAY))
    sub = alice.tasks.create(TaskCreate(title="S", parent_id=parent.id, due_date=TODAY + timedelta(days=3)))
    assert sub.due_after_parent
    ok = alice.tasks.update(sub.id, TaskPatch(due_date=TODAY))
    assert not ok.due_after_parent


def test_attach_and_detach(alice):
    parent = alice.tasks.create(TaskCreate(title="P"))
    child = alice.tasks.create(TaskCreate(title="C", status=Status.IN_PROGRESS))
    attached = alice.tasks.attach(child.id, parent.id)
    assert attached.parent_id == parent.id
    assert alice.tasks.get(parent.id).status is Status.IN_PROGRESS
    assert titles(alice.tasks.list()) == ["P"]  # sous-tâches masquées par défaut
    detached = alice.tasks.detach(child.id)
    assert detached.parent_id is None
    with pytest.raises(InvalidOperation):
        alice.tasks.detach(child.id)


def test_attach_refusals(alice):
    parent = alice.tasks.create(TaskCreate(title="P"))
    sub = alice.tasks.create(TaskCreate(title="S", parent_id=parent.id))
    other = alice.tasks.create(TaskCreate(title="O"))
    with pytest.raises(InvalidOperation):
        alice.tasks.attach(other.id, sub.id)  # la cible est une sous-tâche
    with pytest.raises(InvalidOperation):
        alice.tasks.attach(parent.id, other.id)  # la tâche déposée a des sous-tâches
    with pytest.raises(InvalidOperation):
        alice.tasks.attach(other.id, other.id)


def test_attach_moves_subtask_to_new_parent(alice):
    p1 = alice.tasks.create(TaskCreate(title="P1"))
    p2 = alice.tasks.create(TaskCreate(title="P2"))
    sub = alice.tasks.create(TaskCreate(title="S", parent_id=p1.id))
    alice.tasks.attach(sub.id, p2.id)
    assert alice.tasks.get(p1.id).subtask_count == 0
    assert alice.tasks.get(p2.id).subtask_count == 1


def test_reorder_subtasks(alice):
    parent = alice.tasks.create(TaskCreate(title="P"))
    ids = [alice.tasks.create(TaskCreate(title=n, parent_id=parent.id)).id for n in "abc"]
    assert titles(alice.tasks.subtasks(parent.id)) == ["a", "b", "c"]
    alice.tasks.reorder_subtasks(parent.id, [ids[2], ids[0], ids[1]])
    assert titles(alice.tasks.subtasks(parent.id)) == ["c", "a", "b"]
    with pytest.raises(InvalidOperation):
        alice.tasks.reorder_subtasks(parent.id, ids[:2])


def test_delete_parent_detaches_or_deletes_subtasks(alice):
    p1 = alice.tasks.create(TaskCreate(title="P1"))
    alice.tasks.create(TaskCreate(title="S1", parent_id=p1.id))
    alice.tasks.delete(p1.id)
    assert titles(alice.tasks.list()) == ["S1"]

    p2 = alice.tasks.create(TaskCreate(title="P2"))
    alice.tasks.create(TaskCreate(title="S2", parent_id=p2.id))
    alice.tasks.delete(p2.id, with_subtasks=True)
    assert titles(alice.tasks.list(TaskFilter(include_subtasks=True))) == ["S1"]


# --- visibilité et partage --------------------------------------------------------------------------------


def test_tasks_are_private_by_default(alice, bob):
    task = alice.tasks.create(TaskCreate(title="Secret"))
    assert bob.tasks.list() == []
    with pytest.raises(NotFound):
        bob.tasks.get(task.id)
    with pytest.raises(NotFound):
        bob.tasks.update(task.id, TaskPatch(title="Piraté"))


def test_sharing_gives_edit_but_not_delete(alice, bob):
    task = alice.tasks.create(TaskCreate(title="Commun"))
    shared = alice.tasks.set_shares(task.id, [bob.actor.id])
    assert shared.shared_with == [bob.actor.id]
    assert titles(bob.tasks.list()) == ["Commun"]
    assert titles(bob.tasks.list(TaskFilter(scope="shared"))) == ["Commun"]
    assert bob.tasks.list(TaskFilter(scope="mine")) == []
    bob.tasks.update(task.id, TaskPatch(notes="vu par Bob"))
    assert alice.tasks.get(task.id).notes == "vu par Bob"
    assert not bob.tasks.get(task.id).can_delete
    with pytest.raises(Forbidden):
        bob.tasks.delete(task.id)
    with pytest.raises(Forbidden):
        bob.tasks.set_shares(task.id, [])


def test_subtasks_follow_parent_visibility(alice, bob):
    parent = alice.tasks.create(TaskCreate(title="P"))
    alice.tasks.create(TaskCreate(title="S", parent_id=parent.id))
    assert bob.tasks.list(TaskFilter(include_subtasks=True)) == []
    alice.tasks.set_shares(parent.id, [bob.actor.id])
    assert titles(bob.tasks.list(TaskFilter(include_subtasks=True))) == ["P", "S"]
    # Bob ajoute une sous-tâche : Alice la voit et peut la supprimer (propriétaire du parent).
    bobs = bob.tasks.create(TaskCreate(title="De Bob", parent_id=parent.id))
    assert alice.tasks.get(bobs.id).can_delete
    alice.tasks.delete(bobs.id)


# --- filtres et tri ---------------------------------------------------------------------------------------


@pytest.fixture
def sample(alice, project):
    tag = alice.tags.create(TagIn(name="Urgent client"))
    alice.tasks.create(
        TaskCreate(
            title="Payer la facture",
            importance=Importance.CRITICAL,
            urgency=Urgency.IMMEDIATE,
            due_date=TODAY - timedelta(days=1),
            tag_ids=[tag.id],
        )
    )
    alice.tasks.create(
        TaskCreate(title="Réparer la tâche du mur", due_date=TODAY, project_id=project.id, notes="peinture")
    )
    alice.tasks.create(
        TaskCreate(title="Lire un livre", importance=Importance.MINOR, urgency=Urgency.WHENEVER)
    )
    alice.tasks.create(
        TaskCreate(title="Suivre colis", kind=TaskKind.FOLLOWUP, due_date=TODAY + timedelta(days=12))
    )
    return {"tag": tag}


def test_text_filter_is_accent_insensitive_and_searches_notes_tags_projects(alice, sample):
    assert titles(alice.tasks.list(TaskFilter(text="tache"))) == ["Réparer la tâche du mur"]
    assert titles(alice.tasks.list(TaskFilter(text="PEINTURE"))) == ["Réparer la tâche du mur"]
    assert titles(alice.tasks.list(TaskFilter(text="client"))) == ["Payer la facture"]
    assert titles(alice.tasks.list(TaskFilter(text="maison"))) == ["Réparer la tâche du mur"]
    assert titles(alice.tasks.list(TaskFilter(text="la mur"))) == ["Réparer la tâche du mur"]


def test_attribute_filters(alice, sample, project):
    assert titles(alice.tasks.list(TaskFilter(importance=[Importance.MINOR]))) == ["Lire un livre"]
    assert titles(alice.tasks.list(TaskFilter(kind=[TaskKind.FOLLOWUP]))) == ["Suivre colis"]
    assert titles(alice.tasks.list(TaskFilter(due=[DueBucket.OVERDUE, DueBucket.TODAY]))) == [
        "Payer la facture",
        "Réparer la tâche du mur",
    ]
    assert titles(alice.tasks.list(TaskFilter(tag_ids=[sample["tag"].id]))) == ["Payer la facture"]
    assert titles(alice.tasks.list(TaskFilter(project_ids=[project.id]))) == ["Réparer la tâche du mur"]
    assert len(alice.tasks.list(TaskFilter(project_ids=[None]))) == 3


def test_sorting(alice, sample):
    assert titles(alice.tasks.list(sort=TaskSort(key="due"))) == [
        "Payer la facture",
        "Réparer la tâche du mur",
        "Suivre colis",
        "Lire un livre",  # sans échéance : en dernier
    ]
    assert titles(alice.tasks.list(sort=TaskSort(key="priority")))[0] == "Payer la facture"
    assert titles(alice.tasks.list(sort=TaskSort(key="priority", descending=True)))[0] == "Lire un livre"
    assert titles(alice.tasks.list(sort=TaskSort(key="title"))) == [
        "Lire un livre",
        "Payer la facture",
        "Réparer la tâche du mur",
        "Suivre colis",
    ]
    with pytest.raises(InvalidOperation):
        alice.tasks.list(sort=TaskSort(key="n_importe_quoi"))


# --- liens ------------------------------------------------------------------------------------------------


def test_links_crud(alice):
    task = alice.tasks.create(TaskCreate(title="T"))
    url = alice.tasks.add_link(task.id, LinkIn(kind=LinkKind.URL, target="https://example.org", label="Site"))
    alice.tasks.add_link(task.id, LinkIn(kind=LinkKind.PATH, target="/home/moi/doc.pdf"))
    assert [link.kind for link in alice.tasks.get(task.id).links] == [LinkKind.URL, LinkKind.PATH]
    alice.tasks.update_link(url.id, LinkPatch(label="Exemple"))
    assert alice.tasks.get(task.id).links[0].label == "Exemple"
    alice.tasks.remove_link(url.id)
    assert len(alice.tasks.get(task.id).links) == 1


def test_links_of_invisible_task_are_protected(alice, bob):
    task = alice.tasks.create(TaskCreate(title="T"))
    link = alice.tasks.add_link(task.id, LinkIn(kind=LinkKind.URL, target="https://example.org"))
    with pytest.raises(NotFound):
        bob.tasks.remove_link(link.id)
    with pytest.raises(NotFound):
        bob.tasks.add_link(task.id, LinkIn(kind=LinkKind.URL, target="https://evil.example"))


def test_unknown_date_is_kept_as_date(alice):
    task = alice.tasks.create(TaskCreate(title="T", due_date=date(2027, 1, 31)))
    assert alice.tasks.get(task.id).due_date == date(2027, 1, 31)


# --- duplication ------------------------------------------------------------------------------------------


def test_duplicate_copies_content_and_subtasks(alice):
    tag = alice.tags.create(TagIn(name="maison"))
    source = alice.tasks.create(
        TaskCreate(
            title="Repeindre",
            importance=Importance.CRITICAL,
            due_date=TODAY,
            notes="- [ ] acheter",
            tag_ids=[tag.id],
            status=Status.IN_PROGRESS,
        )
    )
    alice.tasks.add_link(source.id, LinkIn(kind=LinkKind.URL, target="https://example.org"))
    alice.tasks.create(TaskCreate(title="Poncer", parent_id=source.id, status=Status.DONE))
    copy = alice.tasks.duplicate(source.id)
    assert copy.title == "Repeindre (copie)"
    assert copy.id != source.id
    assert (copy.importance, copy.due_date, copy.notes) == (Importance.CRITICAL, TODAY, "- [ ] acheter")
    assert copy.status is Status.NOT_STARTED
    assert [t.name for t in copy.tags] == ["maison"]
    assert [link.target for link in copy.links] == ["https://example.org"]
    subs = alice.tasks.subtasks(copy.id)
    assert [(s.title, s.status) for s in subs] == [("Poncer", Status.NOT_STARTED)]
    alice.undo.undo()  # une seule action annule tout
    assert titles(alice.tasks.list(TaskFilter(include_subtasks=True))) == ["Repeindre", "Poncer"]


def test_duplicate_shared_task_belongs_to_me_without_private_labels(alice, bob):
    secret = alice.tags.create(TagIn(name="secret"))
    task = alice.tasks.create(TaskCreate(title="Commun", tag_ids=[secret.id]))
    alice.tasks.set_shares(task.id, [bob.actor.id])
    copy = bob.tasks.duplicate(task.id)
    assert copy.owner_id == bob.actor.id
    assert copy.tags == []
    with pytest.raises(NotFound):
        alice.tasks.get(copy.id)


def test_move_reorders_and_tunes_urgency(alice):
    a = alice.tasks.create(TaskCreate(title="A", urgency=Urgency(3)))
    b = alice.tasks.create(TaskCreate(title="B", urgency=Urgency(3)))
    c = alice.tasks.create(TaskCreate(title="C", urgency=Urgency(3)))
    low = alice.tasks.create(TaskCreate(title="Bas", urgency=Urgency(1)))

    def column():
        return titles(alice.tasks.list(TaskFilter(), TaskSort(key="urgency")))

    assert column() == ["A", "B", "C", "Bas"]
    alice.tasks.move(c.id, order=[c.id, a.id, b.id, low.id])  # C en tête de son groupe
    assert column() == ["C", "A", "B", "Bas"]
    moved = alice.tasks.move(low.id, order=[c.id, low.id, a.id, b.id])  # « Bas » remonté entre C et A
    assert moved.urgency == 3 and column() == ["C", "Bas", "A", "B"]
    assert alice.undo.status().undo_label == "Reclasser « Bas » (urgence : ⏰ Pressant)"
    alice.undo.undo()
    assert alice.tasks.get(low.id).urgency == 1 and column() == ["C", "A", "B", "Bas"]


def test_move_with_patch_is_one_undo_step(alice):
    a = alice.tasks.create(TaskCreate(title="A", urgency=Urgency(4), status=Status.IN_PROGRESS))
    b = alice.tasks.create(TaskCreate(title="B", urgency=Urgency(2)))
    moved = alice.tasks.move(b.id, TaskPatch(status=Status.IN_PROGRESS), order=[b.id, a.id])
    assert moved.status is Status.IN_PROGRESS and moved.urgency == 4
    alice.undo.undo()
    back = alice.tasks.get(b.id)
    assert back.status is Status.NOT_STARTED and back.urgency == 2
    with pytest.raises(InvalidOperation):
        alice.tasks.move(b.id, order=[a.id])


def test_move_refuses_invisible_tasks(alice, bob):
    mine = alice.tasks.create(TaskCreate(title="A"))
    secret = bob.tasks.create(TaskCreate(title="secret"))
    with pytest.raises(NotFound):
        alice.tasks.move(mine.id, order=[secret.id, mine.id])
    alice.tasks.delete(mine.id)  # le rang éventuel part avec la tâche


def test_followup_uses_current_offset_setting(alice, users):
    from organizer.core.schemas import ProfilePatch

    users.update_profile(alice.actor.id, ProfilePatch(reminder_offset_days=5))  # changé ailleurs
    task = alice.tasks.create(TaskCreate(title="Relancer", kind=TaskKind.FOLLOWUP))
    assert task.reminder_offset_days == 5
