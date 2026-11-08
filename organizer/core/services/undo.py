"""Annuler / rétablir (Ctrl+Z, Ctrl+Maj+Z) : rejoue les états avant / après enregistrés par
:mod:`organizer.core.unit_of_work`.

Avant d'appliquer une entrée, on vérifie que chaque ligne est toujours dans l'état attendu ; si quelqu'un l'a
modifiée entre-temps, l'opération est refusée (rien n'est écrasé) et l'entrée est retirée de l'historique pour
ne pas bloquer les suivantes.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session
from sqlmodel import select as sm_select

from organizer.core.errors import UndoConflict
from organizer.core.models import UNDOABLE_TABLES, UndoEntry
from organizer.core.schemas import UndoResult, UndoStatus
from organizer.core.services.base import BaseService
from organizer.core.unit_of_work import Change, decode_row, decode_value, encode_row


class UndoService(BaseService):
    def _last_done(self, s: Session) -> UndoEntry | None:
        return s.exec(
            sm_select(UndoEntry)
            .where(UndoEntry.user_id == self.actor.id, UndoEntry.undone == False)  # noqa: E712
            .order_by(UndoEntry.id.desc())
            .limit(1)
        ).first()

    def _first_undone(self, s: Session) -> UndoEntry | None:
        return s.exec(
            sm_select(UndoEntry)
            .where(UndoEntry.user_id == self.actor.id, UndoEntry.undone == True)  # noqa: E712
            .order_by(UndoEntry.id)
            .limit(1)
        ).first()

    def status(self) -> UndoStatus:
        with Session(self.ctx.engine) as s:
            last = self._last_done(s)
            nxt = self._first_undone(s)
            return UndoStatus(undo_label=last.label if last else None, redo_label=nxt.label if nxt else None)

    def undo(self) -> UndoResult | None:
        """Annule la dernière action ; None s'il n'y a rien à annuler."""
        return self._run("undo")

    def redo(self) -> UndoResult | None:
        """Rétablit la dernière action annulée ; None s'il n'y a rien à rétablir."""
        return self._run("redo")

    def _run(self, action: str) -> UndoResult | None:
        with Session(self.ctx.engine) as s:
            s.connection().exec_driver_sql("PRAGMA defer_foreign_keys = ON")
            entry = self._last_done(s) if action == "undo" else self._first_undone(s)
            if entry is None:
                return None
            entry_id, label = entry.id, entry.label
            changes = [Change.from_json(c) for c in json.loads(entry.changes)]
            try:
                if action == "undo":
                    for change in reversed(changes):
                        _apply(s, change.table, change.pk, expected=change.after, target=change.before)
                else:
                    for change in changes:
                        _apply(s, change.table, change.pk, expected=change.before, target=change.after)
                entry.undone = action == "undo"
                s.add(entry)
                s.commit()
            except (_Mismatch, IntegrityError) as exc:  # conflit détecté, ou intégrité violée au commit
                s.rollback()
                verb = "d'annuler" if action == "undo" else "de rétablir"
                with Session(self.ctx.engine) as cleanup:
                    stale = cleanup.get(UndoEntry, entry_id)
                    if stale is not None:
                        cleanup.delete(stale)
                        cleanup.commit()
                raise UndoConflict(
                    f"Impossible {verb} — {label} : les données ont été modifiées depuis. "
                    "Cette action a été retirée de l'historique."
                ) from exc
        self.notify({change.table for change in changes})
        return UndoResult(action=action, label=label, task_ids=_task_ids(changes))


class _Mismatch(Exception):
    pass


def _apply(
    s: Session,
    table_name: str,
    pk: dict[str, Any],
    expected: dict[str, Any] | None,
    target: dict[str, Any] | None,
) -> None:
    table = UNDOABLE_TABLES[table_name].__table__
    where = and_(*(table.c[col] == decode_value(value) for col, value in pk.items()))
    conn = s.connection()
    current_row = conn.execute(select(table).where(where)).mappings().first()
    current = encode_row(dict(current_row)) if current_row is not None else None
    if current != expected:
        raise _Mismatch(table_name, pk)
    if target is None:
        conn.execute(table.delete().where(where))
    elif current is None:
        conn.execute(table.insert().values(**decode_row(target)))
    else:
        conn.execute(table.update().where(where).values(**decode_row(target)))


def _task_ids(changes: list[Change]) -> list[int]:
    ids: set[int] = set()
    for change in changes:
        row = change.after or change.before or {}
        if change.table == "task":
            ids.add(change.pk["id"])
            if row.get("parent_id"):
                ids.add(row["parent_id"])
        elif "task_id" in row:
            ids.add(row["task_id"])
    return sorted(ids)
