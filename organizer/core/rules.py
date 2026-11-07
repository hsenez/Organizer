"""Règles métier pures (sans accès à la base) : partagées par les services et l'interface.

L'interface les utilise pour réagir instantanément (surbrillance Ctrl+drop, colonnes interdites…) ; les
services les réappliquent côté serveur pour garantir la cohérence.
"""

from __future__ import annotations

import colorsys
import random
import re
import unicodedata
from collections.abc import Iterable
from datetime import date, timedelta
from typing import Protocol

from organizer.core.enums import DueBucket, Importance, LinkKind, Quadrant, Status, TaskKind, Urgency
from organizer.core.errors import InvalidOperation

IMPORTANT_THRESHOLD = 3  # importance >= 3 → « important » dans la matrice
URGENT_THRESHOLD = 3  # urgence >= 3 → « urgent »


# --- Texte ------------------------------------------------------------------------------------------------


def normalize_text(text: str) -> str:
    """Minuscules sans accents, pour une recherche tolérante (« tache » trouve « Tâche »)."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


_SCHEME_RE = re.compile(r"^(?:[a-z][a-z0-9+.-]*://|mailto:|tel:)", re.IGNORECASE)
_PATH_RE = re.compile(r"^(?:/|~|\./|\.\./|\\\\|[a-z]:[\\/]|file://)", re.IGNORECASE)
# Nom de domaine éventuellement suivi d'un port et d'un chemin : « google.fr », « exemple.com/page?x=1 ».
_DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?P<tld>[a-z]{2,24})(?::\d{1,5})?(?:[/?#].*)?$", re.IGNORECASE
)
# « localhost:2603 », « 192.168.1.20:2603/tasks » : serveurs du réseau local.
_HOST_RE = re.compile(r"^(?:localhost|\d{1,3}(?:\.\d{1,3}){3})(?::\d{1,5})?(?:[/?#].*)?$", re.IGNORECASE)
# Extensions de fichiers courantes : « notes.txt » est un fichier, pas un site web.
_FILE_EXTENSIONS = {
    "txt", "md", "pdf", "doc", "docx", "odt", "ods", "odp", "xls", "xlsx", "ppt", "pptx", "csv", "json",
    "xml", "yaml", "yml", "ini", "log", "zip", "tar", "gz", "rar", "png", "jpg", "jpeg", "gif", "svg",
    "webp", "mp3", "mp4", "mkv", "avi", "wav", "py", "js", "sh", "exe", "html", "htm",
}  # fmt: skip


def detect_link_kind(target: str) -> LinkKind:
    """Devine si un texte saisi est un hyperlien ou un chemin de fichier local.

    - ``https://…``, ``mailto:…``, ``www.…``, ``localhost:2603``, une adresse IP, et tout ce qui ressemble à
      un nom de domaine (``google.fr``, ``exemple.com/page``) → hyperlien ;
    - ``/…``, ``~/…``, ``./…``, ``C:\\…``, ``\\\\serveur\\…``, ``file://…`` et les noms de fichiers
      (``notes.txt``) → chemin local.
    """
    text = target.strip()
    if _PATH_RE.match(text):
        return LinkKind.PATH
    if _SCHEME_RE.match(text) or text.lower().startswith("www.") or _HOST_RE.match(text):
        return LinkKind.URL
    domain = _DOMAIN_RE.match(text)
    if domain and ("/" in text or domain.group("tld").lower() not in _FILE_EXTENSIONS):
        return LinkKind.URL
    return LinkKind.PATH


def normalize_url(target: str) -> str:
    """Adresse complète à ouvrir : ajoute ``http://`` pour un serveur local (localhost, adresse IP), sinon
    ``https://``, si aucun protocole n'est précisé."""
    text = target.strip()
    if _SCHEME_RE.match(text):
        return text
    return f"http://{text}" if _HOST_RE.match(text) else f"https://{text}"


