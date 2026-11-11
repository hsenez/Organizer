"""Socle commun des tâches et des événements : projet, tags, liens (et pièces jointes), lecture groupée.

Chaque sous-classe déclare ses tables (``model``, ``tag_model``, ``share_model``, ``link_model``), le nom de
la colonne qui les relie (``fk`` : ``task_id`` / ``event_id``) et sa visibilité (``_visible_clause``,
``_get``) ; ``_get_editable`` restreint à ce que l'utilisateur peut modifier (par défaut : tout ce qu'il
voit).

Règle commune : un tag **privé** d'un autre utilisateur est invisible sur un élément partagé et **préservé**
quand quelqu'un d'autre modifie les tags de cet élément.

**Compte désactivé** : ses éléments disparaissent pour tous (ils restent en base : une réactivation les fait
revenir), sauf pour ceux qui peuvent les modifier — ceux-là les gardent et peuvent aussi les supprimer.
Le « public » et les partages en lecture seule ne comptent plus.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from sqlalchemy import and_, func, or_
from sqlmodel import Session, SQLModel, select

from organizer.core.enums import LinkKind
from organizer.core.errors import InvalidOperation, NotFound
from organizer.core.models import Project, Tag, User, utcnow
from organizer.core.schemas import LinkIn, LinkOut, LinkPatch, ProjectOut, TagOut
from organizer.core.services.base import BaseService, ServiceContext, quoted
from organizer.core.services.labels import ProjectService, TagService


class ItemService(BaseService):
    model: type[SQLModel]
    tag_model: type[SQLModel]
    share_model: type[SQLModel]
    link_model: type[SQLModel]
    fk: str  # colonne des tables de liaison qui désigne l'élément
    not_found = "Élément introuvable."

    def __init__(self, ctx: ServiceContext, projects: ProjectService, tags: TagService):
        super().__init__(ctx)
        self.projects = projects
        self.tags = tags

    # --- comptes désactivés ---

    @staticmethod
    def _inactive_owners():
        """Sous-requête : identifiants des comptes désactivés."""
        return select(User.id).where(User.is_active.is_(False))

    def _shared_visible_clause(self):
        """Visibilité d'un élément à droits par partage (événements, notes) : à moi ; partagé avec moi en
        modification ; partagé (même en lecture) ou public, si son propriétaire est actif."""
        model, share = self.model, self.share_model
        me = self.actor.id
        fk = self._column(share)
        shared = select(fk).where(share.user_id == me)
        editable = select(fk).where(share.user_id == me, share.can_edit.is_(True))
        return or_(
            model.owner_id == me,
            model.id.in_(editable),
            and_(
                model.owner_id.not_in(self._inactive_owners()),
                or_(model.id.in_(shared), model.is_public.is_(True)),
            ),
        )

    # --- à fournir par les sous-classes ---

    def _get(self, s: Session, item_id: int) -> Any:
        raise NotImplementedError

    def _get_editable(self, s: Session, item_id: int) -> Any:
        return self._get(s, item_id)

    def _column(self, model: type[SQLModel]):
        return getattr(model, self.fk)

    # --- projet, tags ---

    def _check_project(self, s: Session, project_id: int | None) -> None:
        if project_id is not None and project_id not in self.projects.visible_ids(s):
            raise NotFound("Projet introuvable.")

    def _check_tags(self, s: Session, tag_ids: Iterable[int]) -> set[int]:
        wanted = set(tag_ids)
        unknown = wanted - self.tags.visible_ids(s)
        if unknown:
            raise NotFound("Tag introuvable.")
        return wanted

    def _set_tags(self, s: Session, item: Any, tag_ids: Iterable[int]) -> None:
        """Remplace les tags *visibles* de l'élément ; les tags privés d'autres utilisateurs sont
        conservés."""
        wanted = self._check_tags(s, tag_ids)
        visible = self.tags.visible_ids(s)
        column = self._column(self.tag_model)
        current = {
            link.tag_id: link for link in s.exec(select(self.tag_model).where(column == item.id)).all()
        }
        for tag_id, link in current.items():
            if tag_id in visible and tag_id not in wanted:
                s.delete(link)
        for tag_id in wanted - current.keys():
            s.add(self.tag_model(**{self.fk: item.id, "tag_id": tag_id}))

    # --- lecture groupée (construction des objets de sortie) ---

    def _visible_projects(self, s: Session) -> dict[int, Project]:
        return {p.id: p for p in s.exec(select(Project).where(self.projects._visible_clause())).all()}

    def _project_out(self, projects: dict[int, Project], project_id: int | None) -> ProjectOut | None:
        project = projects.get(project_id) if project_id is not None else None
        if project is None:
            return None
        return ProjectOut.model_validate(project).model_copy(
            update={"can_edit": self.projects.can_edit(project)}
        )

    def _tags_by_item(self, s: Session, ids: list[int]) -> dict[int, list[TagOut]]:
        visible = {t.id: t for t in s.exec(select(Tag).where(self.tags._visible_clause())).all()}
        result: dict[int, list[TagOut]] = defaultdict(list)
        column = self._column(self.tag_model)
        for link in s.exec(select(self.tag_model).where(column.in_(ids))).all():
            tag = visible.get(link.tag_id)
            if tag is not None:
                result[getattr(link, self.fk)].append(
                    TagOut.model_validate(tag).model_copy(update={"can_edit": self.tags.can_edit(tag)})
                )
        for tags in result.values():
            tags.sort(key=lambda tag: (tag.position, tag.name))
        return result

    def _links_by_item(self, s: Session, ids: list[int]) -> dict[int, list[LinkOut]]:
        result: dict[int, list[LinkOut]] = defaultdict(list)
        model = self.link_model
        for link in s.exec(
            select(model).where(self._column(model).in_(ids)).order_by(model.position, model.id)
        ).all():
            result[getattr(link, self.fk)].append(LinkOut.model_validate(link))
        return result

    def _shares_by_item(self, s: Session, ids: list[int]) -> dict[int, list[Any]]:
        result: dict[int, list[Any]] = defaultdict(list)
        for share in s.exec(select(self.share_model).where(self._column(self.share_model).in_(ids))).all():
            result[getattr(share, self.fk)].append(share)
        return result

    # --- liens ---

    def _touch(self, s: Session, item: Any) -> None:
        item.updated_at = utcnow()
        s.add(item)

    def _next_link_position(self, s: Session, item_id: int) -> float:
        model = self.link_model
        current = s.exec(select(func.max(model.position)).where(self._column(model) == item_id)).one()
        return (current or 0.0) + 1.0

    def _new_link(self, s: Session, item_id: int, kind: str, target: str, label: str) -> Any:
        link = self.link_model(
            **{self.fk: item_id},
            kind=kind,
            target=target,
            label=label,
            position=self._next_link_position(s, item_id),
        )
        s.add(link)
        return link

    def add_link(self, item_id: int, data: LinkIn) -> LinkOut:
        with self.uow() as probe:
            title = self._get(probe.session, item_id).title
        with self.uow(label=f"Ajouter un lien à {quoted(title)}") as w:
            s = w.session
            item = self._get_editable(s, item_id)
            if data.kind is LinkKind.ATTACHMENT:
                raise InvalidOperation("Une pièce jointe s'ajoute en envoyant le fichier.")
            link = self._new_link(s, item_id, str(data.kind), data.target.strip(), data.label.strip())
            self._touch(s, item)
            s.flush()
            return LinkOut.model_validate(link)

    def _get_link(self, s: Session, link_id: int, *, edit: bool = False) -> tuple[Any, Any]:
        link = s.get(self.link_model, link_id)
        if link is None:
            raise NotFound("Lien introuvable.")
        item_id = getattr(link, self.fk)
        return link, (self._get_editable(s, item_id) if edit else self._get(s, item_id))

    def update_link(self, link_id: int, patch: LinkPatch) -> LinkOut:
        with self.uow() as probe:
            _, item = self._get_link(probe.session, link_id)
            title = item.title
        with self.uow(label=f"Modifier un lien de {quoted(title)}") as w:
            s = w.session
            link, item = self._get_link(s, link_id, edit=True)
            for key, value in patch.model_dump(exclude_unset=True).items():
                if value is not None:
                    setattr(link, key, value.strip())
            s.add(link)
            self._touch(s, item)
            s.flush()
            return LinkOut.model_validate(link)

    def remove_link(self, link_id: int) -> None:
        with self.uow() as probe:
            _, item = self._get_link(probe.session, link_id)
            title = item.title
        with self.uow(label=f"Retirer un lien de {quoted(title)}") as w:
            s = w.session
            link, item = self._get_link(s, link_id, edit=True)
            s.delete(link)
            self._touch(s, item)

    # --- copie d'un élément à l'autre (duplication, conversion tâche ↔ événement) ---

    def _copy_links(self, s: Session, source: ItemService, source_id: int, target_id: int) -> None:
        model = source.link_model
        for link in s.exec(select(model).where(source._column(model) == source_id)).all():
            s.add(
                self.link_model(
                    **{self.fk: target_id},
                    kind=link.kind,
                    target=link.target,
                    label=link.label,
                    position=link.position,
                )
            )

    def _copy_tags(
        self, s: Session, source: ItemService, source_id: int, target_id: int, *, all_tags: bool
    ) -> None:
        """``all_tags`` : copie aussi les tags privés d'autres utilisateurs (conversion : c'est le même
        élément) ; sinon seulement les tags visibles (duplication)."""
        visible = self.tags.visible_ids(s)
        model = source.tag_model
        for link in s.exec(select(model).where(source._column(model) == source_id)).all():
            if all_tags or link.tag_id in visible:
                s.add(self.tag_model(**{self.fk: target_id, "tag_id": link.tag_id}))
