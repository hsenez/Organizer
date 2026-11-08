"""Source de données de l'interface.

L'interface (``organizer/ui``) ne manipule **que** un objet :class:`DataSource`. Deux implémentations :

- :class:`LocalDataSource` (serveur) : appelle directement les services, donc la base SQLite ;
- :class:`organizer.client.remote.RemoteDataSource` (client bureau) : mêmes méthodes, via l'API REST du
  serveur ; elle sait en plus ouvrir liens, fichiers locaux et pièces jointes sur le poste (``open_url``,
  ``open_path``, ``open_attachment``) et enregistrer une sauvegarde (``save_backup``), utilisés quand
  ``is_desktop`` est vrai.

Les sous-objets (``tasks``, ``projects``…) exposent les mêmes méthodes, avec les mêmes signatures, que les
services de :mod:`organizer.core.services` : c'est ce contrat que la version distante doit respecter.
Les appels sont synchrones (rapides en local ; sur le client bureau, un seul utilisateur par processus).
"""

from __future__ import annotations

from typing import Protocol

from organizer.core.schemas import UserOut, UserPublic
from organizer.core.services import Services
from organizer.core.services.account import AccountService
from organizer.core.services.attachments import AttachmentService
from organizer.core.services.boards import BoardService
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
    boards: BoardService
    account: AccountService  # profil, mot de passe, appareils, comptes (admin)

    def users_public(self) -> list[UserPublic]: ...

    def attachment_url(self, attachment_id: str) -> str: ...

    def backup_url(self, uploads: bool = True) -> str: ...


class LocalDataSource:
    """Accès direct aux services (côté serveur)."""

    is_desktop = False

    def __init__(self, services: Services, user: UserOut, account: AccountService):
        self._services = services
        self.user = user
        self.account = account
        self.tasks = services.tasks
        self.projects = services.projects
        self.tags = services.tags
        self.undo = services.undo
        self.attachments = services.attachments
        self.boards = services.boards

    def users_public(self) -> list[UserPublic]:
        return self._services.users.list_public()

    def attachment_url(self, attachment_id: str) -> str:
        return f"/api/v1/attachments/{attachment_id}"

    def backup_url(self, uploads: bool = True) -> str:
        """Sauvegarde du serveur (admin), téléchargée par le navigateur avec le cookie de session."""
        return "/api/v1/admin/backup" + ("" if uploads else "?uploads=false")
