"""Projets et tags : public / privé, unicité, suppression, fusion."""

from __future__ import annotations

import pytest

from organizer.core.errors import Forbidden, InvalidOperation, NotFound
from organizer.core.schemas import ProjectIn, ProjectPatch, TagIn, TagPatch, TaskCreate, TaskPatch


def names(items):
    return [i.name for i in items]


def test_private_and_public_visibility(alice, bob):
    alice.projects.create(ProjectIn(name="Perso"))
    alice.projects.create(ProjectIn(name="Équipe", is_public=True))
    assert names(alice.projects.list()) == ["Perso", "Équipe"]
    assert names(bob.projects.list()) == ["Équipe"]


def test_edit_rights(alice, bob, users):
    public = bob.projects.create(ProjectIn(name="De Bob", is_public=True))
    private = bob.tags.create(TagIn(name="bob-privé"))
    # Alice est admin : elle peut modifier un élément public d'un autre, pas un privé (invisible).
    assert alice.projects.get(public.id).can_edit
    alice.projects.update(public.id, ProjectPatch(emoji="🚀"))
    with pytest.raises(NotFound):
        alice.tags.update(private.id, TagPatch(name="x"))
    # Bob (non admin) ne peut pas modifier un élément public d'Alice.
    alices = alice.tags.create(TagIn(name="commun", is_public=True))
    assert not bob.tags.get(alices.id).can_edit
    with pytest.raises(Forbidden):
        bob.tags.update(alices.id, TagPatch(color="#000000"))


def test_unique_names_among_visible(alice, bob):
    alice.tags.create(TagIn(name="Travail"))
    with pytest.raises(InvalidOperation):
        alice.tags.create(TagIn(name="travail"))
    bob.tags.create(TagIn(name="Travail"))  # privé d'Alice invisible pour Bob : autorisé
    public = alice.projects.create(ProjectIn(name="Commun", is_public=True))
    with pytest.raises(InvalidOperation):
        bob.projects.create(ProjectIn(name="COMMUN"))
    other = alice.projects.create(ProjectIn(name="Autre"))
    with pytest.raises(InvalidOperation):
        alice.projects.update(other.id, ProjectPatch(name="commun"))
    alice.projects.update(public.id, ProjectPatch(name="Commun"))  # se renommer à l'identique : ok


def test_archived_projects_hidden_by_default(alice):
    p = alice.projects.create(ProjectIn(name="Vieux"))
    alice.projects.update(p.id, ProjectPatch(archived=True))
    assert alice.projects.list() == []
    assert names(alice.projects.list(include_archived=True)) == ["Vieux"]


def test_reorder(alice):
    ids = [alice.tags.create(TagIn(name=n)).id for n in ("a", "b", "c")]
    alice.tags.reorder([ids[2], ids[0], ids[1]])
    assert names(alice.tags.list()) == ["c", "a", "b"]


def test_delete_project_clears_tasks(alice):
    p = alice.projects.create(ProjectIn(name="P"))
    task = alice.tasks.create(TaskCreate(title="T", project_id=p.id))
    alice.projects.delete(p.id)
    assert alice.tasks.get(task.id).project is None


def test_task_cannot_use_invisible_project_or_tag(alice, bob):
    secret_project = alice.projects.create(ProjectIn(name="Secret"))
    secret_tag = alice.tags.create(TagIn(name="secret"))
    with pytest.raises(NotFound):
        bob.tasks.create(TaskCreate(title="T", project_id=secret_project.id))
    with pytest.raises(NotFound):
        bob.tasks.create(TaskCreate(title="T", tag_ids=[secret_tag.id]))


def test_private_labels_hidden_and_preserved_on_shared_task(alice, bob):
    private_tag = alice.tags.create(TagIn(name="perso"))
    public_tag = alice.tags.create(TagIn(name="équipe", is_public=True))
    private_project = alice.projects.create(ProjectIn(name="Perso"))
    task = alice.tasks.create(
        TaskCreate(title="T", tag_ids=[private_tag.id, public_tag.id], project_id=private_project.id)
    )
    alice.tasks.set_shares(task.id, [bob.actor.id])

    seen_by_bob = bob.tasks.get(task.id)
    assert names(seen_by_bob.tags) == ["équipe"]
    assert seen_by_bob.project is None

    # Bob retire le tag public et modifie le titre : le tag et le projet privés d'Alice restent.
    bob_tag = bob.tags.create(TagIn(name="bob"))
    bob.tasks.update(task.id, TaskPatch(title="T2", tag_ids=[bob_tag.id]))
    seen_by_alice = alice.tasks.get(task.id)
    assert names(seen_by_alice.tags) == ["perso"]  # le tag privé de Bob est invisible pour Alice
    assert seen_by_alice.project.name == "Perso"
    assert sorted(names(bob.tasks.get(task.id).tags)) == ["bob"]


def test_delete_and_merge_tags(alice):
    a = alice.tags.create(TagIn(name="a"))
    b = alice.tags.create(TagIn(name="b"))
    t1 = alice.tasks.create(TaskCreate(title="t1", tag_ids=[a.id]))
    t2 = alice.tasks.create(TaskCreate(title="t2", tag_ids=[a.id, b.id]))
    merged = alice.tags.merge(a.id, b.id)
    assert merged.name == "b"
    assert names(alice.tasks.get(t1.id).tags) == ["b"]
    assert names(alice.tasks.get(t2.id).tags) == ["b"]
    assert names(alice.tags.list()) == ["b"]
    with pytest.raises(InvalidOperation):
        alice.tags.merge(b.id, b.id)
    alice.tags.delete(b.id)
    assert alice.tasks.get(t1.id).tags == []


def test_new_tags_get_distinct_colors(alice):
    from organizer.core import rules

    first = alice.tags.create(TagIn(name="a"))
    second = alice.tags.create(TagIn(name="b"))
    assert first.color in rules.TAG_PALETTE and second.color in rules.TAG_PALETTE
    assert rules.color_distance(first.color, second.color) > 30
    explicit = alice.tags.create(TagIn(name="c", color="#123456"))
    assert explicit.color == "#123456"
    on_task = alice.tags.create(TagIn(name="d", avoid_colors=[first.color]))
    assert rules.color_distance(on_task.color, first.color) > 30
