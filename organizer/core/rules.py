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
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Protocol, TypeVar
from urllib.parse import parse_qs, quote, urlparse

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


def rank_drop(order: list[tuple[int, int, float]], moved: int) -> tuple[Urgency, dict[int, float]]:
    """Reclassement d'une carte dans une colonne triée par urgence décroissante puis par rang croissant.

    ``order`` : la colonne **après** le dépôt, sous forme de ``(id, urgence, rang)`` (la carte déplacée avec
    son urgence actuelle). Renvoie la nouvelle urgence de la carte (ramenée au minimum nécessaire entre celles
    de ses voisines du dessus et du dessous) et les rangs à modifier ``{id: rang}`` pour que l'ordre affiché
    soit respecté parmi les tâches de même urgence.
    """
    ids = [item[0] for item in order]
    i = ids.index(moved)
    urgency = order[i][1]
    high = order[i - 1][1] if i > 0 else max(Urgency)
    low = order[i + 1][1] if i + 1 < len(order) else min(Urgency)
    urgency = min(max(urgency, low), max(high, low))
    group = [(tid, rank) for tid, u, rank in order if (urgency if tid == moved else u) == urgency]
    j = [tid for tid, _ in group].index(moved)
    current = group[j][1]
    before = group[j - 1][1] if j > 0 else None
    after = group[j + 1][1] if j + 1 < len(group) else None
    if (before is None or before < current) and (after is None or current < after):
        return Urgency(urgency), {}  # déjà à sa place
    if before is None:
        return Urgency(urgency), {moved: after - 1}
    if after is None:
        return Urgency(urgency), {moved: before + 1}
    if after - before > 1e-6:
        return Urgency(urgency), {moved: (before + after) / 2}
    # Rangs égaux (jamais reclassés) : on renumérote le groupe dans l'ordre affiché.
    changes = {tid: float(k) for k, (tid, rank) in enumerate(group) if rank != float(k) or tid == moved}
    return Urgency(urgency), changes


def priority_score(importance: int, urgency: int) -> int:
    """Score combiné (2 à 8) ; plus il est haut, plus la tâche est prioritaire."""
    return importance + urgency


# --- Calendrier -------------------------------------------------------------------------------------------


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """Mois décalé de ``delta`` (négatif = vers le passé) : ``(2026, 12) + 1`` → ``(2027, 1)``."""
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def month_grid(year: int, month: int) -> list[list[date]]:
    """Semaines complètes (lundi → dimanche) qui couvrent le mois : 4 à 6 lignes de 7 jours.

    La première ligne commence au lundi qui précède (ou qui est) le 1er ; la dernière finit au dimanche qui
    suit (ou qui est) le dernier jour. Les jours des mois voisins sont donc inclus.
    """
    first = date(year, month, 1)
    next_year, next_month = shift_month(year, month, 1)
    last = date(next_year, next_month, 1) - timedelta(days=1)
    day = first - timedelta(days=first.weekday())
    end = end_of_week(last)
    weeks: list[list[date]] = []
    while day <= end:
        weeks.append([day + timedelta(days=i) for i in range(7)])
        day += timedelta(days=7)
    return weeks


class _DatedTask(Protocol):
    title: str
    due_date: date | None
    due_time: time | None
    urgency: int
    status: Status


_Dated = TypeVar("_Dated", bound=_DatedTask)


def is_overdue(task: _DatedTask, today: date) -> bool:
    """Échéance passée et tâche ni finie ni annulée."""
    return task.due_date is not None and task.due_date < today and not task.status.is_closed


def calendar_days(tasks: Iterable[_Dated], today: date) -> dict[date, list[_Dated]]:
    """Jour du calendrier où montrer chaque tâche datée.

    - une tâche s'affiche à son échéance ;
    - une tâche **en retard** s'affiche **aujourd'hui** (et plus à son échéance passée) ;
    - les tâches annulées et sans échéance ne s'affichent pas.
    Ordre dans une journée : retards d'abord (les plus anciens en tête), puis urgence décroissante, heure
    (les tâches sans heure après), titre.
    """
    days: dict[date, list[_Dated]] = {}
    for task in tasks:
        if task.due_date is None or task.status is Status.CANCELLED:
            continue
        day = today if is_overdue(task, today) else task.due_date
        days.setdefault(day, []).append(task)

    def order(task: _Dated) -> tuple:
        late = is_overdue(task, today)
        return (
            not late,
            task.due_date if late else date.min,
            -int(task.urgency),
            task.due_time is None,
            task.due_time or time.min,
            task.title.lower(),
        )

    for listed in days.values():
        listed.sort(key=order)
    return days


