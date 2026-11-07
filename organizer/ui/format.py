"""Mise en forme des dates pour l'affichage (en français, sans dépendre de la locale du système)."""

from __future__ import annotations

from datetime import date, datetime, time

DAYS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


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


def due_text(d: date, t: time | None, today: date) -> str:
    text = short_date(d, today)
    return f"{text} {t:%H:%M}" if t else text


def local_datetime(dt: datetime) -> str:
    """Date-heure UTC convertie dans le fuseau du système : « 07/11/2026 à 21:54 »."""
    return dt.astimezone().strftime("%d/%m/%Y à %H:%M")
