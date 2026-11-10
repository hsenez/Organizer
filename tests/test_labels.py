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


# --- même nom : privé d'un autre utilisateur / public ----------------------------------------------------


def test_public_name_conflict_notifies_private_owner(alice, bob):
    from organizer.core.schemas import TagPatch

    mine = bob.tags.create(TagIn(name="Sport", color="#40c057"))
    theirs = alice.tags.create(TagIn(name="sport", color="#fa5252"))  # privé de Bob : invisible, permis
    assert bob.notifications.list() == []
    alice.tags.update(theirs.id, TagPatch(is_public=True))
    [n] = bob.notifications.list()
    assert (n.kind, n.item_type, n.item_id, n.actor_name, n.available) == (
        "conflict",
        "tag",
        mine.id,
        "Alice",
        True,
    )
    assert bob.notifications.conflict_target("tag", mine.id) == theirs.id
    alice.tags.update(theirs.id, TagPatch(color="#000000"))  # rien de nouveau tant que non lue
    assert len(bob.notifications.list()) == 1
    # Renommer le sien : plus de conflit.
    bob.tags.update(mine.id, TagPatch(name="Sport perso"))
    assert not bob.notifications.list()[0].available
    assert bob.notifications.conflict_target("tag", mine.id) is None


def test_two_public_labels_with_the_same_name_are_refused(alice, bob):
    from organizer.core.schemas import ProjectPatch, TagPatch

    bob_tag = bob.tags.create(TagIn(name="Courses"))
    alice.tags.create(TagIn(name="courses", is_public=True))
    with pytest.raises(InvalidOperation, match="fusionnez"):
        bob.tags.update(bob_tag.id, TagPatch(is_public=True))
    bob_project = bob.projects.create(ProjectIn(name="Maison"))
    alice.projects.create(ProjectIn(name="Maison", is_public=True))  # notifie Bob
    assert [n.item_type for n in bob.notifications.list()] == ["project", "tag"]
    with pytest.raises(InvalidOperation):
        bob.projects.update(bob_project.id, ProjectPatch(is_public=True))


def test_merge_private_project_into_public(alice, bob):
    from datetime import date

    from organizer.core.schemas import EventCreate

    public = alice.projects.create(ProjectIn(name="Club", is_public=True))
    mine = bob.projects.create(ProjectIn(name="Club perso"))
    task = bob.tasks.create(TaskCreate(title="Cotisation", project_id=mine.id))
    event = bob.agenda.create(
        EventCreate(title="Assemblée", start_date=date(2026, 11, 20), project_id=mine.id)
    )
    merged = bob.projects.merge(mine.id, public.id)
    assert merged.id == public.id
    assert bob.tasks.get(task.id).project.id == public.id
    assert bob.agenda.get(event.id).project.id == public.id
    assert [p.name for p in bob.projects.list()] == ["Club"]
    bob.undo.undo()
    assert bob.tasks.get(task.id).project.id == mine.id
    with pytest.raises(Forbidden):
        bob.projects.merge(public.id, mine.id)  # le public d'Alice ne lui appartient pas
