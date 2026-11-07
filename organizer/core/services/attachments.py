"""Pièces jointes : fichiers envoyés sur le serveur et rattachés à une tâche par un lien de type
``attachment`` (cible = identifiant de la pièce jointe).

- Accès : le déposant, et quiconque voit une tâche qui référence la pièce jointe.
- Retirer le lien (annulable) ne supprime pas le fichier : un Ctrl+Z doit pouvoir le retrouver.
"""

from __future__ import annotations

import mimetypes
import secrets
from pathlib import Path
from typing import BinaryIO

from sqlmodel import select

from organizer.core.enums import LinkKind
from organizer.core.errors import InvalidOperation, NotFound
from organizer.core.models import Attachment, TaskLink
from organizer.core.schemas import AttachmentOut, LinkOut
from organizer.core.services.base import BaseService, ServiceContext, quoted
from organizer.core.services.tasks import TaskService

CHUNK = 1024 * 1024


def clean_filename(name: str) -> str:
    """Nom de fichier sans chemin ni caractères de contrôle."""
    base = Path(name.replace("\\", "/")).name.strip()
    base = "".join(ch for ch in base if ch.isprintable())
    return base[:200] or "fichier"


class AttachmentService(BaseService):
    def __init__(self, ctx: ServiceContext, tasks: TaskService, uploads_dir: Path, max_bytes: int):
        super().__init__(ctx)
        self.tasks = tasks
        self.uploads_dir = uploads_dir
        self.max_bytes = max_bytes

    def path_of(self, attachment_id: str) -> Path:
        if not attachment_id.isalnum():
            raise NotFound("Pièce jointe introuvable.")
        return self.uploads_dir / attachment_id

    def upload(
        self, task_id: int, filename: str, stream: BinaryIO, content_type: str | None = None
    ) -> LinkOut:
        """Enregistre le fichier et l'ajoute aux liens de la tâche."""
        name = clean_filename(filename)
        with self.uow() as probe:
            task_title = self.tasks._get(probe.session, task_id).title
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        attachment_id = secrets.token_hex(16)
        final = self.path_of(attachment_id)
        partial = final.with_suffix(".part")
        size = 0
        try:
            with partial.open("wb") as out:
                while chunk := stream.read(CHUNK):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise InvalidOperation(
                            f"Fichier trop volumineux (maximum {self.max_bytes // (1024 * 1024)} Mo)."
                        )
                    out.write(chunk)
            partial.rename(final)
        finally:
            partial.unlink(missing_ok=True)

        guessed = content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
        try:
            with self.uow(label=f"Joindre {quoted(name)} à {quoted(task_title)}") as w:
                s = w.session
                task = self.tasks._get(s, task_id)
                s.add(
                    Attachment(
                        id=attachment_id,
                        owner_id=self.actor.id,
                        filename=name,
                        content_type=guessed,
                        size=size,
                    )
                )
                s.flush()
                link = TaskLink(
                    task_id=task.id,
                    kind=str(LinkKind.ATTACHMENT),
                    target=attachment_id,
                    label=name,
                    position=self.tasks._next_link_position(s, task.id),
                )
                s.add(link)
                self.tasks._touch(s, task)
                s.flush()
                return LinkOut.model_validate(link)
        except Exception:
            final.unlink(missing_ok=True)
            raise

    def get(self, attachment_id: str) -> tuple[AttachmentOut, Path]:
        """Métadonnées et chemin du fichier, si l'utilisateur y a accès."""
        with self.uow() as w:
            s = w.session
            row = s.get(Attachment, attachment_id)
            if row is None or not self._can_read(s, row):
                raise NotFound("Pièce jointe introuvable.")
            path = self.path_of(attachment_id)
            if not path.is_file():
                raise NotFound("Le fichier de cette pièce jointe a disparu du serveur.")
            return AttachmentOut.model_validate(row), path

    def _can_read(self, s, row: Attachment) -> bool:
        if row.owner_id == self.actor.id:
            return True
        task_ids = s.exec(
            select(TaskLink.task_id).where(
                TaskLink.kind == str(LinkKind.ATTACHMENT), TaskLink.target == row.id
            )
        ).all()
        for task_id in task_ids:
            try:
                self.tasks._get(s, task_id)
                return True
            except NotFound:
                continue
        return False
