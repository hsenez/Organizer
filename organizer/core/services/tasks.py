"""Tâches : création, modification, sous-tâches, liens, partage, filtres et tri.

Visibilité : une tâche est visible (et modifiable) par son propriétaire, par les utilisateurs avec qui elle
est partagée, et par tous ceux qui voient son parent (les sous-tâches suivent leur parent). La suppression
est réservée au propriétaire de la tâche ou de son parent.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, time

from sqlalchemy import func, or_
from sqlalchemy.orm import aliased
from sqlmodel import Session, select

from organizer.core import rules
from organizer.core.enums import Status, TaskKind
from organizer.core.errors import Forbidden, InvalidOperation, NotFound
from organizer.core.models import Project, Tag, Task, TaskLink, TaskShare, TaskTag, User, utcnow
from organizer.core.schemas import (
    LinkIn,
    LinkOut,
    LinkPatch,
    ProjectOut,
    TagOut,
    TaskCreate,
    TaskFilter,
    TaskOut,
    TaskPatch,
    TaskSort,
)
from organizer.core.services.base import BaseService, ServiceContext, quoted
from organizer.core.services.labels import ProjectService, TagService

_REQUIRED_FIELDS = {"title", "importance", "urgency", "status", "kind", "notes"}


class TaskService(BaseService):
    def __init__(self, ctx: ServiceContext, projects: ProjectService, tags: TagService):
        super().__init__(ctx)
        self.projects = projects
        self.tags = tags

    # ==================================================================================================
    # Visibilité
    # ==================================================================================================

    def _visible_clause(self):
        me = self.actor.id
        shared_ids = select(TaskShare.task_id).where(TaskShare.user_id == me)
        parent = aliased(Task)
        visible_parents = select(parent.id).where(or_(parent.owner_id == me, parent.id.in_(shared_ids)))
        return or_(Task.owner_id == me, Task.id.in_(shared_ids), Task.parent_id.in_(visible_parents))

    def _get(self, s: Session, task_id: int) -> Task:
        task = s.exec(select(Task).where(Task.id == task_id, self._visible_clause())).first()
        if task is None:
            raise NotFound("Tâche introuvable.")
        return task

    def _can_delete(self, s: Session, task: Task) -> bool:
        if task.owner_id == self.actor.id:
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

        visible_projects = {
            p.id: p for p in s.exec(select(Project).where(self.projects._visible_clause())).all()
        }
        visible_tags = {t.id: t for t in s.exec(select(Tag).where(self.tags._visible_clause())).all()}

        tags_by_task: dict[int, list[TagOut]] = defaultdict(list)
        for link in s.exec(select(TaskTag).where(TaskTag.task_id.in_(ids))).all():
            tag = visible_tags.get(link.tag_id)
            if tag is not None:
                tags_by_task[link.task_id].append(
                    TagOut.model_validate(tag).model_copy(update={"can_edit": self.tags.can_edit(tag)})
                )

        links_by_task: dict[int, list[LinkOut]] = defaultdict(list)
        for link in s.exec(
            select(TaskLink).where(TaskLink.task_id.in_(ids)).order_by(TaskLink.position, TaskLink.id)
        ).all():
            links_by_task[link.task_id].append(LinkOut.model_validate(link))

        shares_by_task: dict[int, list[int]] = defaultdict(list)
        for share in s.exec(select(TaskShare).where(TaskShare.task_id.in_(ids))).all():
            shares_by_task[share.task_id].append(share.user_id)

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
            project = visible_projects.get(t.project_id) if t.project_id is not None else None
            outs.append(
                TaskOut(
                    id=t.id,
                    owner_id=t.owner_id,
                    parent_id=t.parent_id,
                    parent_title=parent.title if parent else None,
                    position=t.position,
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
                    project=(
                        ProjectOut.model_validate(project).model_copy(
                            update={"can_edit": self.projects.can_edit(project)}
                        )
                        if project
                        else None
                    ),
                    tags=sorted(tags_by_task[t.id], key=lambda tag: (tag.position, tag.name)),
                    links=links_by_task[t.id],
                    shared_with=sorted(shares_by_task[t.id]),
                    subtask_count=sub_count[t.id],
                    subtask_total=sub_total[t.id],
                    subtask_done=sub_done[t.id],
                    due_after_parent=bool(
                        parent and t.due_date and parent.due_date and t.due_date > parent.due_date
                    ),
                    created_at=t.created_at,
                    updated_at=t.updated_at,
                    completed_at=t.completed_at,
                    can_delete=t.owner_id == me or bool(parent and parent.owner_id == me),
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

    def _check_project(self, s: Session, project_id: int | None) -> None:
        if project_id is not None and project_id not in self.projects.visible_ids(s):
            raise NotFound("Projet introuvable.")

    def _check_tags(self, s: Session, tag_ids: Iterable[int]) -> set[int]:
        wanted = set(tag_ids)
        unknown = wanted - self.tags.visible_ids(s)
        if unknown:
            raise NotFound("Tag introuvable.")
        return wanted

    def _set_tags(self, s: Session, task: Task, tag_ids: Iterable[int]) -> None:
        """Remplace les tags *visibles* de la tâche ; les tags privés d'autres utilisateurs sont conservés."""
        wanted = self._check_tags(s, tag_ids)
        visible = self.tags.visible_ids(s)
        current = {
            link.tag_id: link for link in s.exec(select(TaskTag).where(TaskTag.task_id == task.id)).all()
        }
        for tag_id, link in current.items():
            if tag_id in visible and tag_id not in wanted:
                s.delete(link)
        for tag_id in wanted - current.keys():
            s.add(TaskTag(task_id=task.id, tag_id=tag_id))

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
            task.reminder_offset_days = self.actor.reminder_offset_days

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
            s.add(task)
            s.flush()
            return self._out(s, task)

    def _delete_row(self, s: Session, task: Task) -> None:
        for model in (TaskTag, TaskShare, TaskLink):
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

    # --- liens ---

    def _touch(self, s: Session, task: Task) -> None:
        task.updated_at = utcnow()
        s.add(task)

    def add_link(self, task_id: int, data: LinkIn) -> LinkOut:
        with self.uow() as probe:
            title = self._get(probe.session, task_id).title
        with self.uow(label=f"Ajouter un lien à {quoted(title)}") as w:
            s = w.session
            task = self._get(s, task_id)
            current = s.exec(select(func.max(TaskLink.position)).where(TaskLink.task_id == task_id)).one()
            link = TaskLink(
                task_id=task_id,
                kind=str(data.kind),
                target=data.target.strip(),
                label=data.label.strip(),
                position=(current or 0.0) + 1.0,
            )
            s.add(link)
            self._touch(s, task)
            s.flush()
            return LinkOut.model_validate(link)

    def _get_link(self, s: Session, link_id: int) -> tuple[TaskLink, Task]:
        link = s.get(TaskLink, link_id)
        if link is None:
            raise NotFound("Lien introuvable.")
        return link, self._get(s, link.task_id)

    def update_link(self, link_id: int, patch: LinkPatch) -> LinkOut:
        with self.uow() as probe:
            _, task = self._get_link(probe.session, link_id)
            title = task.title
        with self.uow(label=f"Modifier un lien de {quoted(title)}") as w:
            s = w.session
            link, task = self._get_link(s, link_id)
            for key, value in patch.model_dump(exclude_unset=True).items():
                if value is not None:
                    setattr(link, key, value.strip())
            s.add(link)
            self._touch(s, task)
            s.flush()
            return LinkOut.model_validate(link)

    def remove_link(self, link_id: int) -> None:
        with self.uow() as probe:
            _, task = self._get_link(probe.session, link_id)
            title = task.title
        with self.uow(label=f"Retirer un lien de {quoted(title)}") as w:
            s = w.session
            link, task = self._get_link(s, link_id)
            s.delete(link)
            self._touch(s, task)

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
        "urgency": lambda t: (-t.urgency, -t.importance, t.due_date or far),
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