# --- Échéances --------------------------------------------------------------------------------------------


def end_of_week(today: date) -> date:
    """Dimanche de la semaine en cours."""
    return today + timedelta(days=6 - today.weekday())


def due_bucket(due: date | None, today: date) -> DueBucket:
    if due is None:
        return DueBucket.NONE
    if due < today:
        return DueBucket.OVERDUE
    if due == today:
        return DueBucket.TODAY
    if due == today + timedelta(days=1):
        return DueBucket.TOMORROW
    if due <= end_of_week(today):
        return DueBucket.THIS_WEEK
    return DueBucket.LATER


def bucket_accepts_drop(bucket: DueBucket, today: date) -> bool:
    """La colonne « En retard » refuse les dépôts ; « Cette semaine » aussi quand il ne reste plus de jour
    après demain dans la semaine (samedi et dimanche)."""
    if bucket is DueBucket.OVERDUE:
        return False
    if bucket is DueBucket.THIS_WEEK:
        return end_of_week(today) > today + timedelta(days=1)
    return True


def due_for_bucket_drop(bucket: DueBucket, today: date, current: date | None) -> date | None:
    """Nouvelle échéance quand on dépose une carte dans une colonne du board « Par échéance »."""
    if not bucket_accepts_drop(bucket, today):
        raise InvalidOperation(f"Impossible de déposer une tâche dans « {bucket.meta.label} ».")
    if due_bucket(current, today) is bucket:
        return current  # déjà dans la bonne colonne : on ne touche à rien
    match bucket:
        case DueBucket.TODAY:
            return today
        case DueBucket.TOMORROW:
            return today + timedelta(days=1)
        case DueBucket.THIS_WEEK:
            friday = today + timedelta(days=4 - today.weekday())
            return friday if friday > today + timedelta(days=1) else end_of_week(today)
        case DueBucket.LATER:
            return today + timedelta(days=7)
        case _:
            return None


# --- Rappels ----------------------------------------------------------------------------------------------


def effective_reminder(
    kind: TaskKind, due: date | None, offset_days: int | None, manual: date | None
) -> date | None:
    """Date de rappel effective d'une tâche : seulement pour le type Suivi ; corrélée à l'échéance si un
    décalage est défini, sinon date manuelle."""
    if kind is not TaskKind.FOLLOWUP:
        return None
    if offset_days is not None:
        return due - timedelta(days=offset_days) if due is not None else None
    return manual


# --- Matrice d'Eisenhower ---------------------------------------------------------------------------------


def quadrant_of(importance: int, urgency: int) -> Quadrant:
    important = importance >= IMPORTANT_THRESHOLD
    urgent = urgency >= URGENT_THRESHOLD
    if important and urgent:
        return Quadrant.DO
    if important:
        return Quadrant.PLAN
    if urgent:
        return Quadrant.DELEGATE
    return Quadrant.ELIMINATE


def matrix_drop(importance: int, urgency: int, target: Quadrant) -> tuple[Importance, Urgency]:
    """Ajuste importance / urgence au minimum nécessaire pour entrer dans le quadrant ``target``."""
    if (importance >= IMPORTANT_THRESHOLD) != target.important:
        importance = IMPORTANT_THRESHOLD if target.important else IMPORTANT_THRESHOLD - 1
    if (urgency >= URGENT_THRESHOLD) != target.urgent:
        urgency = URGENT_THRESHOLD if target.urgent else URGENT_THRESHOLD - 1
    return Importance(importance), Urgency(urgency)


# --- Sous-tâches ------------------------------------------------------------------------------------------


class _TaskLike(Protocol):
    id: int
    parent_id: int | None

    @property
    def has_subtasks(self) -> bool: ...


