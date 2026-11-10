"""Tables de la base de données (SQLModel).

Conventions :
- les énumérations sont stockées sous forme de valeurs simples (``int`` / ``str``) ; la conversion vers les
  enums de :mod:`organizer.core.enums` se fait dans les services ;
- les dates-heures sont en UTC, avec fuseau (exigé par SQLModel) ; les échéances sont des dates calendaires
  locales ;
- ``__undoable__ = True`` marque les tables suivies par l'historique annuler / rétablir.
- Pas de relations ORM « many-to-many » : les tables de liaison sont manipulées explicitement, pour que
  chaque modification soit visible par l'historique.
- Tâches et événements partagent leurs champs communs par héritage (:class:`ItemBase`, :class:`LinkBase`,
  classes sans table) ; chacun a sa table et ses tables de liaison (tags, partages, liens).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from sqlalchemy import Text
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(SQLModel, table=True):
    __tablename__ = "user"

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    display_name: str = ""
    password_hash: str
    is_admin: bool = False
    is_active: bool = True
    theme: str = "auto"  # auto | light | dark
    reminder_offset_days: int = 2
    desktop_notifications: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class Project(SQLModel, table=True):
    __tablename__ = "project"
    __undoable__ = True

    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id", index=True)
    name: str
    emoji: str = "📁"
    color: str = "#5c7cfa"
    description: str = Field(default="", sa_type=Text)
    is_public: bool = False
    archived: bool = False
    position: float = 0.0
    created_at: datetime = Field(default_factory=utcnow)


class Tag(SQLModel, table=True):
    __tablename__ = "tag"
    __undoable__ = True

    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id", index=True)
    name: str
    color: str = "#868e96"
    is_public: bool = False
    position: float = 0.0
    created_at: datetime = Field(default_factory=utcnow)


class ItemBase(SQLModel):
    """Champs communs aux tâches et aux événements (pas de table)."""

    owner_id: int = Field(foreign_key="user.id", index=True)
    title: str
    notes: str = Field(default="", sa_type=Text)
    project_id: int | None = Field(default=None, foreign_key="project.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class LinkBase(SQLModel):
    """Lien d'une tâche ou d'un événement (pas de table)."""

    id: int | None = Field(default=None, primary_key=True)
    kind: str  # url | path | attachment
    target: str  # URL, chemin local, ou identifiant de pièce jointe
    label: str = ""
    position: float = 0.0
    created_at: datetime = Field(default_factory=utcnow)


class Task(ItemBase, table=True):
    __tablename__ = "task"
    __undoable__ = True

    id: int | None = Field(default=None, primary_key=True)
    parent_id: int | None = Field(default=None, foreign_key="task.id", index=True)
    position: float = 0.0
    importance: int = 2
    urgency: int = 2
    due_date: date | None = None
    due_time: time | None = None
    status: str = "not_started"
    kind: str = "todo"
    # Rappel (type Suivi) : décalage en jours avant l'échéance, ou date manuelle si le décalage est nul.
    reminder_offset_days: int | None = None
    reminder_manual_date: date | None = None
    completed_at: datetime | None = None


class TaskTag(SQLModel, table=True):
    __tablename__ = "task_tag"
    __undoable__ = True

    task_id: int = Field(foreign_key="task.id", primary_key=True)
    tag_id: int = Field(foreign_key="tag.id", primary_key=True)


class TaskShare(SQLModel, table=True):
    __tablename__ = "task_share"
    __undoable__ = True

    task_id: int = Field(foreign_key="task.id", primary_key=True)
    user_id: int = Field(foreign_key="user.id", primary_key=True)


class TaskLink(LinkBase, table=True):
    __tablename__ = "task_link"
    __undoable__ = True

    task_id: int = Field(foreign_key="task.id", index=True)


class Event(ItemBase, table=True):
    """Événement du calendrier. Dates et heures **locales** (comme les échéances) : sans heure de début ni
    de fin, il dure toute la journée (du jour de début au jour de fin inclus) ; avec heures, la fin est
    l'instant où il se termine."""

    __tablename__ = "event"
    __undoable__ = True

    id: int | None = Field(default=None, primary_key=True)
    start_date: date = Field(index=True)
    start_time: time | None = None
    end_date: date = Field(index=True)
    end_time: time | None = None
    location: str = ""  # texte libre ou lien (Google Maps…)
    color: str | None = None  # couleur choisie ; sinon celle du projet
    is_public: bool = False  # visible (en lecture) par tous les comptes


class EventTag(SQLModel, table=True):
    __tablename__ = "event_tag"
    __undoable__ = True

    event_id: int = Field(foreign_key="event.id", primary_key=True)
    tag_id: int = Field(foreign_key="tag.id", primary_key=True)


class EventShare(SQLModel, table=True):
    __tablename__ = "event_share"
    __undoable__ = True

    event_id: int = Field(foreign_key="event.id", primary_key=True)
    user_id: int = Field(foreign_key="user.id", primary_key=True)
    can_edit: bool = True  # sinon : lecture seule


class EventLink(LinkBase, table=True):
    __tablename__ = "event_link"
    __undoable__ = True

    event_id: int = Field(foreign_key="event.id", index=True)