# --- Événements -------------------------------------------------------------------------------------------

DEFAULT_EVENT_DURATION = timedelta(hours=1)
DEFAULT_EVENT_START = time(9, 0)


def event_span(
    start_date: date, start_time: time | None, end_date: date | None, end_time: time | None
) -> tuple[date, time | None, date, time | None]:
    """Normalise le début et la fin d'un événement.

    - sans heure de début : **toute la journée**, de ``start_date`` à ``end_date`` inclus (heures effacées) ;
    - avec heure de début : sans heure de fin, il dure une heure ; la fin doit être après le début.
    """
    end_date = end_date or start_date
    if start_time is None:
        if end_date < start_date:
            raise InvalidOperation("Le dernier jour doit être après le premier.")
        return start_date, None, end_date, None
    start = datetime.combine(start_date, start_time)
    end = datetime.combine(end_date, end_time) if end_time is not None else start + DEFAULT_EVENT_DURATION
    if end <= start:
        raise InvalidOperation("La fin doit être après le début.")
    return start_date, start_time, end.date(), end.time()


def event_days(
    start_date: date, start_time: time | None, end_date: date, end_time: time | None
) -> list[date]:
    """Jours touchés par un événement (pour l'afficher dans le calendrier). Un événement qui finit à minuit
    pile ne déborde pas sur le jour suivant."""
    last = end_date
    if start_time is not None and end_time == time(0, 0) and end_date > start_date:
        last = end_date - timedelta(days=1)
    return [start_date + timedelta(days=i) for i in range((last - start_date).days + 1)]


def event_times_from_due(
    due_date: date | None, due_time: time | None, fallback: date
) -> tuple[date, time, date, time]:
    """Tâche → événement : il commence à l'échéance (ou le jour ``fallback``, à 9 h) et dure une heure."""
    start = datetime.combine(due_date or fallback, due_time or DEFAULT_EVENT_START)
    end = start + DEFAULT_EVENT_DURATION
    return start.date(), start.time(), end.date(), end.time()


_COORDS_RE = re.compile(r"(-?\d{1,3}\.\d+),\s*(-?\d{1,3}\.\d+)")


def _is_address_link(location: str) -> bool:
    text = location.strip()
    return bool(_SCHEME_RE.match(text)) or text.lower().startswith(
        ("www.", "maps.", "goo.gl/", "maps.app.goo.gl")
    )


def maps_url(location: str) -> str | None:
    """Lien à ouvrir pour un lieu : le lien lui-même s'il en est un (Google Maps…), sinon une recherche
    Google Maps de ce texte. ``None`` pour un lieu vide."""
    text = location.strip()
    if not text:
        return None
    if _is_address_link(text):
        return normalize_url(text)
    return "https://www.google.com/maps/search/?api=1&query=" + quote(text)


def waze_url(location: str) -> str | None:
    """Navigation Waze vers un lieu : par l'adresse pour un texte, par les coordonnées pour un lien qui en
    contient (``…/@48.85,2.35,17z``, ``?q=48.85,2.35``) ; ``None`` sinon (lien court sans coordonnées)."""
    text = location.strip()
    if not text:
        return None
    if not _is_address_link(text):
        return f"https://waze.com/ul?q={quote(text)}&navigate=yes"
    url = urlparse(normalize_url(text))
    candidates = [url.path] + [value for values in parse_qs(url.query).values() for value in values]
    for candidate in candidates:
        match = _COORDS_RE.search(candidate)
        if match:
            return f"https://waze.com/ul?ll={match.group(1)},{match.group(2)}&navigate=yes"
    return None


def week_start(day: date) -> date:
    """Lundi de la semaine de ``day``."""
    return day - timedelta(days=day.weekday())


def weeks_from(monday: date, count: int) -> list[list[date]]:
    """``count`` semaines complètes à partir du lundi ``monday``."""
    return [[monday + timedelta(days=7 * w + d) for d in range(7)] for w in range(count)]


def is_band(start_date: date, start_time: time | None, end_date: date, end_time: time | None) -> bool:
    """Un événement s'affiche en **bande** (au-dessus des pastilles) s'il dure toute la journée ou touche
    plusieurs jours ; sinon c'est une pastille horaire dans sa case."""
    return start_time is None or len(event_days(start_date, start_time, end_date, end_time)) > 1


_Key = TypeVar("_Key")


