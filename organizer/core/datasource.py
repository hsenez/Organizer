"""Source de données de l'interface.

L'interface (``organizer/ui``) ne manipule **que** un objet :class:`DataSource`. Deux implémentations :

- :class:`LocalDataSource` (serveur) : appelle directement les services, donc la base SQLite ;
- ``RemoteDataSource`` (client bureau, étape 7) : mêmes méthodes, mais via l'API REST du serveur.

Les sous-objets (``tasks``, ``projects``…) exposent les mêmes méthodes, avec les mêmes signatures, que les
services de :mod:`organizer.core.services` : c'est ce contrat que la version distante doit respecter.
Les appels sont synchrones (rapides en local ; sur le client bureau, un seul utilisateur par processus).
"""

from __future__ import annotations

from typing import Protocol

from organizer.core.schemas import UserOut, UserPublic
from organizer.core.services import Services
from organizer.core.services.attachments import AttachmentService
from organizer.core.services.labels import ProjectService, TagService
from organizer.core.services.tasks import TaskService
from organizer.core.services.undo import UndoService


class DataSource(Protocol):
    user: UserOut
    is_desktop: bool  # True : client bureau (peut ouvrir les fichiers locaux)
    tasks: TaskService
    projects: ProjectService
    tags: TagService
    undo: UndoService
    attachments: AttachmentService

    def users_public(self) -> list[UserPublic]: ...

    def attachment_url(self, attachment_id: str) -> str: ...


class LocalDataSource:
    """Accès direct aux services (côté serveur)."""

    is_desktop = False

    def __init__(self, services: Services, user: UserOut):
        self._services = services
        self.user = user
        self.tasks = services.tasks
        self.projects = services.projects
        self.tags = services.tags
        self.undo = services.undo
        self.attachments = services.attachments

    def users_public(self) -> list[UserPublic]:
        return self._services.users.list_public()

    def attachment_url(self, attachment_id: str) -> str:
        return f"/api/v1/attachments/{attachment_id}"
