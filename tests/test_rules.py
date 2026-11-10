"""Règles métier pures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta

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


# --- reclassement dans une colonne (urgence + rang) ---


def test_rank_drop_keeps_place_and_clamps_urgency():
    # Colonne : A(4) B(3) C(2) ; on dépose X (urgence 1) entre A et B → urgence remontée à 3, avant B.
    urgency, ranks = rules.rank_drop([(1, 4, 0.0), (9, 1, 0.0), (2, 3, 0.0), (3, 2, 0.0)], 9)
    assert urgency == 3 and ranks == {9: -1.0}
    # En bas d'une colonne : urgence abaissée à celle de la dernière.
    urgency, ranks = rules.rank_drop([(1, 4, 0.0), (2, 2, 5.0), (9, 4, 0.0)], 9)
    assert urgency == 2 and ranks == {9: 6.0}
    # Entre deux urgences différentes : l'urgence actuelle convient, rien ne bouge.
    assert rules.rank_drop([(1, 4, 0.0), (9, 3, 0.0), (2, 2, 0.0)], 9) == (3, {})


def test_rank_drop_inside_a_group():
    # Rangs distincts : milieu.
    assert rules.rank_drop([(1, 3, 1.0), (9, 3, 7.0), (2, 3, 2.0)], 9) == (3, {9: 1.5})
    # Rangs égaux (jamais reclassés) : le groupe est renuméroté dans l'ordre affiché.
    urgency, ranks = rules.rank_drop([(1, 3, 0.0), (9, 3, 0.0), (2, 3, 0.0)], 9)
    assert urgency == 3 and ranks == {9: 1.0, 2: 2.0}
    # Seule dans la colonne : rien à faire.
    assert rules.rank_drop([(9, 2, 0.0)], 9) == (2, {})


# --- Calendrier -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("year", "month", "delta", "expected"),
    [
        (2026, 11, 1, (2026, 12)),
        (2026, 12, 1, (2027, 1)),
        (2026, 1, -1, (2025, 12)),
        (2026, 11, -23, (2024, 12)),
        (2026, 11, 0, (2026, 11)),
    ],
)
def test_shift_month(year, month, delta, expected):
    assert rules.shift_month(year, month, delta) == expected


def test_month_grid_starts_monday_and_ends_sunday():
    weeks = rules.month_grid(2026, 11)  # 1er novembre 2026 = dimanche
    assert weeks[0][0] == date(2026, 10, 26)  # lundi précédent
    assert weeks[0][-1] == date(2026, 11, 1)
    assert weeks[-1][-1] == date(2026, 12, 6)  # 30 novembre = lundi → dimanche suivant
    assert len(weeks) == 6
    assert all(len(week) == 7 for week in weeks)
    assert all(week[0].weekday() == 0 for week in weeks)
    days = [d for week in weeks for d in week]
    assert days == [days[0] + timedelta(days=i) for i in range(len(days))]  # continu, sans trou


def test_month_grid_exact_weeks():
    # Février 2027 : commence un lundi, 28 jours → exactement 4 semaines, sans jour voisin.
    weeks = rules.month_grid(2027, 2)
    assert len(weeks) == 4
    assert weeks[0][0] == date(2027, 2, 1)
    assert weeks[-1][-1] == date(2027, 2, 28)


@dataclass
class Dated:
    title: str
    due_date: date | None
    urgency: int = 2
    status: Status = Status.NOT_STARTED
    due_time: time | None = None


def test_calendar_days_places_overdue_tasks_today():
    today = date(2026, 11, 4)
    late_old = Dated("Vieux retard", date(2026, 10, 1), urgency=1)
    late = Dated("Retard", date(2026, 11, 2), urgency=4)
    done_past = Dated("Faite", date(2026, 11, 2), status=Status.DONE)
    cancelled = Dated("Annulée", date(2026, 11, 5), status=Status.CANCELLED)
    undated = Dated("Sans date", None)
    today_low = Dated("Aujourd'hui", today, urgency=1)
    today_high = Dated("Urgente", today, urgency=4)
    later_timed = Dated("B à 9 h", date(2026, 11, 6), due_time=time(9, 0))
    later_untimed = Dated("A sans heure", date(2026, 11, 6))
    later_early = Dated("C à 8 h", date(2026, 11, 6), due_time=time(8, 0))
    days = rules.calendar_days(
        [
            late,
            today_low,
            done_past,
            cancelled,
            undated,
            later_timed,
            late_old,
            today_high,
            later_untimed,
            later_early,
        ],
        today,
    )
    # Retards en tête (le plus ancien d'abord, quelle que soit l'urgence), puis par urgence.
    assert days[today] == [late_old, late, today_high, today_low]
    assert days[date(2026, 11, 2)] == [done_past]  # finie : reste à son échéance
    assert days[date(2026, 11, 6)] == [later_early, later_timed, later_untimed]  # heure, puis sans heure
    assert date(2026, 10, 1) not in days and date(2026, 11, 5) not in days
    assert rules.is_overdue(late, today) and not rules.is_overdue(done_past, today)
    assert not rules.is_overdue(today_low, today)


# --- Événements -------------------------------------------------------------------------------------------


def test_event_span():
    d = date(2026, 11, 12)
    # Toute la journée (plusieurs jours) ; heures de fin ignorées.
    assert rules.event_span(d, None, date(2026, 11, 14), time(10, 0)) == (d, None, date(2026, 11, 14), None)
    assert rules.event_span(d, None, None, None) == (d, None, d, None)
    with pytest.raises(InvalidOperation):
        rules.event_span(d, None, date(2026, 11, 10), None)
    # Avec heures : une heure par défaut, passage de minuit.
    assert rules.event_span(d, time(9, 0), None, None) == (d, time(9, 0), d, time(10, 0))
    assert rules.event_span(d, time(23, 30), None, None) == (d, time(23, 30), date(2026, 11, 13), time(0, 30))
    assert rules.event_span(d, time(9, 0), None, time(11, 15)) == (d, time(9, 0), d, time(11, 15))
    for end in (time(9, 0), time(8, 0)):
        with pytest.raises(InvalidOperation):
            rules.event_span(d, time(9, 0), d, end)


def test_event_days():
    d = date(2026, 11, 12)
    assert rules.event_days(d, None, date(2026, 11, 14), None) == [d, date(2026, 11, 13), date(2026, 11, 14)]
    assert rules.event_days(d, time(22, 0), date(2026, 11, 13), time(0, 0)) == [d]  # finit à minuit pile
    assert rules.event_days(d, time(22, 0), date(2026, 11, 13), time(1, 0)) == [d, date(2026, 11, 13)]


def test_event_times_from_due():
    d = date(2026, 11, 12)
    assert rules.event_times_from_due(d, time(14, 30), date(2026, 1, 1)) == (d, time(14, 30), d, time(15, 30))
    assert rules.event_times_from_due(None, None, d) == (d, time(9, 0), d, time(10, 0))


def test_maps_and_waze_links():
    assert rules.maps_url("") is None and rules.waze_url("  ") is None
    assert rules.maps_url("12 rue de la Paix, Paris") == (
        "https://www.google.com/maps/search/?api=1&query=12%20rue%20de%20la%20Paix%2C%20Paris"
    )
    assert rules.waze_url("12 rue de la Paix, Paris") == (
        "https://waze.com/ul?q=12%20rue%20de%20la%20Paix%2C%20Paris&navigate=yes"
    )
    place = "https://www.google.com/maps/place/Tour+Eiffel/@48.8583701,2.2944813,17z/data=x"
    assert rules.maps_url(place) == place
    assert rules.waze_url(place) == "https://waze.com/ul?ll=48.8583701,2.2944813&navigate=yes"
    assert rules.waze_url("https://maps.google.com/?q=45.75,4.85") == (
        "https://waze.com/ul?ll=45.75,4.85&navigate=yes"
    )
    assert rules.maps_url("maps.app.goo.gl/AbCdE") == "https://maps.app.goo.gl/AbCdE"
    assert rules.waze_url("https://maps.app.goo.gl/AbCdE") is None  # lien court : pas de coordonnées


def test_band_layout_and_weeks():
    monday = date(2026, 11, 9)
    assert rules.week_start(date(2026, 11, 12)) == monday and rules.week_start(monday) == monday
    weeks = rules.weeks_from(monday, 6)
    assert len(weeks) == 6 and weeks[0][0] == monday and weeks[-1][-1] == date(2026, 12, 20)
    spans = [
        ("long", date(2026, 11, 5), date(2026, 11, 11)),  # commence la semaine d'avant
        ("court", date(2026, 11, 10), date(2026, 11, 10)),
        ("chevauche", date(2026, 11, 11), date(2026, 11, 20)),  # continue après
        ("libre", date(2026, 11, 13), date(2026, 11, 14)),
        ("ailleurs", date(2026, 11, 1), date(2026, 11, 2)),
    ]
    placed = {key: rest for key, *rest in rules.band_layout(spans, monday)}
    assert placed["long"] == [0, 2, 0, True, False]
    assert placed["court"] == [1, 1, 1, False, False]
    assert placed["chevauche"] == [2, 6, 1, False, True]  # ligne 0 occupée le mercredi par « long »
    assert placed["libre"] == [4, 5, 0, False, False]  # la ligne 0 est libre dès jeudi
    assert "ailleurs" not in placed
    assert rules.is_band(monday, None, monday, None)
    assert rules.is_band(monday, time(22), date(2026, 11, 10), time(1))
    assert not rules.is_band(monday, time(9), monday, time(10))


def test_agenda_layout_splits_at_noon_and_places_overlaps():
    from datetime import datetime

    day = date(2026, 11, 12)

    def at(h, m=0, d=day):
        return datetime.combine(d, time(h, m))

    blocks = rules.agenda_layout(
        [
            ("midi", at(11), at(13)),  # chevauche midi : deux morceaux
            ("a", at(9), at(10)),
            ("b", at(9, 30), at(10, 30)),  # chevauche « a »
            ("c", at(10, 30), at(11)),  # touche « b » et « midi » sans les chevaucher
            ("nuit", at(22, 0, date(2026, 11, 11)), at(1)),  # commence la veille
            ("soir", at(23), at(2, 0, date(2026, 11, 13))),  # finit le lendemain
            ("ailleurs", at(9, 0, date(2026, 11, 13)), at(10, 0, date(2026, 11, 13))),
        ],
        day,
    )
    by = {(b.key, b.column): b for b in blocks}
    assert set(by) == {("midi", 0), ("midi", 1), ("a", 0), ("b", 0), ("c", 0), ("nuit", 0), ("soir", 1)}
    assert (by["midi", 0].top, by["midi", 0].bottom, by["midi", 0].starts, by["midi", 0].ends) == (
        660,
        720,
        True,
        False,
    )
    assert (by["midi", 1].top, by["midi", 1].bottom, by["midi", 1].starts, by["midi", 1].ends) == (
        0,
        60,
        False,
        True,
    )
    assert (by["a", 0].lane, by["b", 0].lane, by["a", 0].lanes) == (0, 1, 2)
    assert (by["c", 0].lane, by["c", 0].lanes, by["midi", 0].lanes) == (0, 1, 1)  # pleine largeur
    assert (by["nuit", 0].top, by["nuit", 0].bottom, by["nuit", 0].starts) == (0, 60, False)
    assert (by["soir", 1].top, by["soir", 1].bottom, by["soir", 1].ends) == (660, 720, False)
    assert rules.snap_minutes(9 * 60 + 7) == 9 * 60 + 0 and rules.snap_minutes(9 * 60 + 8) == 9 * 60 + 15
    assert rules.snap_minutes(-30) == 0 and rules.snap_minutes(1500) == 1440


def test_label_names_disambiguate_same_names():
    @dataclass
    class L:
        id: int
        name: str
        is_public: bool

    labels = [L(1, "Sport", False), L(2, "sport", True), L(3, "Maison", True), L(4, "Sport", True)]
    assert rules.label_names(labels) == {
        1: "Sport (privé)",
        2: "sport (public)",
        3: "Maison",
        4: "Sport (public)",  # casse différente : déjà distinct
    }
    assert rules.label_names([L(1, "A", True), L(2, "A", True)]) == {1: "A (public)", 2: "A (public) 2"}


def test_ownership():
    from organizer.core.enums import Ownership

    assert rules.ownership(1, 1, []) is Ownership.MINE
    assert rules.ownership(1, 1, [2]) is Ownership.SHARED_BY_ME
    assert rules.ownership(2, 1, [1]) is Ownership.SHARED_WITH_ME
    assert rules.ownership(2, 1, [1], can_edit=False) is Ownership.READ_ONLY
    assert rules.ownership(2, 1, [], can_edit=False) is Ownership.READ_ONLY  # public
