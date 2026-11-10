"""Niveaux, statuts et types de tâches.

**Source unique** des libellés, emojis, infobulles et couleurs : l'interface ne doit jamais les redéfinir.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum


@dataclass(frozen=True)
class Meta:
    """Présentation d'une valeur d'énumération."""

    label: str
    emoji: str
    tooltip: str
    color: str  # couleur principale (hex), utilisée pour liserés, curseurs, pastilles

    @property
    def text(self) -> str:
        """Emoji + libellé, prêt à afficher."""
        return f"{self.emoji} {self.label}"


class Importance(IntEnum):
    MINOR = 1
    NORMAL = 2
    IMPORTANT = 3
    CRITICAL = 4

    @property
    def meta(self) -> Meta:
        return IMPORTANCE_META[self]


class Urgency(IntEnum):
    WHENEVER = 1
    SOON = 2
    PRESSING = 3
    IMMEDIATE = 4

    @property
    def meta(self) -> Meta:
        return URGENCY_META[self]


class Status(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    DONE = "done"
    CANCELLED = "cancelled"

    @property
    def meta(self) -> Meta:
        return STATUS_META[self]

    @property
    def is_closed(self) -> bool:
        """Vrai pour les statuts terminaux (fini ou annulé)."""
        return self in (Status.DONE, Status.CANCELLED)


class TaskKind(StrEnum):
    TODO = "todo"
    FOLLOWUP = "followup"

    @property
    def meta(self) -> Meta:
        return KIND_META[self]


class LinkKind(StrEnum):
    URL = "url"
    PATH = "path"
    ATTACHMENT = "attachment"

    @property
    def meta(self) -> Meta:
        return LINK_KIND_META[self]


class DueBucket(StrEnum):
    """Tranches d'échéance (board « Par échéance », filtres)."""

    OVERDUE = "overdue"
    TODAY = "today"
    TOMORROW = "tomorrow"
    THIS_WEEK = "this_week"
    LATER = "later"
    NONE = "none"

    @property
    def meta(self) -> Meta:
        return DUE_BUCKET_META[self]


class Quadrant(StrEnum):
    """Quadrants de la matrice d'Eisenhower."""

    DO = "do"  # important + urgent
    PLAN = "plan"  # important, pas urgent
    DELEGATE = "delegate"  # urgent, pas important
    ELIMINATE = "eliminate"  # ni l'un ni l'autre

    @property
    def meta(self) -> Meta:
        return QUADRANT_META[self]

    @property
    def important(self) -> bool:
        return self in (Quadrant.DO, Quadrant.PLAN)

    @property
    def urgent(self) -> bool:
        return self in (Quadrant.DO, Quadrant.DELEGATE)


IMPORTANCE_META: dict[Importance, Meta] = {
    Importance.MINOR: Meta(
        "Mineure", "⚪", "Importance mineure : peu d'impact si ce n'est pas fait", "#adb5bd"
    ),
    Importance.NORMAL: Meta("Normale", "🔵", "Importance normale : utile, à faire en temps voulu", "#4dabf7"),
    Importance.IMPORTANT: Meta(
        "Importante", "🟠", "Importance élevée : impact réel, à ne pas négliger", "#ff922b"
    ),
    Importance.CRITICAL: Meta(
        "Critique", "🔴", "Importance critique : conséquences lourdes si raté", "#fa5252"
    ),
}

URGENCY_META: dict[Urgency, Meta] = {
    Urgency.WHENEVER: Meta("Quand possible", "🐢", "Aucune pression de temps", "#69db7c"),
    Urgency.SOON: Meta("Bientôt", "🕐", "À traiter dans les prochains jours", "#ffd43b"),
    Urgency.PRESSING: Meta("Pressant", "⏰", "À traiter rapidement", "#ff922b"),
    Urgency.IMMEDIATE: Meta("Immédiat", "🔥", "À traiter maintenant", "#fa5252"),
}

STATUS_META: dict[Status, Meta] = {
    Status.NOT_STARTED: Meta("Pas commencé", "⏳", "La tâche n'a pas encore été entamée", "#868e96"),
    Status.IN_PROGRESS: Meta("En cours", "🚧", "La tâche est en train d'être traitée", "#339af0"),
    Status.PAUSED: Meta("En pause", "⏸️", "La tâche est entamée mais mise de côté pour l'instant", "#fcc419"),
    Status.DONE: Meta("Fini", "✅", "La tâche est terminée", "#40c057"),
    Status.CANCELLED: Meta("Annulé", "❌", "La tâche a été abandonnée", "#495057"),
}

KIND_META: dict[TaskKind, Meta] = {
    TaskKind.TODO: Meta("À faire", "📌", "Une action à réaliser soi-même", "#7950f2"),
    TaskKind.FOLLOWUP: Meta(
        "Suivi", "👁️", "Quelque chose à surveiller, avec une date de rappel liée à l'échéance", "#15aabf"
    ),
}

LINK_KIND_META: dict[LinkKind, Meta] = {
    LinkKind.URL: Meta("Hyperlien", "🌐", "Lien web, ouvert dans le navigateur", "#4dabf7"),
    LinkKind.PATH: Meta(
        "Fichier local",
        "📁",
        "Chemin sur l'ordinateur (ouvert par le client bureau, copié sur le web)",
        "#fab005",
    ),
    LinkKind.ATTACHMENT: Meta("Pièce jointe", "📎", "Fichier stocké sur le serveur", "#82c91e"),
}

DUE_BUCKET_META: dict[DueBucket, Meta] = {
    DueBucket.OVERDUE: Meta("En retard", "⚠️", "L'échéance est dépassée", "#fa5252"),
    DueBucket.TODAY: Meta("Aujourd'hui", "📅", "À rendre aujourd'hui", "#ff922b"),
    DueBucket.TOMORROW: Meta("Demain", "🌅", "À rendre demain", "#fcc419"),
    DueBucket.THIS_WEEK: Meta("Cette semaine", "🗓️", "À rendre d'ici dimanche", "#4dabf7"),
    DueBucket.LATER: Meta("Plus tard", "🔭", "Échéance après cette semaine", "#868e96"),
    DueBucket.NONE: Meta("Sans échéance", "∅", "Aucune échéance définie", "#ced4da"),
}

QUADRANT_META: dict[Quadrant, Meta] = {
    Quadrant.DO: Meta("Faire", "🔥", "Important et urgent : à faire tout de suite", "#fa5252"),
    Quadrant.PLAN: Meta("Planifier", "📅", "Important mais pas urgent : à planifier", "#339af0"),
    Quadrant.DELEGATE: Meta(
        "Déléguer", "🤝", "Urgent mais pas important : à déléguer si possible", "#fcc419"
    ),
    Quadrant.ELIMINATE: Meta("Éliminer", "🗑️", "Ni important ni urgent : à abandonner ?", "#adb5bd"),
}

# Couleur d'un événement sans couleur choisie ni projet.
EVENT_DEFAULT_COLOR = "#4c6ef5"
