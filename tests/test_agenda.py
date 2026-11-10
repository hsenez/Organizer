"""Événements (AgendaService) : horaires, droits (partage modifiable ou non, public en lecture), filtres,
liens et pièces jointes, conversion tâche ↔ événement, annulation."""

from __future__ import annotations

import io
from datetime import date, time

import pytest

from organizer.core.enums import EVENT_DEFAULT_COLOR, LinkKind
from organizer.core.errors import Forbidden, InvalidOperation, NotFound
from organizer.core.schemas import (
    EventCreate,
    EventFilter,
    EventPatch,
    EventTimes,
    LinkIn,
    LinkPatch,
    ProjectIn,
    ShareSpec,
    TagIn,
    TaskCreate,
    TaskFilter,
)

D = date(2026, 11, 12)


def meeting(sv, **extra):
    values = {"title": "Réunion", "start_date": D, "start_time": time(9, 0), "end_time": time(10, 30)}
    return sv.agenda.create(EventCreate(**{**values, **extra}))


def test_create_timed_and_all_day(alice):
    event = meeting(alice, location="Mairie")
    assert (event.start_date, event.start_time, event.end_date, event.end_time) == (
        D,
        time(9),
        D,
        time(10, 30),
    )
    assert not event.all_day and event.location == "Mairie"
    assert event.owner_id == alice.actor.id and event.can_edit and event.can_delete
    assert event.display_color == EVENT_DEFAULT_COLOR and event.color is None
    one_hour = alice.agenda.create(EventCreate(title="Café", start_date=D, start_time=time(23, 30)))
    assert (one_hour.end_date, one_hour.end_time) == (date(2026, 11, 13), time(0, 30))
    holidays = alice.agenda.create(EventCreate(title="Vacances", start_date=D, end_date=date(2026, 11, 20)))
    assert holidays.all_day and holidays.start_time is None and holidays.end_date == date(2026, 11, 20)
    with pytest.raises(InvalidOperation):
        alice.agenda.create(
            EventCreate(title="À l'envers", start_date=D, start_time=time(9), end_time=time(8))
        )


def test_color_comes_from_project_unless_chosen(alice):
    project = alice.projects.create(ProjectIn(name="Club", color="#12b886"))
    event = meeting(alice, project_id=project.id)
    assert event.display_color == "#12b886"
    event = alice.agenda.update(event.id, EventPatch(color="#e64980"))
    assert event.display_color == "#e64980" and event.color == "#e64980"
    assert alice.agenda.update(event.id, EventPatch(color=None)).display_color == "#12b886"


def test_update_times_and_all_day_switch(alice):
    event = meeting(alice)
    moved = alice.agenda.update(
        event.id, EventPatch(start_date=date(2026, 11, 13), end_date=date(2026, 11, 13))
    )
    assert (moved.start_date, moved.start_time, moved.end_time) == (date(2026, 11, 13), time(9), time(10, 30))
    whole = alice.agenda.update(event.id, EventPatch(start_time=None))
    assert whole.all_day and whole.end_time is None
    timed = alice.agenda.update(event.id, EventPatch(start_time=time(14, 0)))
    assert (timed.start_time, timed.end_date, timed.end_time) == (time(14), date(2026, 11, 13), time(15))
    with pytest.raises(InvalidOperation):
        alice.agenda.update(event.id, EventPatch(end_time=time(13, 0)))
    with pytest.raises(InvalidOperation):
        alice.agenda.update(event.id, EventPatch(title=None))