def band_layout(
    spans: Iterable[tuple[_Key, date, date]], monday: date
) -> list[tuple[_Key, int, int, int, bool, bool]]:
    """Place des bandes (``(clé, premier jour, dernier jour)``) dans la semaine du lundi ``monday``, sur des
    lignes sans chevauchement (la plus haute libre ; les plus longues d'abord à début égal).

    Renvoie ``(clé, colonne de début, colonne de fin, ligne, commence avant, continue après)`` (colonnes 0
    à 6, lundi à dimanche) pour les bandes qui touchent la semaine.
    """
    sunday = monday + timedelta(days=6)
    segments = [
        (key, max(first, monday), min(last, sunday), first < monday, last > sunday)
        for key, first, last in spans
        if last >= monday and first <= sunday
    ]
    segments.sort(key=lambda seg: (seg[1], -(seg[2] - seg[1]).days))
    lane_ends: list[int] = []  # dernière colonne occupée sur chaque ligne
    placed = []
    for key, first, last, before, after in segments:
        start, end = (first - monday).days, (last - monday).days
        lane = next((i for i, used in enumerate(lane_ends) if used < start), len(lane_ends))
        if lane == len(lane_ends):
            lane_ends.append(end)
        else:
            lane_ends[lane] = end
        placed.append((key, start, end, lane, before, after))
    return placed


# --- Vue d'un jour : agenda sur deux colonnes ---------------------------------------------------------------

DAY_MINUTES = 24 * 60
HALF_DAY = 12 * 60
AGENDA_STEP = 15  # pas du glisser-déposer dans l'agenda (minutes)


@dataclass(frozen=True)
class AgendaBlock:
    """Morceau d'un événement dans une colonne de l'agenda (0 : 0-12 h, 1 : 12-24 h). ``top`` / ``bottom`` :
    minutes depuis le haut de la colonne ; ``lane`` / ``lanes`` : place parmi les événements qui se
    chevauchent ; ``starts`` / ``ends`` : le vrai début / la vraie fin de l'événement sont dans ce morceau."""

    key: Any
    column: int
    top: int
    bottom: int
    lane: int
    lanes: int
    starts: bool
    ends: bool


def agenda_layout(spans: Iterable[tuple[Any, datetime, datetime]], day: date) -> list[AgendaBlock]:
    """Découpe les événements (``(clé, début, fin)``) qui touchent ``day`` en morceaux pour les deux colonnes
    de l'agenda (coupure à midi ; ce qui dépasse la journée est coupé), et place côte à côte ceux qui se
    chevauchent dans une même colonne."""
    origin = datetime.combine(day, time(0))
    parts: list[dict] = []
    for key, start, end in spans:
        first = int((start - origin).total_seconds() // 60)
        last = int((end - origin).total_seconds() // 60)
        lo, hi = max(first, 0), min(last, DAY_MINUTES)
        for column, (begin, finish) in enumerate(((0, HALF_DAY), (HALF_DAY, DAY_MINUTES))):
            a, b = max(lo, begin), min(hi, finish)
            if a < b:
                parts.append(
                    {
                        "key": key,
                        "column": column,
                        "top": a - begin,
                        "bottom": b - begin,
                        "starts": a == first,
                        "ends": b == last,
                    }
                )
    blocks: list[AgendaBlock] = []
    for column in (0, 1):
        items = sorted((p for p in parts if p["column"] == column), key=lambda p: (p["top"], -p["bottom"]))
        cluster: list[dict] = []
        cluster_end = -1
        for item in [*items, None]:
            if item is None or item["top"] >= cluster_end:
                blocks.extend(_place_cluster(cluster))
                cluster, cluster_end = [], -1
                if item is None:
                    break
            cluster.append(item)
            cluster_end = max(cluster_end, item["bottom"])
    return blocks


def _place_cluster(cluster: list[dict]) -> list[AgendaBlock]:
    """Événements qui se chevauchent (de proche en proche) : chacun sur la première file libre ; tous ont la
    même largeur (1 / nombre de files)."""
    lane_ends: list[int] = []
    lanes: list[int] = []
    for item in cluster:
        lane = next((i for i, used in enumerate(lane_ends) if used <= item["top"]), len(lane_ends))
        if lane == len(lane_ends):
            lane_ends.append(item["bottom"])
        else:
            lane_ends[lane] = item["bottom"]
        lanes.append(lane)
    count = len(lane_ends)
    return [AgendaBlock(lane=lane, lanes=count, **item) for item, lane in zip(cluster, lanes, strict=True)]


def snap_minutes(minutes: float, step: int = AGENDA_STEP) -> int:
    """Arrondit au pas le plus proche, dans la journée (0 à 24 h)."""
    return max(0, min(DAY_MINUTES, round(minutes / step) * step))