class Board(SQLModel, table=True):
    """Board kanban personnalisé (les boards prédéfinis — statut, échéance… — ne sont pas stockés)."""

    __tablename__ = "board"
    __undoable__ = True

    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id", index=True)
    name: str
    emoji: str = "📊"
    position: float = 0.0
    created_at: datetime = Field(default_factory=utcnow)


class BoardColumn(SQLModel, table=True):
    __tablename__ = "board_column"
    __undoable__ = True

    id: int | None = Field(default=None, primary_key=True)
    board_id: int = Field(foreign_key="board.id", index=True)
    name: str
    emoji: str = ""
    color: str = "#868e96"
    position: float = 0.0


class BoardCard(SQLModel, table=True):
    """Placement d'une tâche sur un board personnalisé (une tâche peut être sur plusieurs boards)."""

    __tablename__ = "board_card"
    __undoable__ = True

    board_id: int = Field(foreign_key="board.id", primary_key=True)
    task_id: int = Field(foreign_key="task.id", primary_key=True)
    column_id: int = Field(foreign_key="board_column.id", index=True)
    position: float = 0.0


class TaskRank(SQLModel, table=True):
    """Rang manuel d'une tâche parmi celles de même urgence (reclassement dans une colonne de kanban) :
    affine l'urgence au-delà de ses 4 niveaux. Rang absent = 0."""

    __tablename__ = "task_rank"
    __undoable__ = True

    task_id: int = Field(foreign_key="task.id", primary_key=True)
    rank: float = 0.0


class BoardShare(SQLModel, table=True):
    """Partage d'un board : ses membres voient (et peuvent modifier) les tâches posées dessus."""

    __tablename__ = "board_share"
    __undoable__ = True

    board_id: int = Field(foreign_key="board.id", primary_key=True)
    user_id: int = Field(foreign_key="user.id", primary_key=True)


class AuthSession(SQLModel, table=True):
    """Session de connexion (cookie du navigateur ou jeton du client bureau).

    Seule l'empreinte SHA-256 du jeton est stockée : une fuite de la base ne permet pas de se connecter.
    """

    __tablename__ = "auth_session"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    token_hash: str = Field(index=True, unique=True)
    kind: str = "web"  # web (cookie) | api (client bureau)
    persistent: bool = False  # « se souvenir de moi »
    label: str = ""  # navigateur / nom de l'appareil
    created_at: datetime = Field(default_factory=utcnow)
    last_seen_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime


class ApiKey(SQLModel, table=True):
    """Jeton d'accès limité à une seule opération (``scope``), sans expiration, révocable.

    Aujourd'hui une seule portée : ``backup`` (télécharger une sauvegarde, pour un script planifié). Créé par
    un administrateur ; il cesse de fonctionner si son créateur perd les droits admin ou est désactivé.
    Comme pour les sessions, seule l'empreinte SHA-256 du jeton est stockée.
    """

    __tablename__ = "api_key"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)  # créateur
    token_hash: str = Field(index=True, unique=True)
    scope: str = "backup"
    label: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    last_used_at: datetime | None = None
    last_used_ip: str = ""


class Attachment(SQLModel, table=True):
    """Fichier envoyé sur le serveur (stocké dans ``data/uploads/<id>``), référencé par un lien de tâche."""

    __tablename__ = "attachment"

    id: str = Field(primary_key=True)  # identifiant aléatoire (hex)
    owner_id: int = Field(foreign_key="user.id", index=True)
    filename: str
    content_type: str = "application/octet-stream"
    size: int = 0
    created_at: datetime = Field(default_factory=utcnow)


class Notification(SQLModel, table=True):
    """Ce qu'un autre utilisateur a fait qui concerne ``user_id`` (partage, modification, suppression d'une
    tâche ou d'un événement). Hors de l'historique annuler / rétablir."""

    __tablename__ = "notification"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)  # destinataire
    actor_id: int = Field(foreign_key="user.id")  # auteur de l'action
    kind: str  # share | unshare | change | delete
    item_type: str  # task | event
    item_id: int
    title: str  # titre de l'élément au moment de l'action
    text: str  # libellé de l'action (celui de l'historique : « Changer l'échéance de « … » »)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)  # dernière action regroupée dans celle-ci
    read_at: datetime | None = None


class UserPref(SQLModel, table=True):
    """Préférence d'affichage d'un utilisateur (filtres, tri, regroupement d'une vue…), valeur JSON."""

    __tablename__ = "user_pref"

    user_id: int = Field(foreign_key="user.id", primary_key=True)
    key: str = Field(primary_key=True)
    value: str = Field(sa_type=Text)
    updated_at: datetime = Field(default_factory=utcnow)


class UndoEntry(SQLModel, table=True):
    """Une action de l'historique annuler / rétablir d'un utilisateur."""

    __tablename__ = "undo_entry"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    label: str
    group_key: str | None = None
    changes: str = Field(sa_type=Text)  # JSON : liste de {table, pk, before, after}
    undone: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


UNDOABLE_TABLES: dict[str, type[SQLModel]] = {
    model.__tablename__: model  # type: ignore[misc]
    for model in (
        Project,
        Tag,
        Task,
        TaskTag,
        TaskShare,
        TaskLink,
        TaskRank,
        Board,
        BoardColumn,
        BoardCard,
        BoardShare,
        Event,
        EventTag,
        EventShare,
        EventLink,
    )
}
