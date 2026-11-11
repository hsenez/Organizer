"""Tâches : création, modification, sous-tâches, liens, partage, filtres et tri.

Visibilité : une tâche est visible (et modifiable) par son propriétaire, par les utilisateurs avec qui elle
est partagée, et par tous ceux qui voient son parent (les sous-tâches suivent leur parent). La suppression
est réservée au propriétaire de la tâche ou de son parent.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, time

from sqlalchemy import func, or_
from sqlalchemy.orm import aliased
from sqlmodel import Session, select

from organizer.core import rules
from organizer.core.enums import Status, TaskKind
from organizer.core.errors import Forbidden, InvalidOperation, NotFound
from organizer.core.models import (
    BoardCard,
    BoardShare,
    Task,
    TaskLink,
    TaskRank,
    TaskShare,
    TaskTag,
    User,
    utcnow,
)
from organizer.core.schemas import (
    TaskCreate,
    TaskFilter,
    TaskOut,
    TaskPatch,
    TaskSort,
)
from organizer.core.services.base import quoted
from organizer.core.services.items import ItemService

_REQUIRED_FIELDS = {"title", "importance", "urgency", "status", "kind", "notes"}


class TaskService(ItemService):
    model = Task
    tag_model = TaskTag
    share_model = TaskShare
    link_model = TaskLink
    fk = "task_id"
    not_found = "Tâche introuvable."

    # ==================================================================================================
    # Visibilité
    # ==================================================================================================

    def _visible_clause(self):
        me = self.actor.id
        shared_ids = select(TaskShare.task_id).where(TaskShare.user_id == me)
        # Tâches posées sur un board partagé avec moi.
        on_shared_boards = select(BoardCard.task_id).where(
            BoardCard.board_id.in_(select(BoardShare.board_id).where(BoardShare.user_id == me))
        )
        parent = aliased(Task)
        visible_parents = select(parent.id).where(
            or_(parent.owner_id == me, parent.id.in_(shared_ids), parent.id.in_(on_shared_boards))
        )
        return or_(
            Task.owner_id == me,
            Task.id.in_(shared_ids),
            Task.id.in_(on_shared_boards),
            Task.parent_id.in_(visible_parents),
        )

    def _get(self, s: Session, task_id: int) -> Task:
        task = s.exec(select(Task).where(Task.id == task_id, self._visible_clause())).first()
        if task is None:
            raise NotFound("Tâche introuvable.")
        return task

    def _can_delete(self, s: Session, task: Task) -> bool:
        """Propriétaire de la tâche ou de son parent ; ou toute personne qui la voit (donc peut la
        modifier) si son propriétaire est désactivé."""
        if task.owner_id == self.actor.id:
            return True
        owner = s.get(User, task.owner_id)
        if owner is not None and not owner.is_active:
            return True
        if task.parent_id is not None:
            parent = s.get(Task, task.parent_id)
            return parent is not None and parent.owner_id == self.actor.id
        return False

    # ==================================================================================================
    # Construction des objets de sortie
    # ==================================================================================================

    def _build(self, s: Session, tasks: list[Task]) -> list[TaskOut]:
        if not tasks:
            return []
        ids = [t.id for t in tasks]
        me = self.actor.id
        inactive = set(s.exec(self._inactive_owners()).all())

        visible_projects = self._visible_projects(s)
        tags_by_task = self._tags_by_item(s, ids)
        links_by_task = self._links_by_item(s, ids)

        ranks = {r.task_id: r.rank for r in s.exec(select(TaskRank).where(TaskRank.task_id.in_(ids))).all()}

        shares_by_task = self._shares_by_item(s, ids)

        sub_count: dict[int, int] = defaultdict(int)
        sub_total: dict[int, int] = defaultdict(int)
        sub_done: dict[int, int] = defaultdict(int)
        for parent_id, status in s.exec(
            select(Task.parent_id, Task.status).where(Task.parent_id.in_(ids))
        ).all():
            sub_count[parent_id] += 1
            if status != Status.CANCELLED:
                sub_total[parent_id] += 1
            if status == Status.DONE:
                sub_done[parent_id] += 1

        parent_ids = {t.parent_id for t in tasks if t.parent_id is not None}
        parents = (
            {
                row.id: row
                for row in s.exec(
                    select(Task.id, Task.title, Task.due_date, Task.owner_id).where(Task.id.in_(parent_ids))
                ).all()
            }
            if parent_ids
            else {}
        )

        outs: list[TaskOut] = []
        for t in tasks:
            parent = parents.get(t.parent_id) if t.parent_id is not None else None
            kind = TaskKind(t.kind)
            outs.append(
                TaskOut(
                    id=t.id,
                    owner_id=t.owner_id,
                    parent_id=t.parent_id,
                    parent_title=parent.title if parent else None,
                    position=t.position,
                    rank=ranks.get(t.id, 0.0),
                    title=t.title,
                    importance=t.importance,
                    urgency=t.urgency,
                    due_date=t.due_date,
                    due_time=t.due_time,
                    status=t.status,
                    kind=kind,
                    reminder_offset_days=t.reminder_offset_days,
                    reminder_date=rules.effective_reminder(
                        kind, t.due_date, t.reminder_offset_days, t.reminder_manual_date
                    ),
                    notes=t.notes,
                    project=self._project_out(visible_projects, t.project_id),
                    tags=tags_by_task[t.id],
                    links=links_by_task[t.id],
                    shared_with=sorted(share.user_id for share in shares_by_task[t.id]),
                    subtask_count=sub_count[t.id],
                    subtask_total=sub_total[t.id],
                    subtask_done=sub_done[t.id],
                    due_after_parent=bool(
                        parent and t.due_date and parent.due_date and t.due_date > parent.due_date
                    ),
                    created_at=t.created_at,
                    updated_at=t.updated_at,
                    completed_at=t.completed_at,
                    can_delete=t.owner_id == me
                    or bool(parent and parent.owner_id == me)
                    or t.owner_id in inactive,
                )
            )
        return outs

    def _out(self, s: Session, task: Task) -> TaskOut:
        return self._build(s, [task])[0]

    # ==================================================================================================
    # Lecture
    # ==================================================================================================

    def get(self, task_id: int) -> TaskOut:
        with self.uow() as w:
            return self._out(w.session, self._get(w.session, task_id))

    def subtasks(self, parent_id: int) -> list[TaskOut]:
        return self.list(TaskFilter(parent_id=parent_id, include_subtasks=True), TaskSort(key="position"))

    def list(self, flt: TaskFilter | None = None, sort: TaskSort | None = None) -> list[TaskOut]:
        flt = flt or TaskFilter()
        sort = sort or TaskSort()
        me = self.actor.id
        with self.uow() as w:
            s = w.session
            query = select(Task).where(self._visible_clause())
            if flt.parent_id is not None:
                query = query.where(Task.parent_id == flt.parent_id)
            elif not flt.include_subtasks:
                query = query.where(Task.parent_id.is_(None))
            if flt.scope == "mine":
                query = query.where(Task.owner_id == me)
            elif flt.scope == "shared":
                query = query.where(Task.owner_id != me)
            if flt.importance:
                query = query.where(Task.importance.in_([int(v) for v in flt.importance]))
            if flt.urgency:
                query = query.where(Task.urgency.in_([int(v) for v in flt.urgency]))
            if flt.status:
                query = query.where(Task.status.in_([str(v) for v in flt.status]))
            if flt.kind:
                query = query.where(Task.kind.in_([str(v) for v in flt.kind]))
            if flt.project_ids:
                real_ids = [p for p in flt.project_ids if p is not None]
                clauses = [Task.project_id.in_(real_ids)] if real_ids else []
                if None in flt.project_ids:
                    clauses.append(Task.project_id.is_(None))
                query = query.where(or_(*clauses))
            if flt.tag_ids:
                query = query.where(
                    Task.id.in_(select(TaskTag.task_id).where(TaskTag.tag_id.in_(flt.tag_ids)))
                )
            outs = self._build(s, list(s.exec(query).all()))

        today = self.today()
        if flt.due:
            wanted = set(flt.due)
            outs = [t for t in outs if rules.due_bucket(t.due_date, today) in wanted]
        if flt.text.strip():
            needles = rules.normalize_text(flt.text).split()
            outs = [t for t in outs if all(n in _haystack(t) for n in needles)]
        return sort_tasks(outs, sort)

    def reminders_due(self) -> list[TaskOut]:
        """Tâches de suivi ouvertes dont la date de rappel est atteinte (sous-tâches comprises)."""
        today = self.today()
        tasks = self.list(
            TaskFilter(kind=[TaskKind.FOLLOWUP], include_subtasks=True),
            TaskSort(key="due"),
        )
        return [
            t
            for t in tasks
            if not t.status.is_closed and t.reminder_date is not None and t.reminder_date <= today
        ]

    # ==================================================================================================
    # Écriture
    # ==================================================================================================

    def _next_position(self, s: Session, parent_id: int | None) -> float:
        query = select(func.max(Task.position))
        query = query.where(Task.parent_id.is_(None) if parent_id is None else Task.parent_id == parent_id)
        current = s.exec(query).one()
        return (current or 0.0) + 1.0

    def _set_status(self, s: Session, task: Task, status: Status) -> None:
        if task.status == status:
            return
        task.status = str(status)
        task.completed_at = utcnow() if status is Status.DONE else None
        if status is Status.IN_PROGRESS and task.parent_id is not None:
            # Démarrer une sous-tâche démarre le parent.
            parent = s.get(Task, task.parent_id)
            if parent is not None and parent.status == Status.NOT_STARTED:
                parent.status = str(Status.IN_PROGRESS)
                parent.updated_at = utcnow()
                s.add(parent)

    def _ensure_followup_reminder(self, task: Task) -> None:
        if (
            task.kind == TaskKind.FOLLOWUP
            and task.reminder_offset_days is None
            and task.reminder_manual_date is None
        ):
            # Valeur actuelle du réglage (elle a pu changer depuis l'ouverture de la page).
            with Session(self.ctx.engine) as s:
                current = s.get(User, self.actor.id)
            task.reminder_offset_days = (
                current.reminder_offset_days if current is not None else self.actor.reminder_offset_days
            )

    def create(self, data: TaskCreate) -> TaskOut:
        given = data.model_fields_set
        title = data.title.strip()
        if not title:
            raise InvalidOperation("Le titre est obligatoire.")
        label = f"Créer {quoted(title)}"
        if data.parent_id is not None:
            with self.uow() as probe:
                parent_title = self._get(probe.session, data.parent_id).title
                label = f"Ajouter la sous-tâche {quoted(title)} à {quoted(parent_title)}"
        with self.uow(label=label) as w:
            s = w.session
            values = data.model_dump(exclude={"tag_ids", "reminder_date", "status"})
            if data.parent_id is not None:
                parent = self._get(s, data.parent_id)
                if parent.parent_id is not None:
                    raise InvalidOperation("Un seul niveau de sous-tâches est possible.")
                # Héritage des attributs du parent, sauf s'ils sont fournis explicitement.
                for key in ("importance", "urgency", "due_date", "project_id"):
                    if key not in given:
                        values[key] = getattr(parent, key)
            self._check_project(s, values["project_id"])
            task = Task(
                **{k: v for k, v in values.items() if k != "title"},
                title=title,
                owner_id=self.actor.id,
                reminder_manual_date=data.reminder_date,
                position=self._next_position(s, data.parent_id),
            )
            task.importance = int(task.importance)
            task.urgency = int(task.urgency)
            task.kind = str(data.kind)
            if data.reminder_date is not None:
                task.reminder_offset_days = None
            self._ensure_followup_reminder(task)
            s.add(task)
            s.flush()
            self._set_status(s, task, data.status)
            if data.tag_ids:
                self._set_tags(s, task, data.tag_ids)
            s.add(task)
            s.flush()
            return self._out(s, task)

    def update(self, task_id: int, patch: TaskPatch) -> TaskOut:
        fields = {k: getattr(patch, k) for k in patch.model_fields_set}
        if not fields:
            return self.get(task_id)
        for key in _REQUIRED_FIELDS & fields.keys():
            if fields[key] is None:
                raise InvalidOperation(f"Le champ « {key} » ne peut pas être vide.")
        with self.uow() as probe:
            current = self._get(probe.session, task_id)
            label = _update_label(current.title, fields)
        group_key = f"task:{task_id}:{','.join(sorted(fields))}"
        with self.uow(label=label, group_key=group_key) as w:
            s = w.session
            task = self._get(s, task_id)
            self._apply(s, task, fields)
            s.add(task)
            s.flush()
            return self._out(s, task)

    def move(self, task_id: int, patch: TaskPatch | None = None, order: list[int] | None = None) -> TaskOut:
        """Glisser-déposer dans un kanban : applique ``patch`` (changement de colonne) puis, si ``order`` est
        fourni (identifiants de la colonne d'arrivée, dans l'ordre affiché, carte déplacée comprise), reclasse
        la carte : son urgence est ajustée à celles de ses voisines et son rang manuel fixé
        (``rules.rank_drop``). Une seule entrée d'historique."""
        fields = {k: getattr(patch, k) for k in patch.model_fields_set} if patch else {}
        for key in _REQUIRED_FIELDS & fields.keys():
            if fields[key] is None:
                raise InvalidOperation(f"Le champ « {key} » ne peut pas être vide.")
        if order is not None and task_id not in order:
            raise InvalidOperation("La tâche déplacée doit figurer dans l'ordre de la colonne.")
        with self.uow() as probe:
            title = self._get(probe.session, task_id).title
        label = _update_label(title, fields) if fields else f"Reclasser {quoted(title)}"
        with self.uow(label=label) as w:
            s = w.session
            task = self._get(s, task_id)
            if fields:
                self._apply(s, task, fields)
            if order:
                others = {
                    t.id: t for t in s.exec(select(Task).where(Task.id.in_(order), self._visible_clause()))
                }
                if others.keys() != set(order):
                    raise NotFound("Tâche introuvable.")
                ranks = {r.task_id: r for r in s.exec(select(TaskRank).where(TaskRank.task_id.in_(order)))}
                rows = [
                    (
                        tid,
                        task.urgency if tid == task_id else others[tid].urgency,
                        ranks[tid].rank if tid in ranks else 0.0,
                    )
                    for tid in order
                ]
                urgency, changes = rules.rank_drop(rows, task_id)
                if int(urgency) != task.urgency:
                    if label.startswith("Reclasser"):
                        label = (
                            f"Reclasser {quoted(title)} (urgence : {urgency.meta.emoji} {urgency.meta.label})"
                        )
                        w.label = label
                    task.urgency = int(urgency)
                    fields["urgency"] = urgency
                for tid, rank in changes.items():
                    row = ranks.get(tid) or TaskRank(task_id=tid)
                    row.rank = rank
                    s.add(row)
            if fields:
                task.updated_at = utcnow()
                s.add(task)
            s.flush()
            return self._out(s, task)

    def _apply(self, s: Session, task: Task, fields: dict) -> None:
        """Applique des champs de ``TaskPatch`` à ``task`` (sans enregistrer)."""
        if "title" in fields:
            title = fields["title"].strip()
            if not title:
                raise InvalidOperation("Le titre est obligatoire.")
            task.title = title
        for key in ("importance", "urgency"):
            if key in fields:
                setattr(task, key, int(fields[key]))
        for key in ("due_date", "due_time", "notes"):
            if key in fields:
                setattr(task, key, fields[key])
        if "due_date" in fields and fields["due_date"] is None:
            task.due_time = None  # pas d'heure sans date
        if "kind" in fields:
            task.kind = str(fields["kind"])
        if "reminder_date" in fields:
            task.reminder_manual_date = fields["reminder_date"]
            if fields["reminder_date"] is not None or "reminder_offset_days" not in fields:
                task.reminder_offset_days = None
        if "reminder_offset_days" in fields:
            task.reminder_offset_days = fields["reminder_offset_days"]
        if "kind" in fields and "reminder_date" not in fields:
            self._ensure_followup_reminder(task)
        if "project_id" in fields:
            self._check_project(s, fields["project_id"])
            task.project_id = fields["project_id"]
        if "tag_ids" in fields:
            self._set_tags(s, task, fields["tag_ids"] or [])
        if "status" in fields:
            self._set_status(s, task, fields["status"])
        task.updated_at = utcnow()

    def _delete_row(self, s: Session, task: Task) -> None:
        for model in (TaskTag, TaskShare, TaskLink, TaskRank, BoardCard):
            for row in s.exec(select(model).where(model.task_id == task.id)).all():
                s.delete(row)
        s.flush()
        s.delete(task)

    def delete(self, task_id: int, with_subtasks: bool = False) -> None:
        """Supprime une tâche ; ses sous-tâches sont supprimées aussi, ou détachées (deviennent
        indépendantes) selon ``with_subtasks``."""
        with self.uow() as probe:
            title = self._get(probe.session, task_id).title
        with self.uow(label=f"Supprimer {quoted(title)}") as w:
            s = w.session
            task = self._get(s, task_id)
            if not self._can_delete(s, task):
                raise Forbidden("Seul le propriétaire peut supprimer cette tâche.")
            for sub in s.exec(select(Task).where(Task.parent_id == task.id).order_by(Task.position)).all():
                if with_subtasks:
                    self._delete_row(s, sub)
                else:
                    sub.parent_id = None
                    sub.position = self._next_position(s, None)
                    sub.updated_at = utcnow()
                    s.add(sub)
                    s.flush()
            s.flush()
            self._delete_row(s, task)

    # --- sous-tâches ---

    def attach(self, child_id: int, parent_id: int) -> TaskOut:
        """Fait de ``child`` une sous-tâche de ``parent`` (Ctrl + glisser-déposer)."""
        with self.uow() as probe:
            child_out, parent_out = self._build(
                probe.session, [self._get(probe.session, child_id), self._get(probe.session, parent_id)]
            )
        reason = rules.attach_refusal_reason(child_out, parent_out)
        if reason:
            raise InvalidOperation(reason)
        with self.uow(label=f"Rattacher {quoted(child_out.title)} à {quoted(parent_out.title)}") as w:
            s = w.session
            child = self._get(s, child_id)
            parent = self._get(s, parent_id)
            child.parent_id = parent.id
            child.position = self._next_position(s, parent.id)
            child.updated_at = utcnow()
            s.add(child)
            if child.status == Status.IN_PROGRESS and parent.status == Status.NOT_STARTED:
                parent.status = str(Status.IN_PROGRESS)
                parent.updated_at = utcnow()
                s.add(parent)
            s.flush()
            return self._out(s, child)

    def detach(self, child_id: int) -> TaskOut:
        """Détache une sous-tâche de son parent : elle redevient une tâche indépendante."""
        with self.uow() as probe:
            child = self._get(probe.session, child_id)
            if child.parent_id is None:
                raise InvalidOperation("Cette tâche n'est pas une sous-tâche.")
            title = child.title
        with self.uow(label=f"Détacher {quoted(title)}") as w:
            s = w.session
            child = self._get(s, child_id)
            child.parent_id = None
            child.position = self._next_position(s, None)
            child.updated_at = utcnow()
            s.add(child)
            s.flush()
            return self._out(s, child)

    def reorder_subtasks(self, parent_id: int, ordered_ids: list[int]) -> list[TaskOut]:
        with self.uow() as probe:
            title = self._get(probe.session, parent_id).title
        with self.uow(label=f"Réordonner les sous-tâches de {quoted(title)}") as w:
            s = w.session
            subs = {t.id: t for t in s.exec(select(Task).where(Task.parent_id == parent_id)).all()}
            if set(ordered_ids) != subs.keys():
                raise InvalidOperation("La liste des sous-tâches ne correspond pas.")
            for position, task_id in enumerate(ordered_ids, start=1):
                subs[task_id].position = float(position)
                s.add(subs[task_id])
        return self.subtasks(parent_id)

    # --- duplication ---

    _COPIED_FIELDS = (
        "importance",
        "urgency",
        "due_date",
        "due_time",
        "kind",
        "reminder_offset_days",
        "reminder_manual_date",
        "notes",
        "project_id",
    )

    def _copy_row(self, s: Session, source: Task, *, title: str, parent_id: int | None) -> Task:
        """Copie une tâche (attributs, tags visibles, liens), remise à « Pas commencé »."""
        copy = Task(
            **{field: getattr(source, field) for field in self._COPIED_FIELDS},
            title=title,
            owner_id=self.actor.id,
            parent_id=parent_id,
            position=self._next_position(s, parent_id),
            status=str(Status.NOT_STARTED),
        )
        if copy.project_id is not None and copy.project_id not in self.projects.visible_ids(s):
            copy.project_id = None  # projet privé d'un autre utilisateur
        s.add(copy)
        s.flush()
        self._copy_tags(s, self, source.id, copy.id, all_tags=False)
        self._copy_links(s, self, source.id, copy.id)
        return copy

    def duplicate(self, task_id: int) -> TaskOut:
        """Duplique une tâche et ses sous-tâches (statut « Pas commencé », titre « … (copie) »)."""
        with self.uow() as probe:
            title = self._get(probe.session, task_id).title
        with self.uow(label=f"Dupliquer {quoted(title)}") as w:
            s = w.session
            source = self._get(s, task_id)
            copy = self._copy_row(s, source, title=f"{source.title} (copie)", parent_id=source.parent_id)
            subs = s.exec(select(Task).where(Task.parent_id == source.id).order_by(Task.position)).all()
            for sub in subs:
                self._copy_row(s, sub, title=sub.title, parent_id=copy.id)
            s.flush()
            return self._out(s, copy)

    # --- partage ---

    def set_shares(self, task_id: int, user_ids: list[int]) -> TaskOut:
        """Définit avec qui la tâche est partagée (réservé au propriétaire)."""
        with self.uow() as probe:
            title = self._get(probe.session, task_id).title
        with self.uow(label=f"Partager {quoted(title)}") as w:
            s = w.session
            task = self._get(s, task_id)
            if task.owner_id != self.actor.id:
                raise Forbidden("Seul le propriétaire peut partager cette tâche.")
            wanted = set(user_ids) - {task.owner_id}
            existing_users = set(s.exec(select(User.id).where(User.id.in_(wanted))).all())
            if wanted - existing_users:
                raise NotFound("Utilisateur introuvable.")
            current = {
                sh.user_id: sh for sh in s.exec(select(TaskShare).where(TaskShare.task_id == task_id)).all()
            }
            for user_id, share in current.items():
                if user_id not in wanted:
                    s.delete(share)
            for user_id in wanted - current.keys():
                s.add(TaskShare(task_id=task_id, user_id=user_id))
            self._touch(s, task)
            s.flush()
            return self._out(s, task)


