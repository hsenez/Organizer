"""Socle commun des services : utilisateur courant, horloge, transactions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Engine

from organizer.core.unit_of_work import UndoPolicy, UnitOfWork


@dataclass(frozen=True)
class Actor:
    """L'utilisateur au nom duquel les services agissent."""

    id: int
    is_admin: bool = False
    reminder_offset_days: int = 2


@dataclass
class ServiceContext:
    engine: Engine
    actor: Actor
    policy: UndoPolicy
    today: Callable[[], date] = date.today


class BaseService:
    def __init__(self, ctx: ServiceContext):
        self.ctx = ctx

    @property
    def actor(self) -> Actor:
        return self.ctx.actor

    def today(self) -> date:
        return self.ctx.today()

    def uow(self, label: str | None = None, group_key: str | None = None) -> UnitOfWork:
        """Transaction ; avec ``label``, l'opération est enregistrée dans l'historique annuler / rétablir."""
        return UnitOfWork(self.ctx.engine, self.actor.id, self.ctx.policy, label=label, group_key=group_key)


def quoted(text: str, limit: int = 40) -> str:
    """« Titre » tronqué pour les libellés de l'historique."""
    text = text.strip()
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return f"« {text} »"
