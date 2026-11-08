"""Objets échangés entre les services, l'API et l'interface (Pydantic).

Ce sont ces objets — et non les tables — qui circulent vers l'UI, que les données viennent de la base locale
(serveur) ou de l'API REST (client bureau).

Pour les objets « Patch », seuls les champs **explicitement fournis** sont appliqués
(``model_fields_set``) : passer ``due_date=None`` efface l'échéance, ne pas le passer la laisse intacte.
"""

from __future__ import annotations

from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field

from organizer.core.enums import DueBucket, Importance, LinkKind, Status, TaskKind, Urgency


class _Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Projets ----------------------------------------------------------------------------------------------


class ProjectIn(_Schema):
    name: str = Field(min_length=1, max_length=80)
    emoji: str = "📁"
    color: str = "#5c7cfa"
    description: str = ""
    is_public: bool = False


class ProjectPatch(_Schema):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    emoji: str | None = None
    color: str | None = None
    description: str | None = None
    is_public: bool | None = None
    archived: bool | None = None


class ProjectOut(_Schema):
    id: int
    owner_id: int
    name: str
    emoji: str
    color: str
    description: str
    is_public: bool
    archived: bool
    position: float
    can_edit: bool = False


# --- Tags -------------------------------------------------------------------------------------------------


class TagIn(_Schema):
    name: str = Field(min_length=1, max_length=40)
    # Sans couleur, une couleur bien distincte des tags existants est choisie automatiquement.
    color: str | None = None
    is_public: bool = False
    # Couleurs dont s'éloigner en priorité (tags de la tâche en cours d'édition) ; non enregistré.
    avoid_colors: list[str] = Field(default_factory=list)


class TagPatch(_Schema):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    color: str | None = None
    is_public: bool | None = None


class TagOut(_Schema):
    id: int
    owner_id: int
    name: str
    color: str
    is_public: bool
    position: float
    can_edit: bool = False


# --- Liens ------------------------------------------------------------------------------------------------


class LinkIn(_Schema):
    kind: LinkKind
    target: str = Field(min_length=1)
    label: str = ""


class LinkPatch(_Schema):
    target: str | None = Field(default=None, min_length=1)
    label: str | None = None


class LinkOut(_Schema):
    id: int
    task_id: int
    kind: LinkKind
    target: str
    label: str
    position: float


# --- Tâches -----------------------------------------------------------------------------------------------


class TaskCreate(_Schema):
    title: str = Field(min_length=1, max_length=300)
    importance: Importance = Importance.NORMAL
    urgency: Urgency = Urgency.SOON
    due_date: date | None = None
    due_time: time | None = None
    status: Status = Status.NOT_STARTED
    kind: TaskKind = TaskKind.TODO
    # Suivi : sans décalage ni date manuelle, le décalage par défaut de l'utilisateur s'applique.
    reminder_offset_days: int | None = Field(default=None, ge=0, le=365)
    reminder_date: date | None = None
    notes: str = ""
    project_id: int | None = None
    tag_ids: list[int] = Field(default_factory=list)
    parent_id: int | None = None


class TaskPatch(_Schema):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    importance: Importance | None = None
    urgency: Urgency | None = None
    due_date: date | None = None
    due_time: time | None = None
    status: Status | None = None
    kind: TaskKind | None = None
    # Fournir ``reminder_date`` (non nul) passe en rappel manuel ; fournir ``reminder_offset_days`` repasse
    # en rappel corrélé à l'échéance.
    reminder_offset_days: int | None = Field(default=None, ge=0, le=365)
    reminder_date: date | None = None
    notes: str | None = None
    project_id: int | None = None
    tag_ids: list[int] | None = None


class TaskOut(_Schema):
    id: int
    owner_id: int
    parent_id: int | None
    parent_title: str | None = None
    position: float
    rank: float = 0.0  # rang manuel parmi les tâches de même urgence (reclassement au kanban)
    title: str
    importance: Importance
    urgency: Urgency
    due_date: date | None
    due_time: time | None
    status: Status
    kind: TaskKind
    reminder_offset_days: int | None
    reminder_date: date | None  # date de rappel effective (calculée), None si pas de rappel
    notes: str
    project: ProjectOut | None = None
    tags: list[TagOut] = Field(default_factory=list)
    links: list[LinkOut] = Field(default_factory=list)
    shared_with: list[int] = Field(default_factory=list)
    subtask_count: int = 0  # toutes les sous-tâches, annulées comprises
    subtask_total: int = 0  # sous-tâches non annulées (dénominateur de la progression)
    subtask_done: int = 0
    due_after_parent: bool = False  # sous-tâche dont l'échéance dépasse celle du parent
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    can_delete: bool = False

    @property
    def is_subtask(self) -> bool:
        return self.parent_id is not None

    @property
    def has_subtasks(self) -> bool:
        return self.subtask_count > 0


