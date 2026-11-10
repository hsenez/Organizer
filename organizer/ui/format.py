"""Mise en forme des dates pour l'affichage (en français, sans dépendre de la locale du système)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

DAYS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
DAY_NAMES = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MONTH_NAMES = [
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
]


def short_date(d: date, today: date) -> str:
    """« Aujourd'hui », « Demain », « Hier », sinon « lun. 9 nov. » (+ année si différente)."""
    delta = (d - today).days
    if delta == 0:
        return "Aujourd'hui"
    if delta == 1:
        return "Demain"
    if delta == -1:
        return "Hier"
    text = f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"
    return text if d.year == today.year else f"{text} {d.year}"


def long_date(d: date) -> str:
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]} {d.year}"


def relative(d: date, today: date) -> str:
    """« en retard de 3 j », « aujourd'hui », « dans 5 j »."""
    delta = (d - today).days
    if delta < 0:
        return f"en retard de {-delta} j"
    if delta == 0:
        return "aujourd'hui"
    return f"dans {delta} j"


def distance(d: date, today: date) -> str:
    """« aujourd'hui », « demain », « hier », « dans 5 j », « il y a 3 j »."""
    delta = (d - today).days
    if delta == 0:
        return "aujourd'hui"
    if delta == 1:
        return "demain"
    if delta == -1:
        return "hier"
    return f"dans {delta} j" if delta > 0 else f"il y a {-delta} j"


def due_text(d: date, t: time | None, today: date) -> str:
    text = short_date(d, today)
    return f"{text} {t:%H:%M}" if t else text


def local_datetime(dt: datetime) -> str:
    """Date-heure UTC convertie dans le fuseau du système : « 07/11/2026 à 21:54 »."""
    return dt.astimezone().strftime("%d/%m/%Y à %H:%M")


def ago(moment: datetime, now: datetime | None = None) -> str:
    """« à l'instant », « il y a 5 min », « il y a 3 h », sinon la date et l'heure locales."""
    now = now or datetime.now(moment.tzinfo)
    seconds = (now - moment).total_seconds()
    if seconds < 60:
        return "à l'instant"
    if seconds < 3600:
        return f"il y a {int(seconds // 60)} min"
    if seconds < 24 * 3600:
        return f"il y a {int(seconds // 3600)} h"
    return local_datetime(moment)


def duration(delta: timedelta) -> str:
    """« 45 min », « 1 h », « 1 h 30 », « 2 j »."""
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} min"
    if minutes % (24 * 60) == 0:
        return f"{minutes // (24 * 60)} j"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest:02d}" if rest else f"{hours} h"


def event_range(start_date: date, start_time: time | None, end_date: date, end_time: time | None) -> str:
    """« jeu. 12 nov. 2026 · 09:00 → 10:30 (1 h 30) », « jeu. 12 nov. 2026 · toute la journée »,
    « du jeu. 12 nov. au sam. 14 nov. 2026 (3 j) »."""
    if start_time is None:
        if start_date == end_date:
            return f"{long_date(start_date)} · toute la journée"
        days = (end_date - start_date).days + 1
        first = long_date(start_date) if start_date.year != end_date.year else long_date(start_date)[:-5]
        return f"du {first} au {long_date(end_date)} ({days} j)"
    start = datetime.combine(start_date, start_time)
    end = datetime.combine(end_date, end_time or start_time)
    span = duration(end - start)
    if start_date == end_date:
        return f"{long_date(start_date)} · {start_time:%H:%M} → {end_time:%H:%M} ({span})"
    return f"{long_date(start_date)} {start_time:%H:%M} → {long_date(end_date)} {end_time:%H:%M} ({span})"