# ======================================================================================================
# Utilitaires
# ======================================================================================================


def _haystack(task: TaskOut) -> str:
    parts = [task.title, task.notes, *(tag.name for tag in task.tags)]
    if task.project:
        parts.append(task.project.name)
    return rules.normalize_text(" ".join(parts))


def _update_label(title: str, fields: dict) -> str:
    name = quoted(title)
    keys = set(fields)
    if "due_date" in keys:
        keys.discard("due_time")  # changer l'échéance et son heure reste « changer l'échéance »
    if keys == {"status"}:
        return f"Statut de {name} → {Status(fields['status']).meta.text}"
    if keys == {"title"}:
        return f"Renommer {name}"
    if keys == {"notes"}:
        return f"Modifier les notes de {name}"
    if keys == {"due_date"}:
        return f"Changer l'échéance de {name}"
    if keys == {"importance"}:
        return f"Changer l'importance de {name}"
    if keys == {"urgency"}:
        return f"Changer l'urgence de {name}"
    if keys == {"importance", "urgency"}:
        return f"Déplacer {name} dans la matrice"
    return f"Modifier {name}"


def sort_tasks(tasks: list[TaskOut], sort: TaskSort) -> list[TaskOut]:
    """Trie les tâches ; l'ordre par défaut de chaque clé est le plus utile (échéance la plus proche,
    importance la plus haute, plus récente…) et ``descending`` l'inverse."""
    far = date.max

    def priority(t: TaskOut) -> int:
        return rules.priority_score(t.importance, t.urgency)

    keys = {
        "due": lambda t: (t.due_date is None, t.due_date or far, t.due_time or time.max, -priority(t)),
        "importance": lambda t: (-t.importance, -t.urgency, t.due_date or far),
        "urgency": lambda t: (-t.urgency, t.rank, -t.importance, t.due_date or far),
        "priority": lambda t: (-priority(t), -t.importance, t.due_date or far),
        "created": lambda t: (-t.created_at.timestamp(), t.id),
        "updated": lambda t: (-t.updated_at.timestamp(), t.id),
        "title": lambda t: (rules.normalize_text(t.title), t.id),
        "position": lambda t: (t.position, t.id),
    }
    key = keys.get(sort.key)
    if key is None:
        raise InvalidOperation(f"Tri inconnu : {sort.key}")
    return sorted(tasks, key=key, reverse=sort.descending)
