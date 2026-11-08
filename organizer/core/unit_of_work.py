"""Transactions et enregistrement automatique de l'historique annuler / rétablir.

Chaque opération des services s'exécute dans une :class:`UnitOfWork` (une transaction). Si l'opération porte
un libellé, toutes les lignes des tables « annulables » qu'elle insère, modifie ou supprime sont capturées
(état avant / après) via l'événement SQLAlchemy ``after_flush``, puis enregistrées dans ``undo_entry`` au
moment du commit. Les services n'ont donc rien à faire de particulier pour être annulables.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import Engine, delete, event, inspect
from sqlmodel import Session, select

from organizer.core.models import UndoEntry, utcnow

_RECORDER_KEY = "undo_recorder"


# --- Encodage JSON des valeurs de colonnes ----------------------------------------------------------------


def encode_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"$dt": value.isoformat()}
    if isinstance(value, date):
        return {"$d": value.isoformat()}
    if isinstance(value, time):
        return {"$t": value.isoformat()}
    return value


def decode_value(value: Any) -> Any:
    if isinstance(value, dict):
        if "$dt" in value:
            return datetime.fromisoformat(value["$dt"])
        if "$d" in value:
            return date.fromisoformat(value["$d"])
        if "$t" in value:
            return time.fromisoformat(value["$t"])
    return value


def encode_row(row: dict[str, Any]) -> dict[str, Any]:
    return {k: encode_value(v) for k, v in row.items()}


def decode_row(row: dict[str, Any]) -> dict[str, Any]:
    return {k: decode_value(v) for k, v in row.items()}


# --- Capture des changements ------------------------------------------------------------------------------


@dataclass
class Change:
    table: str
    pk: dict[str, Any]
    before: dict[str, Any] | None  # encodé ; None = la ligne n'existait pas
    after: dict[str, Any] | None  # encodé ; None = la ligne n'existe plus

    def key(self) -> tuple[str, str]:
        return self.table, json.dumps(self.pk, sort_keys=True)

    def to_json(self) -> dict[str, Any]:
        return {"table": self.table, "pk": self.pk, "before": self.before, "after": self.after}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Change:
        return cls(data["table"], data["pk"], data["before"], data["after"])


def merge_changes(older: list[Change], newer: list[Change]) -> list[Change]:
    """Fusionne deux séquences : pour chaque ligne, on garde le *before* le plus ancien et l'*after* le plus
    récent. Les lignes créées puis supprimées (ou revenues à l'identique) disparaissent."""
    merged: dict[tuple[str, str], Change] = {}
    for change in [*older, *newer]:
        key = change.key()
        if key in merged:
            merged[key] = Change(change.table, change.pk, merged[key].before, change.after)
        else:
            merged[key] = Change(change.table, change.pk, change.before, change.after)
    return [c for c in merged.values() if c.before != c.after]


def _row_of(obj: Any, *, old_values: bool) -> dict[str, Any]:
    """Valeurs de colonnes d'un objet ORM ; ``old_values`` = valeurs d'avant modification."""
    state = inspect(obj)
    row: dict[str, Any] = {}
    for attr in state.mapper.column_attrs:
        key = attr.key
        value = state.dict.get(key)
        if old_values:
            history = state.attrs[key].history
            if history.deleted:
                value = history.deleted[0]
            elif history.unchanged:
                value = history.unchanged[0]
        row[attr.columns[0].name] = value
    return encode_row(row)


def _pk_of(obj: Any) -> dict[str, Any]:
    state = inspect(obj)
    mapper = state.mapper
    values = state.identity or mapper.primary_key_from_instance(obj)
    return {col.name: encode_value(v) for col, v in zip(mapper.primary_key, values, strict=True)}


@dataclass
class Recorder:
    changes: list[Change] = field(default_factory=list)

    def capture(self, session: Session) -> None:
        batch: list[Change] = []
        for obj in session.new:
            if getattr(obj, "__undoable__", False):
                batch.append(Change(obj.__tablename__, _pk_of(obj), None, _row_of(obj, old_values=False)))
        for obj in session.dirty:
            if getattr(obj, "__undoable__", False) and session.is_modified(obj, include_collections=False):
                before = _row_of(obj, old_values=True)
                after = _row_of(obj, old_values=False)
                if before != after:
                    batch.append(Change(obj.__tablename__, _pk_of(obj), before, after))
        for obj in session.deleted:
            if getattr(obj, "__undoable__", False):
                batch.append(Change(obj.__tablename__, _pk_of(obj), _row_of(obj, old_values=True), None))
        self.changes = merge_changes(self.changes, batch)


@event.listens_for(Session, "after_flush")
def _after_flush(session: Session, _flush_context: Any) -> None:
    recorder: Recorder | None = session.info.get(_RECORDER_KEY)
    if recorder is not None:
        recorder.capture(session)


# --- Unité de travail -------------------------------------------------------------------------------------


@dataclass
class UndoPolicy:
    history_size: int = 50
    merge_window: timedelta = timedelta(seconds=5)


class UnitOfWork:
    """Transaction ; enregistre une entrée d'historique si ``label`` est fourni.

    ``group_key`` : deux opérations successives du même utilisateur avec la même clé, à moins de
    ``merge_window`` d'intervalle, sont fusionnées en une seule entrée (ex. sauvegarde auto des notes).
    """

    def __init__(
        self,
        engine: Engine,
        user_id: int,
        policy: UndoPolicy,
        label: str | None = None,
        group_key: str | None = None,
        on_commit: Callable[[set[str]], None] | None = None,
    ):
        """``on_commit`` : appelé après la validation avec les tables modifiées (si ``label`` est fourni et
        qu'il y a eu des modifications) — diffusion en temps réel."""
        self.engine = engine
        self.on_commit = on_commit
        self.user_id = user_id
        self.policy = policy
        self.label = label
        self.group_key = group_key
        self.session = Session(engine, expire_on_commit=False)
        self.recorder: Recorder | None = Recorder() if label else None
        if self.recorder is not None:
            self.session.info[_RECORDER_KEY] = self.recorder

    def __enter__(self) -> UnitOfWork:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self.session.flush()
                self._store_history()
                self.session.commit()
                if self.on_commit is not None and self.recorder is not None and self.recorder.changes:
                    self.on_commit({change.table for change in self.recorder.changes})
            else:
                self.session.rollback()
        finally:
            self.session.close()

    def _store_history(self) -> None:
        if self.recorder is None or not self.recorder.changes:
            return
        self.session.info.pop(_RECORDER_KEY, None)
        s = self.session
        now = utcnow()
        # Toute nouvelle action vide la pile « rétablir ».
        s.exec(delete(UndoEntry).where(UndoEntry.user_id == self.user_id, UndoEntry.undone == True))  # noqa: E712
        last = s.exec(
            select(UndoEntry).where(UndoEntry.user_id == self.user_id).order_by(UndoEntry.id.desc()).limit(1)
        ).first()
        if (
            last is not None
            and self.group_key is not None
            and last.group_key == self.group_key
            and now - last.updated_at <= self.policy.merge_window
        ):
            older = [Change.from_json(c) for c in json.loads(last.changes)]
            merged = merge_changes(older, self.recorder.changes)
            if merged:
                last.changes = json.dumps([c.to_json() for c in merged])
                last.updated_at = now
                last.label = self.label or last.label
                s.add(last)
            else:
                s.delete(last)  # l'utilisateur est revenu exactement à l'état initial
        else:
            s.add(
                UndoEntry(
                    user_id=self.user_id,
                    label=self.label or "",
                    group_key=self.group_key,
                    changes=json.dumps([c.to_json() for c in self.recorder.changes]),
                    created_at=now,
                    updated_at=now,
                )
            )
        s.flush()
        # Limite de taille de l'historique.
        ids = s.exec(
            select(UndoEntry.id).where(UndoEntry.user_id == self.user_id).order_by(UndoEntry.id.desc())
        ).all()
        if len(ids) > self.policy.history_size:
            s.exec(delete(UndoEntry).where(UndoEntry.id.in_(ids[self.policy.history_size :])))
