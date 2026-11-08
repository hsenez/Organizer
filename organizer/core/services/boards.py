"""Boards kanban personnalisés : colonnes libres, cartes rangées à la main, partage.

- Le **propriétaire** gère le board (nom, colonnes, partage, suppression).
- Les **membres** (board partagé) voient les tâches posées dessus et peuvent déplacer, ajouter, retirer des
  cartes ; la visibilité des tâches est assurée par ``TaskService._visible_clause``.
- Une tâche peut figurer sur plusieurs boards, une fois par board.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func, or_
from sqlmodel import Session, select

from organizer.core.errors import Forbidden, InvalidOperation, NotFound
from organizer.core.models import Board, BoardCard, BoardColumn, BoardShare, User
from organizer.core.schemas import (
    BoardContent,
    BoardIn,
    BoardOut,
    BoardPatch,
    ColumnIn,
    ColumnOut,
    ColumnPatch,
    TaskFilter,
    TaskOut,
)
from organizer.core.services.base import BaseService, ServiceContext, quoted
from organizer.core.services.tasks import TaskService


class BoardService(BaseService):
    def __init__(self, ctx: ServiceContext, tasks: TaskService):
        super().__init__(ctx)
        self.tasks = tasks

    # --- accès ---

    def _visible_clause(self):
        me = self.actor.id
        return or_(
            Board.owner_id == me, Board.id.in_(select(BoardShare.board_id).where(BoardShare.user_id == me))
        )

    def _get(self, s: Session, board_id: int) -> Board:
        board = s.exec(select(Board).where(Board.id == board_id, self._visible_clause())).first()
        if board is None:
            raise NotFound("Board introuvable.")
        return board

    def _get_managed(self, s: Session, board_id: int) -> Board:
        board = self._get(s, board_id)
        if board.owner_id != self.actor.id:
            raise Forbidden("Seul le propriétaire du board peut le modifier.")
        return board

    def _column(self, s: Session, column_id: int) -> tuple[BoardColumn, Board]:
        column = s.get(BoardColumn, column_id)
        if column is None:
            raise NotFound("Colonne introuvable.")
        return column, self._get(s, column.board_id)

    def _out(self, s: Session, board: Board) -> BoardOut:
        columns = s.exec(
            select(BoardColumn)
            .where(BoardColumn.board_id == board.id)
            .order_by(BoardColumn.position, BoardColumn.id)
        ).all()
        shares = s.exec(select(BoardShare.user_id).where(BoardShare.board_id == board.id)).all()
        return BoardOut(
            id=board.id,
            owner_id=board.owner_id,
            name=board.name,
            emoji=board.emoji,
            position=board.position,
            columns=[ColumnOut.model_validate(c) for c in columns],
            shared_with=sorted(shares),
            can_manage=board.owner_id == self.actor.id,
        )

    # --- lecture ---

    def list(self) -> list[BoardOut]:
        with self.uow() as w:
            boards = w.session.exec(
                select(Board).where(self._visible_clause()).order_by(Board.position, Board.id)
            ).all()
            return [self._out(w.session, b) for b in boards]

    def get(self, board_id: int) -> BoardOut:
        with self.uow() as w:
            return self._out(w.session, self._get(w.session, board_id))

    def content(self, board_id: int, flt: TaskFilter | None = None) -> BoardContent:
        """Tâches du board par colonne (dans l'ordre des cartes), restreintes par ``flt``."""
        with self.uow() as w:
            s = w.session
            board = self._out(s, self._get(s, board_id))
            cards = s.exec(
                select(BoardCard).where(BoardCard.board_id == board_id).order_by(BoardCard.position)
            ).all()
        flt = (flt or TaskFilter()).model_copy(update={"include_subtasks": True, "parent_id": None})
        by_id = {t.id: t for t in self.tasks.list(flt)}
        columns: dict[int, list[TaskOut]] = defaultdict(list)
        for card in cards:
            task = by_id.get(card.task_id)
            if task is not None:
                columns[card.column_id].append(task)
        return BoardContent(board=board, columns={c.id: columns.get(c.id, []) for c in board.columns})

    # --- board ---

    def create(self, data: BoardIn) -> BoardOut:
        name = data.name.strip()
        with self.uow(label=f"Créer le board {quoted(name)}") as w:
            s = w.session
            current = s.exec(select(func.max(Board.position))).one()
            board = Board(owner_id=self.actor.id, name=name, emoji=data.emoji, position=(current or 0.0) + 1)
            s.add(board)
            s.flush()
            for position, column in enumerate(data.columns):
                s.add(BoardColumn(board_id=board.id, position=float(position), **column.model_dump()))
            s.flush()
            return self._out(s, board)

    def update(self, board_id: int, patch: BoardPatch) -> BoardOut:
        with self.uow() as probe:
            name = self._get(probe.session, board_id).name
        with self.uow(label=f"Modifier le board {quoted(name)}") as w:
            board = self._get_managed(w.session, board_id)
            for key, value in patch.model_dump(exclude_unset=True).items():
                if value is not None:
                    setattr(board, key, value.strip() if isinstance(value, str) else value)
            w.session.add(board)
            w.session.flush()
            return self._out(w.session, board)

    def delete(self, board_id: int) -> None:
        """Supprime le board (les tâches, elles, restent)."""
        with self.uow() as probe:
            name = self._get(probe.session, board_id).name
        with self.uow(label=f"Supprimer le board {quoted(name)}") as w:
            s = w.session
            board = self._get_managed(s, board_id)
            for model in (BoardCard, BoardShare):
                for row in s.exec(select(model).where(model.board_id == board_id)).all():
                    s.delete(row)
            s.flush()
            for column in s.exec(select(BoardColumn).where(BoardColumn.board_id == board_id)).all():
                s.delete(column)
            s.flush()
            s.delete(board)

    def set_shares(self, board_id: int, user_ids: list[int]) -> BoardOut:
        with self.uow() as probe:
            name = self._get(probe.session, board_id).name
        with self.uow(label=f"Partager le board {quoted(name)}") as w:
            s = w.session
            board = self._get_managed(s, board_id)
            wanted = set(user_ids) - {board.owner_id}
            if wanted - set(s.exec(select(User.id).where(User.id.in_(wanted))).all()):
                raise NotFound("Utilisateur introuvable.")
            current = {
                sh.user_id: sh
                for sh in s.exec(select(BoardShare).where(BoardShare.board_id == board_id)).all()
            }
            for user_id, share in current.items():
                if user_id not in wanted:
                    s.delete(share)
            for user_id in wanted - current.keys():
                s.add(BoardShare(board_id=board_id, user_id=user_id))
            s.flush()
            return self._out(s, board)

    # --- colonnes ---

    def add_column(self, board_id: int, data: ColumnIn) -> BoardOut:
        with self.uow() as probe:
            name = self._get(probe.session, board_id).name
        with self.uow(label=f"Ajouter la colonne {quoted(data.name)} à {quoted(name)}") as w:
            s = w.session
            board = self._get_managed(s, board_id)
            current = s.exec(
                select(func.max(BoardColumn.position)).where(BoardColumn.board_id == board_id)
            ).one()
            s.add(BoardColumn(board_id=board_id, position=(current or 0.0) + 1, **data.model_dump()))
            s.flush()
            return self._out(s, board)

    def update_column(self, column_id: int, patch: ColumnPatch) -> BoardOut:
        with self.uow() as probe:
            column, _ = self._column(probe.session, column_id)
            name = column.name
        with self.uow(label=f"Modifier la colonne {quoted(name)}") as w:
            s = w.session
            column, board = self._column(s, column_id)
            self._get_managed(s, board.id)
            for key, value in patch.model_dump(exclude_unset=True).items():
                if value is not None:
                    setattr(column, key, value.strip() if isinstance(value, str) else value)
            s.add(column)
            s.flush()
            return self._out(s, board)

    def delete_column(self, column_id: int) -> BoardOut:
        """Supprime une colonne ; ses cartes passent dans la première colonne restante (ou quittent le board
        s'il n'en reste aucune)."""
        with self.uow() as probe:
            column, _ = self._column(probe.session, column_id)
            name = column.name
        with self.uow(label=f"Supprimer la colonne {quoted(name)}") as w:
            s = w.session
            column, board = self._column(s, column_id)
            self._get_managed(s, board.id)
            others = s.exec(
                select(BoardColumn)
                .where(BoardColumn.board_id == board.id, BoardColumn.id != column_id)
                .order_by(BoardColumn.position)
            ).all()
            fallback = others[0] if others else None
            offset = self._max_card_position(s, board.id, fallback.id) if fallback else 0.0
            for card in s.exec(
                select(BoardCard).where(BoardCard.column_id == column_id).order_by(BoardCard.position)
            ).all():
                if fallback is None:
                    s.delete(card)
                else:
                    offset += 1
                    card.column_id = fallback.id
                    card.position = offset
                    s.add(card)
            s.flush()
            s.delete(column)
            s.flush()
            return self._out(s, board)

    def reorder_columns(self, board_id: int, column_ids: list[int]) -> BoardOut:
        with self.uow() as probe:
            name = self._get(probe.session, board_id).name
        with self.uow(label=f"Réordonner les colonnes de {quoted(name)}") as w:
            s = w.session
            board = self._get_managed(s, board_id)
            columns = {
                c.id: c for c in s.exec(select(BoardColumn).where(BoardColumn.board_id == board_id)).all()
            }
            if set(column_ids) != columns.keys():
                raise InvalidOperation("La liste des colonnes ne correspond pas.")
            for position, column_id in enumerate(column_ids):
                columns[column_id].position = float(position)
                s.add(columns[column_id])
            s.flush()
            return self._out(s, board)

    # --- cartes ---

    def _max_card_position(self, s: Session, board_id: int, column_id: int) -> float:
        current = s.exec(
            select(func.max(BoardCard.position)).where(
                BoardCard.board_id == board_id, BoardCard.column_id == column_id
            )
        ).one()
        return current or 0.0

    def place(self, board_id: int, task_id: int, column_id: int, index: int | None = None) -> None:
        """Pose (ou déplace) une tâche dans une colonne, à la position ``index`` (par défaut : en fin de
        colonne)."""
        with self.uow() as probe:
            s = probe.session
            board = self._get(s, board_id)
            task = self.tasks._get(s, task_id)
            column, _ = self._column(s, column_id)
            if column.board_id != board.id:
                raise InvalidOperation("Cette colonne n'appartient pas à ce board.")
            column_name = f"{column.emoji} {column.name}".strip()
            label = f"Déplacer {quoted(task.title)} dans « {column_name} »"
        with self.uow(label=label, group_key=f"board:{board_id}:task:{task_id}") as w:
            s = w.session
            card = s.get(BoardCard, (board_id, task_id))
            siblings = [
                c
                for c in s.exec(
                    select(BoardCard)
                    .where(BoardCard.board_id == board_id, BoardCard.column_id == column_id)
                    .order_by(BoardCard.position)
                ).all()
                if c.task_id != task_id
            ]
            if card is None:
                card = BoardCard(board_id=board_id, task_id=task_id, column_id=column_id)
            card.column_id = column_id
            index = len(siblings) if index is None else max(0, min(index, len(siblings)))
            siblings.insert(index, card)
            for position, item in enumerate(siblings):
                if item.position != float(position) or item is card:
                    item.position = float(position)
                    s.add(item)

    def remove(self, board_id: int, task_id: int) -> None:
        """Retire une tâche du board (la tâche elle-même n'est pas supprimée)."""
        with self.uow() as probe:
            self._get(probe.session, board_id)
            title = self.tasks._get(probe.session, task_id).title
        with self.uow(label=f"Retirer {quoted(title)} du board") as w:
            card = w.session.get(BoardCard, (board_id, task_id))
            if card is not None:
                w.session.delete(card)

    def boards_of_task(self, task_id: int) -> list[int]:
        """Boards (visibles) sur lesquels figure la tâche."""
        with self.uow() as w:
            ids = w.session.exec(select(BoardCard.board_id).where(BoardCard.task_id == task_id)).all()
            visible = set(w.session.exec(select(Board.id).where(self._visible_clause())).all())
            return [i for i in ids if i in visible]
