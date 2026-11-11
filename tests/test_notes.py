"""Notes (NoteService) : création, droits (partage modifiable ou non, publique en lecture), épingles
personnelles, filtres, liens internes (résolution, liens retour), tags / projets, annulation,
notifications."""

from __future__ import annotations

from datetime import date, time

import pytest

from organizer.core import rules
from organizer.core.errors import Forbidden, InvalidOperation, NotFound
from organizer.core.schemas import (
    EventCreate,
    NoteCreate,
    NoteFilter,
    NotePatch,
    ProjectIn,
    ShareSpec,
    TagIn,
    TaskCreate,
)


def note(sv, title="Courses", **extra):
    return sv.notes.create(NoteCreate(title=title, **extra))


# --- règles pures ---------------------------------------------------------------------------------------


def test_refs_rules():
    assert rules.parse_ref("note:5") == ("note", 5)
    assert rules.parse_ref(" task:12 ") == ("task", 12)
    assert rules.parse_ref("note:x") is None and rules.parse_ref("https://a.fr") is None
    text = "Voir [pain](task:3), [réunion](event:8) puis [x](note:5) et encore [pain](task:3) ; [y](note:55)"
    assert rules.refs_in(text) == ["task:3", "event:8", "note:5", "note:55"]
    assert rules.ref_link("note", 5, "Liste [courses]\n bis") == "[Liste (courses) bis](note:5)"
    assert rules.parse_emojis("📝  💡 📝 ") == ["📝", "💡"]
    assert rules.parse_emojis(["a", "", "a", "b"]) == ["a", "b"]


# --- création, modification ------------------------------------------------------------------------------


def test_create_update_and_defaults(alice):
    created = note(alice, notes="- [ ] lait", emoji="🛒")
    assert created.owner_id == alice.actor.id and created.can_edit and created.can_delete
    assert (created.title, created.notes, created.emoji, created.is_public, created.pinned) == (
        "Courses",
        "- [ ] lait",
        "🛒",
        False,
        False,
    )
    assert note(alice, "Sans emoji", emoji="  ").emoji == "📝"
    updated = alice.notes.update(created.id, NotePatch(title="Courses du samedi", notes="- [x] lait"))
    assert (updated.title, updated.notes) == ("Courses du samedi", "- [x] lait")
    with pytest.raises(InvalidOperation):
        alice.notes.update(created.id, NotePatch(title="   "))
    with pytest.raises(InvalidOperation):
        alice.notes.create(NoteCreate(title="  "))


def test_project_and_tags(alice, bob):
    project = alice.projects.create(ProjectIn(name="Maison"))
    tag = alice.tags.create(TagIn(name="urgent"))
    created = note(alice, project_id=project.id, tag_ids=[tag.id])
    assert created.project.id == project.id and [t.id for t in created.tags] == [tag.id]
    assert [n.id for n in alice.notes.list(NoteFilter(tag_ids=[tag.id]))] == [created.id]
    assert [n.id for n in alice.notes.list(NoteFilter(project_ids=[project.id]))] == [created.id]
    assert alice.notes.list(NoteFilter(project_ids=[None])) == []
    # Supprimer le tag ou le projet : la note les perd.
    alice.tags.delete(tag.id)
    alice.projects.delete(project.id)
    again = alice.notes.get(created.id)
    assert again.tags == [] and again.project is None


def test_merge_tags_and_projects_moves_notes(alice):
    a, b = alice.tags.create(TagIn(name="a")), alice.tags.create(TagIn(name="b"))
    p1, p2 = alice.projects.create(ProjectIn(name="P1")), alice.projects.create(ProjectIn(name="P2"))
    created = note(alice, tag_ids=[a.id], project_id=p1.id)
    alice.tags.merge(a.id, b.id)
    alice.projects.merge(p1.id, p2.id)
    again = alice.notes.get(created.id)
    assert [t.id for t in again.tags] == [b.id] and again.project.id == p2.id


# --- droits ----------------------------------------------------------------------------------------------


def test_private_by_default(alice, bob):
    created = note(alice)
    assert bob.notes.list() == []
    with pytest.raises(NotFound):
        bob.notes.get(created.id)


def test_share_editable_or_read_only(alice, bob):
    created = note(alice)
    shared = alice.notes.set_shares(created.id, [ShareSpec(user_id=bob.actor.id, can_edit=False)])
    assert shared.shared_with == [bob.actor.id] and not shared.shares[0].can_edit
    seen = bob.notes.get(created.id)
    assert not seen.can_edit and not seen.can_delete
    with pytest.raises(Forbidden):
        bob.notes.update(created.id, NotePatch(notes="non"))
    with pytest.raises(Forbidden):
        bob.notes.delete(created.id)
    with pytest.raises(Forbidden):
        bob.notes.set_shares(created.id, [])

    alice.notes.set_shares(created.id, [ShareSpec(user_id=bob.actor.id, can_edit=True)])
    assert bob.notes.update(created.id, NotePatch(notes="oui")).notes == "oui"
    with pytest.raises(Forbidden):  # rendre publique : propriétaire seulement
        bob.notes.update(created.id, NotePatch(is_public=True))
    bob.notes.delete(created.id)  # un partage modifiable peut supprimer
    assert alice.notes.list() == []


