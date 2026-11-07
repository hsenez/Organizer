"""Historique annuler / rétablir."""

from __future__ import annotations

import pytest

from organizer.config import Settings
from organizer.core.enums import LinkKind, Status
from organizer.core.errors import UndoConflict
from organizer.core.schemas import LinkIn, ProjectIn, TagIn, TaskCreate, TaskFilter, TaskPatch
from organizer.core.services import Services


def titles(tasks):
    return [t.title for t in tasks]


def test_nothing_to_undo(alice):
    assert alice.undo.undo() is None
    assert alice.undo.redo() is None
    status = alice.undo.status()
    assert status.undo_label is None and status.redo_label is None


def test_undo_redo_create(alice):
    task = alice.tasks.create(TaskCreate(title="T"))
    assert alice.undo.status().undo_label == "Créer « T »"
    result = alice.undo.undo()
    assert result.action == "undo" and result.task_ids == [task.id]
    assert alice.tasks.list() == []
    assert alice.undo.status().redo_label == "Créer « T »"
    alice.undo.redo()
    assert titles(alice.tasks.list()) == ["T"]


def test_undo_update_restores_previous_values(alice):
    task = alice.tasks.create(TaskCreate(title="T"))
    alice.tasks.update(task.id, TaskPatch(status=Status.DONE, notes="fini"))
    alice.undo.undo()
    restored = alice.tasks.get(task.id)
    assert restored.status is Status.NOT_STARTED
    assert restored.notes == ""
    assert restored.completed_at is None
    assert restored.updated_at == task.updated_at


def test_undo_delete_restores_subtasks_tags_and_links(alice):
    tag = alice.tags.create(TagIn(name="x"))
    parent = alice.tasks.create(TaskCreate(title="P", tag_ids=[tag.id]))
    sub = alice.tasks.create(TaskCreate(title="S", parent_id=parent.id, tag_ids=[tag.id]))
    alice.tasks.add_link(sub.id, LinkIn(kind=LinkKind.URL, target="https://example.org"))
    alice.tasks.delete(parent.id, with_subtasks=True)
    assert alice.tasks.list(TaskFilter(include_subtasks=True)) == []

    alice.undo.undo()
    restored_parent = alice.tasks.get(parent.id)
    restored_sub = alice.tasks.get(sub.id)
    assert restored_parent.subtask_count == 1
    assert [t.name for t in restored_parent.tags] == ["x"]
    assert restored_sub.parent_id == parent.id
    assert [link.target for link in restored_sub.links] == ["https://example.org"]

    alice.undo.redo()
    assert alice.tasks.list(TaskFilter(include_subtasks=True)) == []


def test_undo_attach(alice):
    parent = alice.tasks.create(TaskCreate(title="P"))
    child = alice.tasks.create(TaskCreate(title="C", status=Status.IN_PROGRESS))
    alice.tasks.attach(child.id, parent.id)
    assert alice.undo.status().undo_label == "Rattacher « C » à « P »"
    alice.undo.undo()
    assert alice.tasks.get(child.id).parent_id is None
    assert alice.tasks.get(parent.id).status is Status.NOT_STARTED  # l'automatisme est annulé aussi


def test_undo_order_is_lifo_and_new_action_clears_redo(alice):
    a = alice.tasks.create(TaskCreate(title="A"))
    alice.tasks.update(a.id, TaskPatch(title="A2"))
    alice.tasks.update(a.id, TaskPatch(title="A3"))
    alice.undo.undo()
    alice.undo.undo()
    assert alice.tasks.get(a.id).title == "A"
    alice.undo.redo()
    assert alice.tasks.get(a.id).title == "A2"
    alice.tasks.update(a.id, TaskPatch(notes="nouveau"))
    assert alice.undo.status().redo_label is None
    assert alice.undo.redo() is None


def test_project_and_tag_operations_are_undoable(alice):
    project = alice.projects.create(ProjectIn(name="P"))
    task = alice.tasks.create(TaskCreate(title="T", project_id=project.id))
    alice.projects.delete(project.id)
    alice.undo.undo()
    assert alice.tasks.get(task.id).project.name == "P"
    a = alice.tags.create(TagIn(name="a"))
    b = alice.tags.create(TagIn(name="b"))
    alice.tasks.update(task.id, TaskPatch(tag_ids=[a.id]))
    alice.tags.merge(a.id, b.id)
    alice.undo.undo()
    assert [t.name for t in alice.tasks.get(task.id).tags] == ["a"]
    assert sorted(t.name for t in alice.tags.list()) == ["a", "b"]


def test_histories_are_per_user(alice, bob):
    alice.tasks.create(TaskCreate(title="A"))
    bob.tasks.create(TaskCreate(title="B"))
    alice.undo.undo()
    assert alice.tasks.list() == []
    assert titles(bob.tasks.list()) == ["B"]


def test_conflict_when_someone_else_changed_the_row(alice, bob):
    task = alice.tasks.create(TaskCreate(title="T"))
    alice.tasks.set_shares(task.id, [bob.actor.id])
    alice.tasks.update(task.id, TaskPatch(title="Version Alice"))
    bob.tasks.update(task.id, TaskPatch(title="Version Bob"))
    with pytest.raises(UndoConflict) as conflict:
        alice.undo.undo()
    assert conflict.value.message.startswith("Impossible d'annuler — Renommer « T »")
    assert alice.tasks.get(task.id).title == "Version Bob"  # rien n'est écrasé
    # L'entrée en conflit a été retirée : l'annulation suivante porte sur l'action précédente (le partage).
    assert alice.undo.status().undo_label == "Partager « T »"


def test_history_is_bounded(engine, alice, clock, tmp_path):
    small = Services(
        engine, alice.actor, settings=Settings(data_dir=tmp_path, undo_history_size=3), today=clock
    )
    for i in range(5):
        small.tasks.create(TaskCreate(title=f"T{i}"))
    undone = 0
    while small.undo.undo() is not None:
        undone += 1
    assert undone == 3
    assert sorted(titles(small.tasks.list())) == ["T0", "T1"]


def test_rapid_edits_of_same_field_are_merged(engine, alice, clock, tmp_path):
    merging = Services(
        engine, alice.actor, settings=Settings(data_dir=tmp_path, undo_merge_window_seconds=60), today=clock
    )
    task = merging.tasks.create(TaskCreate(title="T"))
    for text in ("a", "ab", "abc"):
        merging.tasks.update(task.id, TaskPatch(notes=text))
    merging.tasks.update(task.id, TaskPatch(title="T2"))  # autre champ : nouvelle entrée
    merging.undo.undo()
    assert merging.tasks.get(task.id).title == "T"
    assert merging.tasks.get(task.id).notes == "abc"
    merging.undo.undo()  # une seule annulation pour les trois frappes
    assert merging.tasks.get(task.id).notes == ""
    merging.undo.undo()
    assert merging.tasks.list() == []


def test_merged_edits_back_to_start_stay_undoable(engine, alice, clock, tmp_path):
    merging = Services(
        engine, alice.actor, settings=Settings(data_dir=tmp_path, undo_merge_window_seconds=60), today=clock
    )
    task = merging.tasks.create(TaskCreate(title="T"))
    merging.tasks.update(task.id, TaskPatch(notes="x"))
    merging.tasks.update(task.id, TaskPatch(notes=""))
    # Les notes sont revenues à l'identique, mais ``updated_at`` a changé : l'entrée reste annulable
    # et l'annulation suivante concerne bien la modification des notes, pas la création.
    assert merging.undo.status().undo_label == "Modifier les notes de « T »"
