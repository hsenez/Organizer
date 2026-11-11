"""Projets / sujets et tags : listes éditables, publiques ou privées.

- Public : visible et utilisable par tous ; modifiable par son créateur et les admins.
- Privé : visible, utilisable et modifiable uniquement par son créateur.

Noms : uniques (sans la casse) parmi ce que l'utilisateur voit. Un privé d'un autre utilisateur est
invisible : quand un élément devient public (création, passage en public, renommage), un autre utilisateur
peut donc déjà avoir un privé du même nom. C'est permis, mais son propriétaire reçoit une notification
« conflict » qui lui propose de renommer le sien ou de le fusionner dans le public. Deux publics du même nom
sont refusés.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_
from sqlmodel import Session, select

from organizer.core import rules
from organizer.core.errors import Forbidden, InvalidOperation, NotFound
from organizer.core.models import Event, EventTag, Note, NoteTag, Notification, Project, Tag, Task, TaskTag
from organizer.core.schemas import ProjectIn, ProjectOut, ProjectPatch, TagIn, TagOut, TagPatch
from organizer.core.services.base import BaseService, quoted


class _LabelService(BaseService):
    model: Any = None
    noun: str = ""  # « le projet », « le tag »
    kind: str = ""  # « project », « tag » (type d'élément des notifications)

    # --- visibilité / droits ---

    def _visible_clause(self):
        m = self.model
        return or_(m.is_public == True, m.owner_id == self.actor.id)  # noqa: E712

    def can_edit(self, obj: Any) -> bool:
        return obj.owner_id == self.actor.id or (obj.is_public and self.actor.is_admin)

    def _get_visible(self, s: Session, obj_id: int) -> Any:
        obj = s.get(self.model, obj_id)
        if obj is None or not (obj.is_public or obj.owner_id == self.actor.id):
            raise NotFound(f"{self.noun.capitalize()} est introuvable.")
        return obj

    def _get_editable(self, s: Session, obj_id: int) -> Any:
        obj = self._get_visible(s, obj_id)
        if not self.can_edit(obj):
            raise Forbidden(f"Vous ne pouvez pas modifier {self.noun} {quoted(obj.name)}.")
        return obj

    def visible_ids(self, s: Session) -> set[int]:
        return set(s.exec(select(self.model.id).where(self._visible_clause())).all())

    def _check_unique(self, s: Session, name: str, exclude_id: int | None = None) -> None:
        """Les noms sont uniques (sans tenir compte de la casse) parmi ce que l'utilisateur voit."""
        m = self.model
        query = select(m).where(self._visible_clause(), func.lower(m.name) == name.strip().lower())
        if exclude_id is not None:
            query = query.where(m.id != exclude_id)
        if s.exec(query).first() is not None:
            raise InvalidOperation(f"{self.noun.capitalize()} {quoted(name)} existe déjà.")

    def _check_public_name(self, s: Session, obj: Any) -> None:
        """``obj`` est (ou devient) public sous ce nom : refuse un autre public du même nom ; prévient les
        propriétaires d'un privé du même nom (notification « conflict », une seule tant qu'elle n'est pas
        lue)."""
        m = self.model
        same = s.exec(select(m).where(func.lower(m.name) == obj.name.lower(), m.id != obj.id)).all()
        if any(other.is_public for other in same):
            raise InvalidOperation(
                f"{self.noun.capitalize()} public {quoted(obj.name)} existe déjà : fusionnez plutôt les deux."
            )
        for other in same:
            if other.owner_id == self.actor.id:
                continue
            pending = s.exec(
                select(Notification.id).where(
                    Notification.user_id == other.owner_id,
                    Notification.kind == "conflict",
                    Notification.item_type == self.kind,
                    Notification.item_id == other.id,
                    Notification.read_at.is_(None),
                )
            ).first()
            if pending is None:
                s.add(
                    Notification(
                        user_id=other.owner_id,
                        actor_id=self.actor.id,
                        kind="conflict",
                        item_type=self.kind,
                        item_id=other.id,
                        title=other.name,
                        text=f"Même nom que {self.noun} public {quoted(obj.name)}",
                    )
                )

    def _next_position(self, s: Session) -> float:
        current = s.exec(select(func.max(self.model.position))).one()
        return (current or 0.0) + 1.0

    def _out(self, obj: Any) -> Any:
        raise NotImplementedError

    # --- lecture ---

    def get(self, obj_id: int) -> Any:
        with self.uow() as w:
            return self._out(self._get_visible(w.session, obj_id))

    def _list(self, extra_where: tuple = ()) -> list[Any]:
        with self.uow() as w:
            rows = w.session.exec(
                select(self.model)
                .where(self._visible_clause(), *extra_where)
                .order_by(self.model.position, self.model.name)
            ).all()
            return [self._out(o) for o in rows]

    # --- écriture ---

    def _create(self, data: Any) -> Any:
        name = data.name.strip()
        with self.uow(label=f"Créer {self.noun} {quoted(name)}") as w:
            self._check_unique(w.session, name)
            obj = self.model(
                **data.model_dump(exclude={"name", "avoid_colors"}),
                name=name,
                owner_id=self.actor.id,
                position=self._next_position(w.session),
            )
            w.session.add(obj)
            w.session.flush()
            if obj.is_public:
                self._check_public_name(w.session, obj)
            return self._out(obj)

    def update(self, obj_id: int, patch: Any) -> Any:
        fields = patch.model_dump(exclude_unset=True)
        with self.uow() as probe:
            name = self._get_visible(probe.session, obj_id).name
        with self.uow(label=f"Modifier {self.noun} {quoted(name)}") as w:
            obj = self._get_editable(w.session, obj_id)
            was_public, old_name = obj.is_public, obj.name
            if "name" in fields:
                fields["name"] = fields["name"].strip()
                self._check_unique(w.session, fields["name"], exclude_id=obj.id)
            for key, value in fields.items():
                setattr(obj, key, value)
            w.session.add(obj)
            w.session.flush()
            if obj.is_public and (not was_public or obj.name.lower() != old_name.lower()):
                self._check_public_name(w.session, obj)
            return self._out(obj)

    plural: str = ""

    def reorder(self, ordered_ids: list[int]) -> None:
        """Range les éléments dans l'ordre donné (ceux que l'on ne peut pas modifier sont ignorés)."""
        with self.uow(label=f"Réordonner les {self.plural}") as w:
            for position, obj_id in enumerate(ordered_ids):
                obj = w.session.get(self.model, obj_id)
                if obj is not None and self.can_edit(obj):
                    obj.position = float(position)
                    w.session.add(obj)