def test_visibility_shares_and_public(alice, bob):
    private = meeting(alice, title="Privé")
    with pytest.raises(NotFound):
        bob.agenda.get(private.id)
    assert bob.agenda.list() == []

    shared = meeting(alice, title="Partagé")
    shared = alice.agenda.set_shares(shared.id, [ShareSpec(user_id=bob.actor.id, can_edit=False)])
    assert shared.shares == [ShareSpec(user_id=bob.actor.id, can_edit=False)]
    seen = bob.agenda.get(shared.id)
    assert not seen.can_edit and not seen.can_delete
    with pytest.raises(Forbidden):
        bob.agenda.update(shared.id, EventPatch(title="Changé"))
    with pytest.raises(Forbidden):
        bob.agenda.add_link(shared.id, LinkIn(kind=LinkKind.URL, target="exemple.fr"))
    alice.agenda.set_shares(shared.id, [ShareSpec(user_id=bob.actor.id, can_edit=True)])
    assert bob.agenda.update(shared.id, EventPatch(title="Changé par Bob")).title == "Changé par Bob"
    with pytest.raises(Forbidden):
        bob.agenda.delete(shared.id)
    with pytest.raises(Forbidden):
        bob.agenda.set_shares(shared.id, [])
    with pytest.raises(Forbidden):
        bob.agenda.update(shared.id, EventPatch(is_public=True))

    public = meeting(alice, title="Fête du quartier", is_public=True)
    seen = bob.agenda.get(public.id)
    assert seen.is_public and not seen.can_edit
    with pytest.raises(Forbidden):
        bob.agenda.update(public.id, EventPatch(notes="…"))
    assert {e.title for e in bob.agenda.list()} == {"Changé par Bob", "Fête du quartier"}
    assert {e.title for e in bob.agenda.list(EventFilter(scope="mine"))} == set()
    assert len(bob.agenda.list(EventFilter(scope="shared"))) == 2
    assert {e.title for e in alice.agenda.list(EventFilter(scope="shared"))} == set()
    with pytest.raises(NotFound):
        alice.agenda.set_shares(public.id, [ShareSpec(user_id=999)])


def test_list_filters_by_period_text_and_labels(alice):
    tag = alice.tags.create(TagIn(name="sport"))
    meeting(alice, title="Avant", start_date=date(2026, 11, 1), end_date=date(2026, 11, 1))
    meeting(alice, title="Piscine", tag_ids=[tag.id], location="Centre aquatique")
    alice.agenda.create(
        EventCreate(title="Vacances", start_date=date(2026, 11, 10), end_date=date(2026, 11, 20))
    )
    alice.agenda.create(
        EventCreate(
            title="Soirée",
            start_date=date(2026, 11, 13),
            start_time=time(22),
            end_date=date(2026, 11, 14),
            end_time=time(0),
        )
    )
    period = EventFilter(start=date(2026, 11, 12), end=date(2026, 11, 13))
    assert [e.title for e in alice.agenda.list(period)] == ["Vacances", "Piscine", "Soirée"]
    # La soirée finit à minuit pile : elle ne touche pas le 14.
    assert [e.title for e in alice.agenda.list(EventFilter(start=date(2026, 11, 14)))] == ["Vacances"]
    assert [e.title for e in alice.agenda.list(EventFilter(text="aquatique"))] == ["Piscine"]
    assert [e.title for e in alice.agenda.list(EventFilter(tag_ids=[tag.id]))] == ["Piscine"]


def test_private_tags_of_others_are_preserved(alice, bob):
    secret = alice.tags.create(TagIn(name="secret"))
    event = meeting(alice, tag_ids=[secret.id])
    alice.agenda.set_shares(event.id, [ShareSpec(user_id=bob.actor.id)])
    assert bob.agenda.get(event.id).tags == []
    mine = bob.tags.create(TagIn(name="bob"))
    bob.agenda.update(event.id, EventPatch(tag_ids=[mine.id]))
    assert {t.name for t in alice.agenda.get(event.id).tags} == {"secret"}  # celui de Bob est privé
    assert {t.name for t in bob.agenda.get(event.id).tags} == {"bob"}


def test_links_attachments_and_undo(alice, bob):
    event = meeting(alice)
    link = alice.agenda.add_link(event.id, LinkIn(kind=LinkKind.URL, target="exemple.fr"))
    assert link.event_id == event.id and link.task_id is None
    alice.agenda.update_link(link.id, LinkPatch(label="Programme"))
    assert alice.agenda.get(event.id).links[0].label == "Programme"
    file = alice.attachments.upload_event(event.id, "plan.pdf", io.BytesIO(b"%PDF"), "application/pdf")
    assert file.kind is LinkKind.ATTACHMENT and file.event_id == event.id
    with pytest.raises(NotFound):
        bob.attachments.get(file.target)
    alice.agenda.set_shares(event.id, [ShareSpec(user_id=bob.actor.id, can_edit=False)])
    meta, _ = bob.attachments.get(file.target)  # visible par ceux qui voient l'événement
    assert meta.filename == "plan.pdf"
    alice.agenda.remove_link(link.id)
    assert [x.kind for x in alice.agenda.get(event.id).links] == [LinkKind.ATTACHMENT]
    alice.undo.undo()
    assert len(alice.agenda.get(event.id).links) == 2
    alice.agenda.delete(event.id)
    with pytest.raises(NotFound):
        alice.agenda.get(event.id)
    alice.undo.undo()
    assert alice.agenda.get(event.id).title == "Réunion"