def test_public_is_read_only_for_others(alice, bob):
    created = note(alice, is_public=True)
    seen = bob.notes.get(created.id)
    assert seen.is_public and not seen.can_edit
    with pytest.raises(Forbidden):
        bob.notes.update(created.id, NotePatch(title="Piraté"))
    assert [n.id for n in bob.notes.list(NoteFilter(scope="shared"))] == [created.id]
    assert bob.notes.list(NoteFilter(scope="mine")) == []


# --- liste, épingles -------------------------------------------------------------------------------------


def test_list_order_pins_and_search(alice, bob):
    first = note(alice, "Recettes", notes="Tarte aux pommes")
    second = note(alice, "Idées cadeaux")
    third = note(alice, "Vacances")
    assert [n.id for n in alice.notes.list()] == [third.id, second.id, first.id]  # récentes d'abord
    pinned = alice.notes.set_pinned(first.id, True)
    assert pinned.pinned
    assert [n.id for n in alice.notes.list()] == [first.id, third.id, second.id]
    assert [n.id for n in alice.notes.list(NoteFilter(text="POMME"))] == [first.id]
    # L'épingle est personnelle.
    alice.notes.set_shares(first.id, [ShareSpec(user_id=bob.actor.id)])
    assert not bob.notes.get(first.id).pinned
    bob.notes.set_pinned(first.id, True)
    alice.notes.set_pinned(first.id, False)
    assert bob.notes.get(first.id).pinned and not alice.notes.get(first.id).pinned
    # Ne plus partager retire son épingle ; supprimer la note retire les épingles.
    alice.notes.set_shares(first.id, [])
    alice.notes.set_shares(first.id, [ShareSpec(user_id=bob.actor.id)])
    assert not bob.notes.get(first.id).pinned
    alice.notes.delete(first.id)


# --- liens internes --------------------------------------------------------------------------------------


def test_resolve_refs(alice, bob):
    task = alice.tasks.create(TaskCreate(title="Acheter du pain"))
    event = alice.agenda.create(
        EventCreate(title="Réunion", start_date=date(2026, 11, 12), start_time=time(9))
    )
    target = note(alice, "Recettes", emoji="🍳")
    secret = note(bob, "Secret")
    refs = alice.notes.resolve(
        [f"task:{task.id}", f"event:{event.id}", f"note:{target.id}", f"note:{secret.id}", "task:999", "x"]
    )
    assert [(r.ref, r.title, r.emoji, r.available) for r in refs] == [
        (f"task:{task.id}", "Acheter du pain", "📋", True),
        (f"event:{event.id}", "Réunion", "📅", True),
        (f"note:{target.id}", "Recettes", "🍳", True),
        (f"note:{secret.id}", "", "📝", False),  # note privée de Bob : ni titre ni existence
        ("task:999", "", "📋", False),
    ]


def test_backlinks(alice, bob):
    target = note(alice, "Recettes")
    ref = f"note:{target.id}"
    citing = note(alice, "Menu", notes=f"Voir [les recettes]({ref})")
    note(alice, "Faux ami", notes=f"[x](note:{target.id}0)")  # note:50 ≠ note:5
    task = alice.tasks.create(TaskCreate(title="Cuisiner", notes=f"[recettes]({ref})"))
    private = note(bob, "Chez Bob", notes=f"[recettes]({ref})")  # invisible pour Alice
    note(alice, "Elle-même")
    alice.notes.update(target.id, NotePatch(notes=f"Moi : [moi]({ref})"))  # se cite : ignoré
    found = alice.notes.backlinks(ref)
    assert [(r.kind, r.id) for r in found] == [("note", citing.id), ("task", task.id)]
    assert private.id not in [r.id for r in found]
    with pytest.raises(InvalidOperation):
        alice.notes.backlinks("n'importe quoi")


# --- annulation, notifications ---------------------------------------------------------------------------


def test_undo_create_update_and_pin(alice):
    created = note(alice)
    alice.notes.update(created.id, NotePatch(notes="texte"))
    alice.notes.set_pinned(created.id, True)
    alice.undo.undo()
    assert not alice.notes.get(created.id).pinned
    alice.undo.undo()
    assert alice.notes.get(created.id).notes == ""
    alice.undo.undo()
    assert alice.notes.list() == []
    alice.undo.redo()
    assert alice.notes.get(created.id).title == "Courses"


def test_notifications(alice, bob):
    created = note(alice)
    alice.notes.set_shares(created.id, [ShareSpec(user_id=bob.actor.id)])
    [shared] = bob.notifications.list()
    assert (shared.kind, shared.item_type, shared.item_id, shared.available) == (
        "share",
        "note",
        created.id,
        True,
    )
    bob.notes.update(created.id, NotePatch(notes="du lait"))
    [change] = alice.notifications.list()
    assert (change.kind, change.item_type) == ("change", "note")
    bob.notes.set_pinned(created.id, True)  # épingler ne concerne que soi
    assert len(alice.notifications.list()) == 1
    alice.notes.delete(created.id)
    assert bob.notifications.list()[0].kind == "delete"