class ProjectService(_LabelService):
    model = Project
    noun = "le projet"
    plural = "projets"
    kind = "project"

    def _out(self, obj: Project) -> ProjectOut:
        return ProjectOut.model_validate(obj).model_copy(update={"can_edit": self.can_edit(obj)})

    def list(self, include_archived: bool = False) -> list[ProjectOut]:
        return self._list(() if include_archived else (Project.archived == False,))  # noqa: E712

    def create(self, data: ProjectIn) -> ProjectOut:
        return self._create(data)

    def update(self, obj_id: int, patch: ProjectPatch) -> ProjectOut:
        return super().update(obj_id, patch)

    def delete(self, project_id: int) -> None:
        """Supprime le projet ; les tâches, événements et notes qui l'utilisaient n'ont plus de projet."""
        with self.uow() as probe:
            name = self._get_visible(probe.session, project_id).name
        with self.uow(label=f"Supprimer le projet {quoted(name)}") as w:
            project = self._get_editable(w.session, project_id)
            for model in (Task, Event, Note):
                for item in w.session.exec(select(model).where(model.project_id == project_id)).all():
                    item.project_id = None
                    w.session.add(item)
            w.session.flush()
            w.session.delete(project)

    def merge(self, source_id: int, target_id: int) -> ProjectOut:
        """Fusionne le projet ``source`` dans ``target`` : ses tâches et ses événements passent à ``target``,
        puis ``source`` est supprimé."""
        if source_id == target_id:
            raise InvalidOperation("Impossible de fusionner un projet avec lui-même.")
        with self.uow() as probe:
            source_name = self._get_visible(probe.session, source_id).name
            target_name = self._get_visible(probe.session, target_id).name
        with self.uow(label=f"Fusionner le projet {quoted(source_name)} dans {quoted(target_name)}") as w:
            s = w.session
            source = self._get_editable(s, source_id)
            target = self._get_visible(s, target_id)
            for model in (Task, Event, Note):
                for item in s.exec(select(model).where(model.project_id == source_id)).all():
                    item.project_id = target_id
                    s.add(item)
            s.flush()
            s.delete(source)
            s.flush()
            return self._out(target)


class TagService(_LabelService):
    model = Tag
    noun = "le tag"
    plural = "tags"
    kind = "tag"

    def _out(self, obj: Tag) -> TagOut:
        return TagOut.model_validate(obj).model_copy(update={"can_edit": self.can_edit(obj)})

    def list(self) -> list[TagOut]:
        return self._list()

    def create(self, data: TagIn) -> TagOut:
        if data.color is None:
            data = data.model_copy(update={"color": self.suggest_color(data.avoid_colors)})
        return self._create(data)

    def suggest_color(self, avoid: list[str] | None = None) -> str:
        """Couleur bien distincte des tags visibles, et surtout de ``avoid`` (tags de la tâche éditée)."""
        with self.uow() as w:
            taken = w.session.exec(select(Tag.color).where(self._visible_clause())).all()
        return rules.pick_distinct_color(taken, avoid or [])

    def update(self, obj_id: int, patch: TagPatch) -> TagOut:
        return super().update(obj_id, patch)

    def delete(self, tag_id: int) -> None:
        with self.uow() as probe:
            name = self._get_visible(probe.session, tag_id).name
        with self.uow(label=f"Supprimer le tag {quoted(name)}") as w:
            tag = self._get_editable(w.session, tag_id)
            for model in (TaskTag, EventTag, NoteTag):
                for link in w.session.exec(select(model).where(model.tag_id == tag_id)).all():
                    w.session.delete(link)
            w.session.flush()
            w.session.delete(tag)

    def merge(self, source_id: int, target_id: int) -> TagOut:
        """Fusionne le tag ``source`` dans ``target`` : les tâches de l'un passent à l'autre, puis
        ``source`` est supprimé."""
        if source_id == target_id:
            raise InvalidOperation("Impossible de fusionner un tag avec lui-même.")
        with self.uow() as probe:
            source_name = self._get_visible(probe.session, source_id).name
            target_name = self._get_visible(probe.session, target_id).name
        with self.uow(label=f"Fusionner le tag {quoted(source_name)} dans {quoted(target_name)}") as w:
            s = w.session
            source = self._get_editable(s, source_id)
            target = self._get_visible(s, target_id)
            for model, fk in ((TaskTag, "task_id"), (EventTag, "event_id"), (NoteTag, "note_id")):
                column = getattr(model, fk)
                already = set(s.exec(select(column).where(model.tag_id == target_id)).all())
                for link in s.exec(select(model).where(model.tag_id == source_id)).all():
                    item_id = getattr(link, fk)
                    if item_id not in already:
                        s.add(model(**{fk: item_id, "tag_id": target_id}))
                        already.add(item_id)
                    s.delete(link)
            s.flush()
            s.delete(source)
            s.flush()
            return self._out(target)