def attach_refusal_reason(child: _TaskLike, parent: _TaskLike) -> str | None:
    """Raison pour laquelle ``child`` ne peut pas devenir sous-tâche de ``parent`` (None = possible)."""
    if child.id == parent.id:
        return "Une tâche ne peut pas être sa propre sous-tâche."
    if parent.parent_id is not None:
        return "La cible est déjà une sous-tâche : un seul niveau de sous-tâches est possible."
    if child.has_subtasks:
        return "Cette tâche a déjà des sous-tâches : un seul niveau de sous-tâches est possible."
    if child.parent_id == parent.id:
        return "C'est déjà une sous-tâche de cette tâche."
    return None


class _ParentLike(Protocol):
    status: Status
    subtask_total: int
    subtask_done: int


def should_suggest_parent_completion(parent: _ParentLike) -> bool:
    """Vrai si toutes les sous-tâches (non annulées) sont finies alors que le parent est encore ouvert."""
    return (
        parent.subtask_total > 0
        and parent.subtask_done == parent.subtask_total
        and not Status(parent.status).is_closed
    )


# --- Couleurs (tags) ---------------------------------------------------------------------------------


def _hsl_to_hex(hue: float, saturation: float, lightness: float) -> str:
    r, g, b = colorsys.hls_to_rgb(hue / 360, lightness, saturation)
    return "#{:02x}{:02x}{:02x}".format(*(round(v * 255) for v in (r, g, b)))


# 24 teintes réparties sur le cercle chromatique, assez saturées pour être lisibles en pastille et en texte.
TAG_PALETTE: tuple[str, ...] = tuple(_hsl_to_hex(hue, 0.68, 0.50) for hue in range(0, 360, 15))


def _hex_to_lab(color: str) -> tuple[float, float, float]:
    """Couleur ``#rrggbb`` → CIELAB (D65), où la distance euclidienne suit à peu près la perception."""
    h = color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    try:
        rgb = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    except ValueError:
        rgb = [0.5, 0.5, 0.5]
    linear = [((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92 for c in rgb]
    x = (0.4124 * linear[0] + 0.3576 * linear[1] + 0.1805 * linear[2]) / 0.95047
    y = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    z = (0.0193 * linear[0] + 0.1192 * linear[1] + 0.9505 * linear[2]) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def color_distance(a: str, b: str) -> float:
    """Écart perçu entre deux couleurs (ΔE CIE76 : ~2 à peine visible, > 30 nettement différent)."""
    la, lb = _hex_to_lab(a), _hex_to_lab(b)
    return sum((x - y) ** 2 for x, y in zip(la, lb, strict=True)) ** 0.5


# Bonus accordé à l'écart avec les tags « ailleurs » : les couleurs de la tâche en cours comptent davantage.
_PRIORITY_BONUS = 15.0
_TOLERANCE = 6.0  # on tire au hasard parmi les couleurs presque aussi bonnes que la meilleure


def pick_distinct_color(
    taken: Iterable[str], priority: Iterable[str] = (), rng: random.Random | None = None
) -> str:
    """Couleur de la palette la plus éloignée des couleurs déjà utilisées.

    ``priority`` : couleurs dont il faut s'éloigner en premier (tags de la tâche en cours d'édition) ;
    ``taken`` : toutes les autres couleurs de tags. Un peu de hasard évite de toujours tirer la même suite.
    """
    rng = rng or random.Random()
    taken = [c for c in taken if c]
    priority = [c for c in priority if c]

    def score(candidate: str) -> float:
        near_priority = min((color_distance(candidate, c) for c in priority), default=1000.0)
        near_any = min((color_distance(candidate, c) for c in taken), default=1000.0)
        return min(near_priority, near_any + _PRIORITY_BONUS)

    scored = [(score(c), c) for c in TAG_PALETTE]
    best = max(value for value, _ in scored)
    return rng.choice([c for value, c in scored if value >= best - _TOLERANCE])


# --- Tri --------------------------------------------------------------------------------------------------


def priority_score(importance: int, urgency: int) -> int:
    """Score combiné (2 à 8) ; plus il est haut, plus la tâche est prioritaire."""
    return importance + urgency
