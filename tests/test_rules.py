"""Règles métier pures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pytest

from organizer.core import rules
from organizer.core.enums import (
    DueBucket,
    Importance,
    LinkKind,
    Quadrant,
    Status,
    TaskKind,
    Urgency,
)
from organizer.core.errors import InvalidOperation

WED = date(2026, 11, 4)
SAT = date(2026, 11, 7)
SUN = date(2026, 11, 8)


@pytest.mark.parametrize("enum", [Importance, Urgency, Status, TaskKind, LinkKind, DueBucket, Quadrant])
def test_every_enum_value_has_complete_meta(enum):
    for member in enum:
        meta = member.meta
        assert meta.label and meta.emoji and meta.tooltip
        assert meta.color.startswith("#")


def test_normalize_text_ignores_case_and_accents():
    assert rules.normalize_text("Tâche ÉCHÉANCE") == "tache echeance"


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("https://example.org", LinkKind.URL),
        ("www.example.org", LinkKind.URL),
        ("mailto:a@b.c", LinkKind.URL),
        ("obsidian://open?vault=x", LinkKind.URL),
        ("google.fr", LinkKind.URL),
        ("exemple.com/page?x=1", LinkKind.URL),
        ("sub.domaine.co.uk/x", LinkKind.URL),
        ("localhost:2603", LinkKind.URL),
        ("192.168.1.20:2603/tasks", LinkKind.URL),
        ("/home/moi/doc.pdf", LinkKind.PATH),
        ("~/Documents", LinkKind.PATH),
        ("./relatif.txt", LinkKind.PATH),
        (r"C:\Users\moi\doc.pdf", LinkKind.PATH),
        (r"\\nas\partage", LinkKind.PATH),
        ("file:///home/moi", LinkKind.PATH),
        ("notes.txt", LinkKind.PATH),
        ("rapport final.pdf", LinkKind.PATH),
    ],
)
def test_detect_link_kind(text, kind):
    assert rules.detect_link_kind(text) is kind


@pytest.mark.parametrize(
    ("text", "url"),
    [
        ("https://example.org", "https://example.org"),
        ("mailto:a@b.c", "mailto:a@b.c"),
        ("google.fr", "https://google.fr"),
        ("www.example.org/page", "https://www.example.org/page"),
        ("localhost:2603", "http://localhost:2603"),
        ("192.168.1.20:2603/tasks", "http://192.168.1.20:2603/tasks"),
    ],
)
def test_normalize_url(text, url):
    assert rules.normalize_url(text) == url


@pytest.mark.parametrize(
    ("due", "bucket"),
    [
        (None, DueBucket.NONE),
        (WED - timedelta(days=1), DueBucket.OVERDUE),
        (WED, DueBucket.TODAY),
        (WED + timedelta(days=1), DueBucket.TOMORROW),
        (WED + timedelta(days=2), DueBucket.THIS_WEEK),
        (SUN, DueBucket.THIS_WEEK),
        (SUN + timedelta(days=1), DueBucket.LATER),
    ],
)
def test_due_bucket(due, bucket):
    assert rules.due_bucket(due, WED) is bucket


def test_due_drop_targets_on_wednesday():
    assert rules.due_for_bucket_drop(DueBucket.TODAY, WED, None) == WED
    assert rules.due_for_bucket_drop(DueBucket.TOMORROW, WED, None) == WED + timedelta(days=1)
    assert rules.due_for_bucket_drop(DueBucket.THIS_WEEK, WED, None) == date(2026, 11, 6)  # vendredi
    assert rules.due_for_bucket_drop(DueBucket.LATER, WED, None) == WED + timedelta(days=7)
    assert rules.due_for_bucket_drop(DueBucket.NONE, WED, WED) is None


def test_due_drop_keeps_date_already_in_bucket():
    later = WED + timedelta(days=30)
    assert rules.due_for_bucket_drop(DueBucket.LATER, WED, later) == later


def test_due_drop_this_week_on_thursday_goes_to_sunday():
    thursday = date(2026, 11, 5)  # demain = vendredi → « cette semaine » = samedi / dimanche
    assert rules.due_for_bucket_drop(DueBucket.THIS_WEEK, thursday, None) == SUN


def test_due_drop_refused_on_overdue_and_empty_week():
    with pytest.raises(InvalidOperation):
        rules.due_for_bucket_drop(DueBucket.OVERDUE, WED, None)
    assert not rules.bucket_accepts_drop(DueBucket.THIS_WEEK, SAT)
    with pytest.raises(InvalidOperation):
        rules.due_for_bucket_drop(DueBucket.THIS_WEEK, SAT, None)


def test_later_drop_always_lands_in_later_bucket():
    for offset in range(7):
        day = WED + timedelta(days=offset)
        new_due = rules.due_for_bucket_drop(DueBucket.LATER, day, None)
        assert rules.due_bucket(new_due, day) is DueBucket.LATER


def test_effective_reminder():
    due = date(2026, 11, 20)
    assert rules.effective_reminder(TaskKind.FOLLOWUP, due, 2, None) == date(2026, 11, 18)
    assert rules.effective_reminder(TaskKind.FOLLOWUP, None, 2, None) is None
    assert rules.effective_reminder(TaskKind.FOLLOWUP, due, None, date(2026, 11, 1)) == date(2026, 11, 1)
    assert rules.effective_reminder(TaskKind.TODO, due, 2, None) is None


def test_quadrants():
    assert rules.quadrant_of(4, 4) is Quadrant.DO
    assert rules.quadrant_of(3, 2) is Quadrant.PLAN
    assert rules.quadrant_of(2, 3) is Quadrant.DELEGATE
    assert rules.quadrant_of(1, 1) is Quadrant.ELIMINATE


def test_matrix_drop_changes_values_minimally():
    assert rules.matrix_drop(2, 2, Quadrant.DO) == (3, 3)
    assert rules.matrix_drop(4, 1, Quadrant.DO) == (4, 3)  # importance déjà compatible : inchangée
    assert rules.matrix_drop(4, 4, Quadrant.ELIMINATE) == (2, 2)
    assert rules.matrix_drop(1, 4, Quadrant.PLAN) == (3, 2)
    for quadrant in Quadrant:
        assert rules.quadrant_of(*rules.matrix_drop(1, 4, quadrant)) is quadrant


@dataclass
class FakeTask:
    id: int
    parent_id: int | None = None
    has_subtasks: bool = False


def test_attach_refusal_reasons():
    assert rules.attach_refusal_reason(FakeTask(1), FakeTask(2)) is None
    assert rules.attach_refusal_reason(FakeTask(1), FakeTask(1))
    assert rules.attach_refusal_reason(FakeTask(1), FakeTask(2, parent_id=3))
    assert rules.attach_refusal_reason(FakeTask(1, has_subtasks=True), FakeTask(2))
    assert rules.attach_refusal_reason(FakeTask(1, parent_id=2), FakeTask(2))
    # Une sous-tâche peut changer de parent.
    assert rules.attach_refusal_reason(FakeTask(1, parent_id=5), FakeTask(2)) is None


@dataclass
class FakeParent:
    status: Status
    subtask_total: int
    subtask_done: int


def test_suggest_parent_completion():
    assert rules.should_suggest_parent_completion(FakeParent(Status.IN_PROGRESS, 2, 2))
    assert not rules.should_suggest_parent_completion(FakeParent(Status.IN_PROGRESS, 2, 1))
    assert not rules.should_suggest_parent_completion(FakeParent(Status.DONE, 2, 2))
    assert not rules.should_suggest_parent_completion(FakeParent(Status.IN_PROGRESS, 0, 0))


def test_tag_palette_is_varied():
    assert len(set(rules.TAG_PALETTE)) == 24
    assert all(c.startswith("#") and len(c) == 7 for c in rules.TAG_PALETTE)


def test_color_distance():
    assert rules.color_distance("#ff0000", "#ff0000") == 0
    assert rules.color_distance("#ff0000", "#fe0000") < 2
    assert rules.color_distance("#ff0000", "#0000ff") > 100


def test_pick_distinct_color_avoids_task_colors_first():
    import random

    red, green = "#d92626", "#26d926"
    for seed in range(20):
        color = rules.pick_distinct_color([red, green], priority=[red], rng=random.Random(seed))
        assert rules.color_distance(color, red) > 40
        assert rules.color_distance(color, green) > 25


def test_pick_distinct_color_spreads_over_palette():
    import random

    rng = random.Random(1)
    chosen: list[str] = []
    for _ in range(8):
        chosen.append(rules.pick_distinct_color(chosen, rng=rng))
    closest = min(rules.color_distance(a, b) for i, a in enumerate(chosen) for b in chosen[i + 1 :])
    assert len(set(chosen)) == 8 and closest > 15
