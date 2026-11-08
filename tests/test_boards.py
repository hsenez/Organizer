"""Boards personnalisés : colonnes, cartes, ordre, partage, annulation."""

from __future__ import annotations

import pytest

from organizer.core.enums import Status
from organizer.core.errors import Forbidden, InvalidOperation, NotFound
from organizer.core.schemas import BoardIn, BoardPatch, ColumnIn, ColumnPatch, TaskCreate, TaskFilter


def titles(tasks):
    return [t.title for t in tasks]


@pytest.fixture
def board(alice):
    return alice.boards.create(BoardIn(name="Vacances", emoji="🏖️"))


def test_create_with_default_columns(board):
    assert [c.name for c in board.columns] == ["À faire", "En cours", "Fait"]
    assert board.can_manage


def test_place_move_and_order(alice, board):
    todo, doing, _ = (c.id for c in board.columns)
    a, b, c = (alice.tasks.create(TaskCreate(title=n)).id for n in "abc")
    for task_id in (a, b, c):
        alice.boards.place(board.id, task_id, todo)
    content = alice.boards.content(board.id)
    assert titles(content.columns[todo]) == ["a", "b", "c"]
    alice.boards.place(board.id, c, todo, index=0)
    assert titles(alice.boards.content(board.id).columns[todo]) == ["c", "a", "b"]
    alice.boards.place(board.id, a, doing)
    content = alice.boards.content(board.id)
    assert titles(content.columns[todo]) == ["c", "b"]
    assert titles(content.columns[doing]) == ["a"]
    alice.boards.remove(board.id, a)
    assert alice.boards.content(board.id).columns[doing] == []
    assert alice.tasks.get(a).title == "a"  # la tâche existe toujours


def test_task_on_several_boards_and_filter(alice, board):
    other = alice.boards.create(BoardIn(name="Boulot"))
    task = alice.tasks.create(TaskCreate(title="Commun", status=Status.IN_PROGRESS))
    done = alice.tasks.create(TaskCreate(title="Fini", status=Status.DONE))
    alice.boards.place(board.id, task.id, board.columns[0].id)
    alice.boards.place(board.id, done.id, board.columns[0].id)
    alice.boards.place(other.id, task.id, other.columns[1].id)
    assert sorted(alice.boards.boards_of_task(task.id)) == sorted([board.id, other.id])
    only_open = alice.boards.content(board.id, TaskFilter(status=[Status.IN_PROGRESS]))
    assert titles(only_open.columns[board.columns[0].id]) == ["Commun"]


def test_columns_management(alice, board):
    first, second, third = board.columns
    updated = alice.boards.add_column(board.id, ColumnIn(name="Bloqué", emoji="🧱"))
    assert [c.name for c in updated.columns][-1] == "Bloqué"
    alice.boards.update_column(first.id, ColumnPatch(name="Idées"))
    task = alice.tasks.create(TaskCreate(title="T"))
    alice.boards.place(board.id, task.id, second.id)
    after = alice.boards.delete_column(second.id)  # la carte part dans la première colonne restante
    assert second.id not in [c.id for c in after.columns]
    assert titles(alice.boards.content(board.id).columns[first.id]) == ["T"]
    ids = [c.id for c in after.columns]
    reordered = alice.boards.reorder_columns(board.id, list(reversed(ids)))
    assert [c.id for c in reordered.columns] == list(reversed(ids))
    with pytest.raises(InvalidOperation):
        alice.boards.reorder_columns(board.id, ids[:1])
    assert third.id in ids


def test_sharing_gives_access_to_tasks_on_board(alice, bob, board):
    task = alice.tasks.create(TaskCreate(title="Réserver l'hôtel"))
    sub = alice.tasks.create(TaskCreate(title="Comparer", parent_id=task.id))
    alice.boards.place(board.id, task.id, board.columns[0].id)
    with pytest.raises(NotFound):
        bob.boards.get(board.id)
    with pytest.raises(NotFound):
        bob.tasks.get(task.id)
    alice.boards.set_shares(board.id, [bob.actor.id])
    assert [b.name for b in bob.boards.list()] == ["Vacances"]
    assert bob.tasks.get(task.id).title == "Réserver l'hôtel"
    assert bob.tasks.get(sub.id).parent_id == task.id  # sous-tâche visible via le parent
    content = bob.boards.content(board.id)
    assert titles(content.columns[board.columns[0].id]) == ["Réserver l'hôtel"]
    # Un membre peut déplacer les cartes, pas gérer le board.
    bob.boards.place(board.id, task.id, board.columns[1].id)
    assert not bob.boards.get(board.id).can_manage
    with pytest.raises(Forbidden):
        bob.boards.update(board.id, BoardPatch(name="Piraté"))
    with pytest.raises(Forbidden):
        bob.boards.delete(board.id)
    # Retirer la tâche du board retire l'accès.
    alice.boards.remove(board.id, task.id)
    with pytest.raises(NotFound):
        bob.tasks.get(task.id)


def test_delete_task_removes_its_cards(alice, board):
    task = alice.tasks.create(TaskCreate(title="T"))
    alice.boards.place(board.id, task.id, board.columns[0].id)
    alice.tasks.delete(task.id)
    assert alice.boards.content(board.id).columns[board.columns[0].id] == []
    alice.undo.undo()
    assert titles(alice.boards.content(board.id).columns[board.columns[0].id]) == ["T"]


def test_undo_board_operations(alice, board):
    task = alice.tasks.create(TaskCreate(title="T"))
    todo, doing, _ = (c.id for c in board.columns)
    alice.boards.place(board.id, task.id, todo)
    alice.boards.place(board.id, task.id, doing)
    alice.undo.undo()
    assert titles(alice.boards.content(board.id).columns[todo]) == ["T"]
    alice.boards.delete(board.id)
    assert alice.boards.list() == []
    alice.undo.undo()
    restored = alice.boards.content(board.id)
    assert restored.board.name == "Vacances" and titles(restored.columns[todo]) == ["T"]


def test_cannot_place_in_foreign_column(alice, board):
    other = alice.boards.create(BoardIn(name="Autre"))
    task = alice.tasks.create(TaskCreate(title="T"))
    with pytest.raises(InvalidOperation):
        alice.boards.place(board.id, task.id, other.columns[0].id)
