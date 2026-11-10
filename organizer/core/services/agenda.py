"""Événements du calendrier (« agenda ») : création, modification, partage, liens, conversion avec les tâches.

Droits :
- **voir** : le propriétaire, les utilisateurs avec qui l'événement est partagé, et tout le monde s'il est
  **public** ;
- **modifier** (champs, tags, liens, pièces jointes) **et supprimer** : le propriétaire, et les partages
  « modifiables » ; un événement public ou partagé en lecture seule ne se modifie ni ne se supprime ;
- **partager, rendre public, transformer en tâche** : le propriétaire seulement.

Les dates et heures sont locales ; :func:`rules.event_span` normalise début et fin (toute la journée sans
heure de début, une heure par défaut, fin après le début).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import or_
from sqlmodel import Session, select

from organizer.core import rules
from organizer.core.enums import EVENT_DEFAULT_COLOR
from organizer.core.errors import Forbidden, InvalidOperation, NotFound
from organizer.core.models import Event, EventLink, EventShare, EventTag, Task, TaskShare, User
from organizer.core.schemas import (
    EventCreate,
    EventFilter,
    EventOut,
    EventPatch,
    EventTimes,
    ShareSpec,
    TaskOut,
    TaskPatch,
)
from organizer.core.services.base import ServiceContext, quoted
from organizer.core.services.items import ItemService
from organizer.core.services.labels import ProjectService, TagService
from organizer.core.services.tasks import TaskService

_REQUIRED_FIELDS = {"title", "start_date", "end_date", "location", "notes", "is_public"}
_TIME_FIELDS = ("start_date", "start_time", "end_date", "end_time")


class AgendaService(ItemService):
    model = Event
    tag_model = EventTag
    share_model = EventShare
    link_model = EventLink
    fk = "event_id"
    not_found = "Événement introuvable."

    def __init__(self, ctx: ServiceContext, projects: ProjectService, tags: TagService, tasks: TaskService):
        super().__init__(ctx, projects, tags)
        self.tasks = tasks

    # ==================================================================================================
    # Visibilité et droits
    # ==================================================================================================

    def _visible_clause(self):
        me = self.actor.id
        shared = select(EventShare.event_id).where(EventShare.user_id == me)
        return or_(Event.owner_id == me, Event.id.in_(shared), Event.is_public.is_(True))

    def _get(self, s: Session, event_id: int) -> Event:
        event = s.exec(select(Event).where(Event.id == event_id, self._visible_clause())).first()
        if event is None:
            raise NotFound(self.not_found)
        return event

    def _can_edit(self, s: Session, event: Event) -> bool:
        if event.owner_id == self.actor.id:
            return True
        share = s.get(EventShare, (event.id, self.actor.id))
        return share is not None and share.can_edit

    def _get_editable(self, s: Session, event_id: int) -> Event:
        event = self._get(s, event_id)
        if not self._can_edit(s, event):
            raise Forbidden("Cet événement est en lecture seule pour vous.")
        return event

    def _get_owned(self, s: Session, event_id: int, action: str) -> Event:
        event = self._get(s, event_id)
        if event.owner_id != self.actor.id:
            raise Forbidden(f"Seul le propriétaire peut {action} cet événement.")
        return event

    # ==================================================================================================
    # Lecture
    # ==================================================================================================

    def _build(self, s: Session, events: list[Event]) -> list[EventOut]:
        if not events:
            return []
        ids = [e.id for e in events]
        me = self.actor.id
        projects = self._visible_projects(s)
        tags = self._tags_by_item(s, ids)
        links = self._links_by_item(s, ids)
        shares = self._shares_by_item(s, ids)
        outs = []
        for e in events:
            project = self._project_out(projects, e.project_id)
            mine = {share.user_id: share for share in shares[e.id]}
            can_edit = e.owner_id == me or (me in mine and mine[me].can_edit)
            outs.append(
                EventOut(
                    id=e.id,
                    owner_id=e.owner_id,
                    title=e.title,
                    notes=e.notes,
                    project=project,
                    tags=tags[e.id],
                    links=links[e.id],
                    shared_with=sorted(mine),
                    shares=[ShareSpec(user_id=u, can_edit=mine[u].can_edit) for u in sorted(mine)],
                    created_at=e.created_at,
                    updated_at=e.updated_at,
                    can_delete=can_edit,  # le propriétaire et les partages modifiables
                    start_date=e.start_date,
                    start_time=e.start_time,
                    end_date=e.end_date,
                    end_time=e.end_time,
                    all_day=e.start_time is None,
                    location=e.location,
                    color=e.color,
                    display_color=e.color or (project.color if project else EVENT_DEFAULT_COLOR),
                    is_public=e.is_public,
                    can_edit=can_edit,
                )
            )
        return outs

    def _out(self, s: Session, event: Event) -> EventOut:
        return self._build(s, [event])[0]

    def get(self, event_id: int) -> EventOut:
        with self.uow() as w:
            return self._out(w.session, self._get(w.session, event_id))

    def list(self, flt: EventFilter | None = None) -> list[EventOut]:
        """Événements visibles qui touchent la période du filtre, triés par début (journée entière en
        premier le jour même), puis titre."""
        flt = flt or EventFilter()
        me = self.actor.id
        with self.uow() as w:
            s = w.session
            query = select(Event).where(self._visible_clause())
            if flt.start is not None:
                query = query.where(Event.end_date >= flt.start)
            if flt.end is not None:
                query = query.where(Event.start_date <= flt.end)
            if flt.scope == "mine":
                query = query.where(Event.owner_id == me)
            elif flt.scope == "shared":
                query = query.where(Event.owner_id != me)
            if flt.project_ids:
                real = [p for p in flt.project_ids if p is not None]
                clauses = [Event.project_id.in_(real)] if real else []
                if None in flt.project_ids:
                    clauses.append(Event.project_id.is_(None))
                query = query.where(or_(*clauses))
            if flt.tag_ids:
                tagged = select(EventTag.event_id).where(EventTag.tag_id.in_(flt.tag_ids))
                query = query.where(Event.id.in_(tagged))
            outs = self._build(s, list(s.exec(query).all()))
        if flt.start is not None:
            # Un événement qui finit à minuit pile le jour de début de la période n'y figure pas.
            outs = [e for e in outs if _days(e)[-1] >= flt.start]
        if flt.text.strip():
            needles = rules.normalize_text(flt.text).split()
            outs = [e for e in outs if all(n in _haystack(e) for n in needles)]
        return sorted(
            outs, key=lambda e: (e.start_date, e.start_time is not None, e.start_time, e.title.lower())
        )

    # ==================================================================================================
    # Écriture
    # ==================================================================================================

    def create(self, data: EventCreate) -> EventOut:
        title = data.title.strip()
        if not title:
            raise InvalidOperation("Le titre est obligatoire.")
        span = rules.event_span(data.start_date, data.start_time, data.end_date, data.end_time)
        with self.uow(label=f"Créer l'événement {quoted(title)}") as w:
            s = w.session
            self._check_project(s, data.project_id)
            event = Event(
                owner_id=self.actor.id,
                title=title,
                notes=data.notes,
                project_id=data.project_id,
                location=data.location.strip(),
                color=data.color,
                is_public=data.is_public,
                **dict(zip(_TIME_FIELDS, span, strict=True)),
            )
            s.add(event)
            s.flush()
            if data.tag_ids:
                self._set_tags(s, event, data.tag_ids)
            s.flush()
            return self._out(s, event)

    def update(self, event_id: int, patch: EventPatch) -> EventOut:
        fields = {k: getattr(patch, k) for k in patch.model_fields_set}
        if not fields:
            return self.get(event_id)
        for key in _REQUIRED_FIELDS & fields.keys():
            if fields[key] is None:
                raise InvalidOperation(f"Le champ « {key} » ne peut pas être vide.")
        with self.uow() as probe:
            label = _update_label(self._get(probe.session, event_id).title, fields)
        group_key = f"event:{event_id}:{','.join(sorted(fields))}"
        with self.uow(label=label, group_key=group_key) as w:
            s = w.session
            event = self._get_editable(s, event_id)
            self._apply(s, event, fields)
            s.flush()
            return self._out(s, event)

    def _apply(self, s: Session, event: Event, fields: dict) -> None:
        """Applique des champs d'``EventPatch`` à ``event`` (sans enregistrer)."""
        if (
            "is_public" in fields
            and fields["is_public"] != event.is_public
            and event.owner_id != self.actor.id
        ):
            raise Forbidden("Seul le propriétaire peut rendre cet événement public ou privé.")
        if "title" in fields:
            title = fields["title"].strip()
            if not title:
                raise InvalidOperation("Le titre est obligatoire.")
            event.title = title
        if any(key in fields for key in _TIME_FIELDS):
            # Sans heure de début : toute la journée ; une journée entière qui prend une heure de début
            # (sans heure de fin) dure une heure.
            span = rules.event_span(*(fields.get(key, getattr(event, key)) for key in _TIME_FIELDS))
            for key, value in zip(_TIME_FIELDS, span, strict=True):
                setattr(event, key, value)
        for key in ("notes", "color", "is_public"):
            if key in fields:
                setattr(event, key, fields[key])
        if "location" in fields:
            event.location = fields["location"].strip()
        if "project_id" in fields:
            self._check_project(s, fields["project_id"])
            event.project_id = fields["project_id"]
        if "tag_ids" in fields:
            self._set_tags(s, event, fields["tag_ids"] or [])
        self._touch(s, event)

    def _delete_row(self, s: Session, event: Event) -> None:
        for model in (EventTag, EventShare, EventLink):
            for row in s.exec(select(model).where(model.event_id == event.id)).all():
                s.delete(row)
        s.flush()
        s.delete(event)

    def delete(self, event_id: int) -> None:
        with self.uow() as probe:
            title = self._get(probe.session, event_id).title
        with self.uow(label=f"Supprimer l'événement {quoted(title)}") as w:
            self._delete_row(w.session, self._get_editable(w.session, event_id))

    def set_shares(self, event_id: int, shares: list[ShareSpec]) -> EventOut:
        """Définit avec qui l'événement est partagé, et si chacun peut le modifier (réservé au
        propriétaire)."""
        with self.uow() as probe:
            title = self._get(probe.session, event_id).title
        with self.uow(label=f"Partager l'événement {quoted(title)}") as w:
            s = w.session
            event = self._get_owned(s, event_id, "partager")
            wanted = {share.user_id: share.can_edit for share in shares if share.user_id != event.owner_id}
            existing = set(s.exec(select(User.id).where(User.id.in_(wanted))).all())
            if wanted.keys() - existing:
                raise NotFound("Utilisateur introuvable.")
            current = {
                sh.user_id: sh for sh in s.exec(select(EventShare).where(EventShare.event_id == event_id))
            }
            for user_id, share in current.items():
                if user_id not in wanted:
                    s.delete(share)
                elif share.can_edit != wanted[user_id]:
                    share.can_edit = wanted[user_id]
                    s.add(share)
            for user_id in wanted.keys() - current.keys():
                s.add(EventShare(event_id=event_id, user_id=user_id, can_edit=wanted[user_id]))
            self._touch(s, event)
            s.flush()
            return self._out(s, event)

    # ==================================================================================================
    # Conversion tâche ↔ événement (un seul pas d'annulation)
    # ==================================================================================================

    def from_task(
        self, task_id: int, times: EventTimes | None = None, extra: EventPatch | None = None
    ) -> EventOut:
        """Transforme une tâche en événement : titre, notes, projet, tags, partages (modifiables) et liens
        sont repris ; sans ``times``, il commence à l'échéance (ou aujourd'hui à 9 h) et dure une heure.
        ``extra`` : champs appliqués dans la même action (ceux d'avant une conversion aller-retour)."""
        tasks = self.tasks
        with self.uow() as probe:
            title = tasks._get(probe.session, task_id).title
        with self.uow(label=f"Transformer {quoted(title)} en événement") as w:
            s = w.session
            task = tasks._get(s, task_id)
            if task.owner_id != self.actor.id:
                raise Forbidden("Seul le propriétaire peut transformer cette tâche en événement.")
            if task.parent_id is not None:
                raise InvalidOperation("Une sous-tâche ne peut pas devenir un événement.")
            if s.exec(select(Task.id).where(Task.parent_id == task.id)).first() is not None:
                raise InvalidOperation("Une tâche qui a des sous-tâches ne peut pas devenir un événement.")
            if times is None:
                span = rules.event_times_from_due(task.due_date, task.due_time, self.today())
            else:
                span = rules.event_span(times.start_date, times.start_time, times.end_date, times.end_time)
            event = Event(
                owner_id=task.owner_id,
                title=task.title,
                notes=task.notes,
                project_id=task.project_id,
                **dict(zip(_TIME_FIELDS, span, strict=True)),
            )
            s.add(event)
            s.flush()
            self._copy_tags(s, tasks, task.id, event.id, all_tags=True)
            self._copy_links(s, tasks, task.id, event.id)
            for share in s.exec(select(TaskShare).where(TaskShare.task_id == task.id)).all():
                s.add(EventShare(event_id=event.id, user_id=share.user_id, can_edit=True))
            s.flush()
            tasks._delete_row(s, task)
            if extra is not None and extra.model_fields_set:
                self._apply(s, event, {k: getattr(extra, k) for k in extra.model_fields_set})
            s.flush()
            return self._out(s, event)

    def to_task(self, event_id: int, extra: TaskPatch | None = None) -> TaskOut:
        """Transforme un événement en tâche (échéance = début) ; tags, partages et liens sont repris.
        ``extra`` : champs de la tâche appliqués dans la même action."""
        tasks = self.tasks
        with self.uow() as probe:
            title = self._get(probe.session, event_id).title
        with self.uow(label=f"Transformer l'événement {quoted(title)} en tâche") as w:
            s = w.session
            event = self._get_owned(s, event_id, "transformer")
            task = Task(
                owner_id=event.owner_id,
                title=event.title,
                notes=event.notes,
                project_id=event.project_id,
                due_date=event.start_date,
                due_time=event.start_time,
                position=tasks._next_position(s, None),
            )
            s.add(task)
            s.flush()
            tasks._copy_tags(s, self, event.id, task.id, all_tags=True)
            tasks._copy_links(s, self, event.id, task.id)
            for share in s.exec(select(EventShare).where(EventShare.event_id == event.id)).all():
                s.add(TaskShare(task_id=task.id, user_id=share.user_id))
            s.flush()
            self._delete_row(s, event)
            if extra is not None and extra.model_fields_set:
                tasks._apply(s, task, {k: getattr(extra, k) for k in extra.model_fields_set})
            s.flush()
            return tasks._out(s, task)


def _days(event: EventOut) -> list[date]:
    return rules.event_days(event.start_date, event.start_time, event.end_date, event.end_time)


def _haystack(event: EventOut) -> str:
    parts = [event.title, event.notes, event.location, *(tag.name for tag in event.tags)]
    if event.project:
        parts.append(event.project.name)
    return rules.normalize_text(" ".join(parts))


def _update_label(title: str, fields: dict) -> str:
    name = quoted(title)
    keys = set(fields)
    if keys <= set(_TIME_FIELDS):
        return f"Déplacer l'événement {name}"
    if keys == {"title"}:
        return f"Renommer l'événement {name}"
    if keys == {"notes"}:
        return f"Modifier les notes de {name}"
    return f"Modifier l'événement {name}"