class TaskFilter(_Schema):
    """Critères de la barre de filtres. Une liste vide = pas de filtre sur ce critère."""

    text: str = ""
    importance: list[Importance] = Field(default_factory=list)
    urgency: list[Urgency] = Field(default_factory=list)
    status: list[Status] = Field(default_factory=list)
    kind: list[TaskKind] = Field(default_factory=list)
    project_ids: list[int | None] = Field(default_factory=list)  # None = « sans projet »
    tag_ids: list[int] = Field(default_factory=list)  # la tâche doit avoir au moins un de ces tags
    due: list[DueBucket] = Field(default_factory=list)
    scope: str = "all"  # all | mine | shared (partagées avec moi)
    include_subtasks: bool = False
    parent_id: int | None = None  # ne lister que les sous-tâches de ce parent


class TaskSort(_Schema):
    key: str = "due"  # due | importance | urgency | priority | created | updated | title | position
    descending: bool = False


# --- Boards personnalisés ---------------------------------------------------------------------------------


class ColumnIn(_Schema):
    name: str = Field(min_length=1, max_length=60)
    emoji: str = ""
    color: str = "#868e96"


class ColumnPatch(_Schema):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    emoji: str | None = None
    color: str | None = None


class ColumnOut(_Schema):
    id: int
    board_id: int
    name: str
    emoji: str
    color: str
    position: float


DEFAULT_COLUMNS = [
    ColumnIn(name="À faire", emoji="📥", color="#868e96"),
    ColumnIn(name="En cours", emoji="🚧", color="#339af0"),
    ColumnIn(name="Fait", emoji="✅", color="#40c057"),
]


class BoardIn(_Schema):
    name: str = Field(min_length=1, max_length=60)
    emoji: str = "📊"
    columns: list[ColumnIn] = Field(default_factory=lambda: [c.model_copy() for c in DEFAULT_COLUMNS])


class BoardPatch(_Schema):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    emoji: str | None = None


class BoardOut(_Schema):
    id: int
    owner_id: int
    name: str
    emoji: str
    position: float
    columns: list[ColumnOut] = Field(default_factory=list)
    shared_with: list[int] = Field(default_factory=list)
    can_manage: bool = False  # propriétaire : colonnes, partage, suppression


class BoardContent(_Schema):
    """Contenu d'un board : tâches visibles par colonne, dans l'ordre."""

    board: BoardOut
    columns: dict[int, list[TaskOut]] = Field(default_factory=dict)


# --- Annuler / rétablir -----------------------------------------------------------------------------------


class UndoStatus(_Schema):
    undo_label: str | None = None  # libellé de l'action qu'annulerait Ctrl+Z
    redo_label: str | None = None


class UndoResult(_Schema):
    action: str  # undo | redo
    label: str
    task_ids: list[int] = Field(default_factory=list)  # tâches touchées (pour rafraîchir l'affichage)


# --- Utilisateurs -----------------------------------------------------------------------------------------


class UserOut(_Schema):
    id: int
    username: str
    display_name: str
    is_admin: bool
    is_active: bool
    theme: str
    reminder_offset_days: int
    desktop_notifications: bool


class UserPublic(_Schema):
    """Ce que tout utilisateur connecté voit des autres (pour le partage)."""

    id: int
    username: str
    display_name: str


class UserCreateIn(_Schema):
    username: str = Field(min_length=1, max_length=40)
    password: str
    display_name: str = ""
    is_admin: bool = False


class ProfilePatch(_Schema):
    display_name: str | None = Field(default=None, min_length=1, max_length=60)
    theme: str | None = Field(default=None, pattern="^(auto|light|dark)$")
    reminder_offset_days: int | None = Field(default=None, ge=0, le=365)
    desktop_notifications: bool | None = None


class PasswordChange(_Schema):
    old_password: str
    new_password: str


class AdminUserPatch(_Schema):
    is_active: bool | None = None
    is_admin: bool | None = None
    new_password: str | None = None


# --- Authentification -------------------------------------------------------------------------------------


class LoginIn(_Schema):
    username: str
    password: str
    device_name: str = ""  # affiché dans « appareils connectés »


class SetupIn(_Schema):
    username: str = Field(min_length=1, max_length=40)
    password: str
    display_name: str = ""


class SessionOut(_Schema):
    id: int
    kind: str  # web | api
    persistent: bool
    label: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    current: bool = False


class LoginOut(_Schema):
    token: str
    user: UserOut
    session: SessionOut


class ApiKeyIn(_Schema):
    label: str = Field(default="", max_length=100)


class ApiKeyOut(_Schema):
    """Jeton d'accès limité (sauvegarde), sans le secret."""

    id: int
    scope: str
    label: str
    user_id: int  # créateur
    created_at: datetime
    last_used_at: datetime | None = None
    last_used_ip: str = ""


class ApiKeyCreated(_Schema):
    """Jeton qui vient d'être créé : le secret n'est transmis **qu'une fois**."""

    token: str
    key: ApiKeyOut


class LocalAccessOut(_Schema):
    """Accès direct au serveur par le réseau local (client bureau) : adresses à essayer et clé du compte,
    avec laquelle le serveur prouve son identité avant que le client ne lui envoie son jeton."""

    urls: list[str] = Field(default_factory=list)
    key: str
    user_id: int


# --- Pièces jointes ---------------------------------------------------------------------------------------


class AttachmentOut(_Schema):
    id: str
    owner_id: int
    filename: str
    content_type: str
    size: int
    created_at: datetime
