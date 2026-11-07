"""Services métier : point d'entrée unique :class:`Services`, lié à un utilisateur."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

from sqlalchemy import Engine

from organizer.config import Settings
from organizer.core.services.attachments import AttachmentService
from organizer.core.services.auth import AuthService
from organizer.core.services.base import Actor, ServiceContext
from organizer.core.services.labels import ProjectService, TagService
from organizer.core.services.tasks import TaskService
from organizer.core.services.undo import UndoService
from organizer.core.services.users import UserService
from organizer.core.unit_of_work import UndoPolicy


class Services:
    """Tous les services, au nom d'un utilisateur donné."""

    def __init__(
        self,
        engine: Engine,
        actor: Actor,
        settings: Settings | None = None,
        today: Callable[[], date] | None = None,
    ):
        settings = settings or Settings()
        policy = UndoPolicy(
            history_size=settings.undo_history_size,
            merge_window=timedelta(seconds=settings.undo_merge_window_seconds),
        )
        ctx = ServiceContext(engine=engine, actor=actor, policy=policy, today=today or date.today)
        self.actor = actor
        self.users = UserService(engine)
        self.projects = ProjectService(ctx)
        self.tags = TagService(ctx)
        self.tasks = TaskService(ctx, self.projects, self.tags)
        self.undo = UndoService(ctx)
        self.attachments = AttachmentService(
            ctx, self.tasks, settings.uploads_dir, max_bytes=settings.max_upload_mb * 1024 * 1024
        )

    @classmethod
    def for_user(cls, engine: Engine, user_id: int, **kwargs) -> Services:
        return cls(engine, UserService(engine).actor_for(user_id), **kwargs)


__all__ = ["Actor", "AuthService", "Services", "UserService"]