def test_task_to_event_and_back(alice, bob):
    project = alice.projects.create(ProjectIn(name="Maison"))
    tag = alice.tags.create(TagIn(name="travaux"))
    task = alice.tasks.create(
        TaskCreate(
            title="Plombier",
            notes="Fuite",
            project_id=project.id,
            tag_ids=[tag.id],
            due_date=D,
            due_time=time(14, 0),
        )
    )
    alice.tasks.add_link(task.id, LinkIn(kind=LinkKind.URL, target="plombier.fr"))
    alice.tasks.set_shares(task.id, [bob.actor.id])

    event = alice.agenda.from_task(task.id)
    assert (event.title, event.notes, event.project.id) == ("Plombier", "Fuite", project.id)
    assert (event.start_date, event.start_time, event.end_time) == (D, time(14), time(15))
    assert [t.name for t in event.tags] == ["travaux"] and event.links[0].target == "plombier.fr"
    assert event.shares == [ShareSpec(user_id=bob.actor.id, can_edit=True)]
    with pytest.raises(NotFound):
        alice.tasks.get(task.id)
    alice.undo.undo()  # une seule action
    assert alice.tasks.get(task.id).title == "Plombier" and alice.agenda.list() == []
    alice.undo.redo()

    back = alice.agenda.to_task(event.id)
    assert (back.title, back.due_date, back.due_time, back.shared_with) == (
        "Plombier",
        D,
        time(14),
        [bob.actor.id],
    )
    assert [t.name for t in back.tags] == ["travaux"] and back.links[0].target == "plombier.fr"
    assert alice.agenda.list() == []

    custom = alice.agenda.from_task(back.id, EventTimes(start_date=D, end_date=date(2026, 11, 13)))
    assert custom.all_day and custom.end_date == date(2026, 11, 13)


def test_conversion_refusals(alice, bob):
    parent = alice.tasks.create(TaskCreate(title="Parent"))
    child = alice.tasks.create(TaskCreate(title="Enfant", parent_id=parent.id))
    for task_id in (parent.id, child.id):
        with pytest.raises(InvalidOperation):
            alice.agenda.from_task(task_id)
    shared = alice.tasks.create(TaskCreate(title="À Alice"))
    alice.tasks.set_shares(shared.id, [bob.actor.id])
    with pytest.raises(Forbidden):
        bob.agenda.from_task(shared.id)
    event = meeting(alice)
    alice.agenda.set_shares(event.id, [ShareSpec(user_id=bob.actor.id)])
    with pytest.raises(Forbidden):
        bob.agenda.to_task(event.id)
    assert len(alice.tasks.list(TaskFilter(include_subtasks=True))) == 3


def test_deleting_or_merging_labels_updates_events(alice):
    project = alice.projects.create(ProjectIn(name="Club"))
    a, b = alice.tags.create(TagIn(name="a")), alice.tags.create(TagIn(name="b"))
    event = meeting(alice, project_id=project.id, tag_ids=[a.id])
    alice.tags.merge(a.id, b.id)
    assert [t.name for t in alice.agenda.get(event.id).tags] == ["b"]
    alice.tags.delete(b.id)
    alice.projects.delete(project.id)
    event = alice.agenda.get(event.id)
    assert event.tags == [] and event.project is None


def test_conversion_applies_extra_fields_in_the_same_action(alice):
    from organizer.core.enums import Importance
    from organizer.core.schemas import TaskPatch

    event = meeting(alice, location="Mairie")
    task = alice.agenda.to_task(event.id, TaskPatch(importance=Importance.CRITICAL))
    assert task.importance == Importance.CRITICAL
    again = alice.agenda.from_task(
        task.id,
        EventTimes(start_date=D, start_time=time(14)),
        EventPatch(location="Gymnase", color="#e64980"),
    )
    assert (again.location, again.display_color, again.end_time) == ("Gymnase", "#e64980", time(15))
    alice.undo.undo()  # une seule action
    assert alice.tasks.get(task.id).importance == Importance.CRITICAL and alice.agenda.list() == []
