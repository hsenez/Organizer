"""Notifications : ce que d'autres ont fait qui me concerne.

**Qui est concerné** par une tâche, un événement ou une note : son propriétaire et les utilisateurs avec
qui il est partagé (pour une sous-tâche : aussi ceux de la tâche parente). L'auteur de l'action n'est
jamais prévenu.

:func:`record` est appelée dans la transaction de **chaque action enregistrée dans l'historique** (voir
``BaseService.uow``) : les lignes modifiées disent quels éléments sont touchés, le libellé de l'action
(« Changer l'échéance de « … » ») sert de texte. Pour chaque personne concernée, une notification :

- ``share`` : l'élément vient d'être partagé avec elle ;
- ``unshare`` : il ne l'est plus ;
- ``change`` : il a été modifié (ou converti tâche ↔ événement) ;
- ``delete`` : il a été supprimé ;
- ``conflict`` (créée par ``labels``) : un tag / projet public porte désormais le même nom que mon tag /
  projet privé (``item_type`` = ``tag`` / ``project``, ``item_id`` = le mien) ; utilisable tant que le
  conflit existe.

Les actions rapprochées identiques (enregistrement automatique des notes…) sont **regroupées** dans la
notification non lue précédente. Annuler / rétablir ne notifie pas.

**Réglages** du destinataire (réglages → 🔔 Notifications, préférence ``NOTIFICATIONS_PREF``) : un niveau
par type d'élément (``rules.wants_notification``), et les éléments qu'il a coupés (``ItemMute`` ; pour une
sous-tâche, couper la tâche parente suffit). Une notification non voulue n'est jamais créée. Les conflits
de nom (``conflict``) ne passent pas par là : ils sont toujours signalés.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import and_, func, or_, update
from sqlmodel import Session, select

from organizer.core import rules
from organizer.core.enums import NOTIFICATIONS_PREF
from organizer.core.errors import InvalidOperation, NotFound
from organizer.core.models import (
    Event,
    EventShare,
    ItemMute,
    Note,
    NoteShare,
    Notification,
    Project,
    Tag,
    Task,
    TaskShare,
    User,
    UserPref,
    utcnow,
)
from organizer.core.schemas import NotificationOut, NotificationSettings
from organizer.core.services.base import BaseService, quoted

MERGE_WINDOW = timedelta(minutes=15)
LIST_LIMIT = 200
# Tables liées à un élément : (type d'élément, colonne qui le désigne).
_ITEM_OF = {
    "task": ("task", "id"),
    "task_tag": ("task", "task_id"),
    "task_link": ("task", "task_id"),
    "task_share": ("task", "task_id"),
    "task_rank": ("task", "task_id"),
    "board_card": ("task", "task_id"),
    "event": ("event", "id"),
    "event_tag": ("event", "event_id"),
    "event_link": ("event", "event_id"),
    "event_share": ("event", "event_id"),
    "note": ("note", "id"),
    "note_tag": ("note", "note_id"),
    "note_share": ("note", "note_id"),
}
_MAIN = {
    "task": (Task, TaskShare, "task_id"),
    "event": (Event, EventShare, "event_id"),
    "note": (Note, NoteShare, "note_id"),
}
_KIND_ORDER = {"share": 0, "change": 1, "unshare": 2, "delete": 3}


@dataclass
class _Item:
    type: str
    id: int
    row: dict | None = None  # ligne principale connue par les modifications (après, sinon avant)
    deleted: bool = False
    added: set[int] = field(default_factory=set)  # partages ajoutés par cette action
    removed: set[int] = field(default_factory=set)  # partages retirés


def _items(changes) -> dict[tuple[str, int], _Item]:
    items: dict[tuple[str, int], _Item] = {}
    for change in changes:
        target = _ITEM_OF.get(change.table)
        if target is None:
            continue
        item_type, column = target
        row = change.after or change.before or {}
        item_id = row.get(column)
        if item_id is None:
            continue
        item = items.setdefault((item_type, int(item_id)), _Item(item_type, int(item_id)))
        if change.table == item_type:
            item.row = change.after or change.before
            item.deleted = change.after is None
        elif change.table.endswith("_share"):
            if change.before is None and change.after is not None:
                item.added.add(int(change.after["user_id"]))
            elif change.after is None and change.before is not None:
                item.removed.add(int(change.before["user_id"]))
    return items


@dataclass
class _Concerned:
    title: str = ""
    after: set[int] = field(default_factory=set)  # concernés après l'action
    before: set[int] = field(default_factory=set)  # concernés avant
    owners: set[int] = field(default_factory=set)  # propriétaire (et celui de la tâche parente)
    parent_id: int | None = None  # tâche parente d'une sous-tâche


def _concerned(s: Session, item: _Item) -> _Concerned:
    model, share_model, column = _MAIN[item.type]
    row = item.row
    if row is None:
        current = s.get(model, item.id)
        if current is None:
            return _Concerned()
        row = {
            "title": current.title,
            "owner_id": current.owner_id,
            "parent_id": getattr(current, "parent_id", None),
        }
    shares: set[int] = set()
    if not item.deleted:
        shares = set(s.exec(select(share_model.user_id).where(getattr(share_model, column) == item.id)).all())
    people = {int(row["owner_id"])}
    owners = set(people)
    parent_id = row.get("parent_id") if item.type == "task" else None
    if parent_id is not None:  # une sous-tâche concerne aussi ceux du parent
        parent = s.get(Task, int(parent_id))
        if parent is not None:
            people.add(parent.owner_id)
            owners.add(parent.owner_id)
            people |= set(s.exec(select(TaskShare.user_id).where(TaskShare.task_id == parent.id)).all())
    after = set() if item.deleted else people | shares
    before = people | (shares - item.added) | item.removed
    return _Concerned(
        row.get("title", ""), after, before, owners, int(parent_id) if parent_id is not None else None
    )


def settings_of(s: Session, user_id: int) -> NotificationSettings:
    """Réglages des notifications d'un utilisateur (préférence du compte, tolérante)."""
    row = s.get(UserPref, (user_id, NOTIFICATIONS_PREF))
    try:
        raw = json.loads(row.value) if row is not None else None
    except ValueError:
        raw = None
    return rules.notification_settings(raw)


def _muted(s: Session, user_id: int, item: _Item, parent_id: int | None) -> bool:
    targets = [and_(ItemMute.item_type == item.type, ItemMute.item_id == item.id)]
    if parent_id is not None:
        targets.append(and_(ItemMute.item_type == "task", ItemMute.item_id == parent_id))
    return s.exec(select(ItemMute).where(ItemMute.user_id == user_id, or_(*targets))).first() is not None


def _wanted(s: Session, user_id: int, kind: str, item: _Item, who: _Concerned) -> bool:
    level = settings_of(s, user_id).of(item.type).level
    if not rules.wants_notification(level, kind, is_owner=user_id in who.owners):
        return False
    return not _muted(s, user_id, item, who.parent_id)


def forget_mutes(s: Session, item_type: str, item_id: int) -> None:
    """À appeler en supprimant un élément : ses « ne plus me notifier » disparaissent avec lui."""
    for row in s.exec(
        select(ItemMute).where(ItemMute.item_type == item_type, ItemMute.item_id == item_id)
    ).all():
        s.delete(row)


def record(s: Session, actor_id: int, label: str, changes) -> None:
    """Crée (ou regroupe) les notifications d'une action de ``actor_id`` (voir le module)."""
    found: dict[int, tuple[str, _Item, _Concerned]] = {}  # destinataire → (type, élément, concernés)
    items = _items(changes)
    conversion = any(i.deleted for i in items.values()) and any(
        i.row is not None and not i.deleted for i in items.values()
    )
    for item in items.values():
        who = _concerned(s, item)
        before = who.before
        for user_id in (who.after | before) - {actor_id}:
            if item.deleted:
                kind = "delete"
            elif user_id in item.added and user_id not in before and not conversion:
                kind = "share"  # (une conversion tâche ↔ événement ne partage rien de nouveau)
            elif user_id in item.removed:
                kind = "unshare"
            else:
                kind = "change"
            previous = found.get(user_id)
            # Une conversion supprime l'un et crée l'autre : on retient l'élément qui existe toujours.
            if previous is None or _KIND_ORDER[kind] < _KIND_ORDER[previous[0]]:
                found[user_id] = (kind, item, who)
    if not found:
        return
    now = utcnow()
    for user_id, (kind, item, who) in found.items():
        if not _wanted(s, user_id, kind, item, who):
            continue
        title = who.title
        last = s.exec(
            select(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.actor_id == actor_id,
                Notification.item_type == item.type,
                Notification.item_id == item.id,
                Notification.kind == kind,
                Notification.text == label,
                Notification.read_at.is_(None),
            )
            .order_by(Notification.id.desc())
            .limit(1)
        ).first()
        if last is not None and now - _aware(last.updated_at) <= MERGE_WINDOW:
            last.updated_at = now
            last.title = title or last.title
            s.add(last)
            continue
        s.add(
            Notification(
                user_id=user_id,
                actor_id=actor_id,
                kind=kind,
                item_type=item.type,
                item_id=item.id,
                title=title,
                text=label,
                created_at=now,
                updated_at=now,
            )
        )


def _aware(moment):
    """SQLite rend les dates sans fuseau : elles sont en UTC."""
    from datetime import UTC

    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


class NotificationService(BaseService):
    """Les notifications de l'utilisateur courant."""

    def list(self, limit: int = LIST_LIMIT, after: int | None = None) -> list[NotificationOut]:
        """Les plus récentes d'abord (dernière action regroupée). ``after`` : seulement les **non lues** de
        numéro supérieur (nouvelles depuis la dernière fois : pop-ups du client bureau), plus récentes
        d'abord."""
        me = self.actor.id
        with self.uow() as w:
            s = w.session
            query = select(Notification).where(Notification.user_id == me)
            if after is None:
                query = query.order_by(Notification.updated_at.desc(), Notification.id.desc())
            else:
                query = query.where(Notification.id > after, Notification.read_at.is_(None))
                query = query.order_by(Notification.id.desc())
            rows = s.exec(query.limit(limit)).all()
            names = {u.id: u.display_name or u.username for u in s.exec(select(User)).all()}
            return [
                NotificationOut(
                    id=n.id,
                    actor_id=n.actor_id,
                    actor_name=names.get(n.actor_id, "?"),
                    kind=n.kind,
                    item_type=n.item_type,
                    item_id=n.item_id,
                    title=n.title,
                    text=n.text,
                    created_at=n.created_at,
                    updated_at=n.updated_at,
                    read=n.read_at is not None,
                    available=self._available(s, n),
                )
                for n in rows
            ]

    def _available(self, s: Session, n: Notification) -> bool:
        if n.kind == "delete":
            return False
        if n.kind == "conflict":
            return self.conflicting_public(s, n.item_type, n.item_id) is not None
        return self._visible(s, n.item_type, n.item_id)

    def conflicting_public(self, s: Session, item_type: str, item_id: int):
        """Le tag / projet public qui porte le même nom que mon tag / projet privé ``item_id`` (None : plus de
        conflit — renommé, fusionné, supprimé, ou le public a changé)."""
        model = {"tag": Tag, "project": Project}.get(item_type)
        mine = s.get(model, item_id) if model is not None else None
        if mine is None or mine.owner_id != self.actor.id or mine.is_public:
            return None
        return s.exec(
            select(model).where(model.is_public.is_(True), func.lower(model.name) == mine.name.lower())
        ).first()

    def conflict_target(self, item_type: str, item_id: int) -> int | None:
        """Identifiant du public en conflit avec mon tag / projet privé (pour le fusionner), ou None."""
        with self.uow() as w:
            public = self.conflicting_public(w.session, item_type, item_id)
            return public.id if public is not None else None

    def _visible(self, s: Session, item_type: str, item_id: int) -> bool:
        """L'élément existe-t-il encore, et le voit-on (pour l'ouvrir d'un clic) ?"""
        if item_type not in _MAIN:
            return False
        model, share_model, column = _MAIN[item_type]
        row = s.get(model, item_id)
        if row is None:
            return False
        if row.owner_id == self.actor.id:
            return True
        owner = s.get(User, row.owner_id)
        active = owner is not None and owner.is_active
        if active and getattr(row, "is_public", False):
            return True
        shared = s.exec(
            select(share_model).where(
                getattr(share_model, column) == item_id, share_model.user_id == self.actor.id
            )
        ).first()
        # Propriétaire désactivé : seuls ceux qui peuvent modifier l'élément le voient encore.
        if shared is not None and (active or getattr(shared, "can_edit", True)):
            return True
        parent_id = getattr(row, "parent_id", None)
        return parent_id is not None and self._visible(s, "task", parent_id)

    # --- « ne plus me notifier » pour un élément ---

    def _check_item(self, s: Session, item_type: str, item_id: int) -> str:
        """Titre de l'élément (erreur s'il n'existe pas ou n'est pas visible)."""
        if item_type not in _MAIN:
            raise InvalidOperation(f"Type d'élément inconnu : {item_type}")
        if not self._visible(s, item_type, item_id):
            raise NotFound("Élément introuvable.")
        return s.get(_MAIN[item_type][0], item_id).title

    def muted(self, item_type: str, item_id: int) -> bool:
        """L'utilisateur a-t-il coupé les notifications de cet élément ?"""
        with self.uow() as w:
            self._check_item(w.session, item_type, item_id)
            return w.session.get(ItemMute, (self.actor.id, item_type, item_id)) is not None

    def set_muted(self, item_type: str, item_id: int, muted: bool) -> bool:
        """Coupe (``muted``) ou rétablit les notifications d'un élément pour soi ; renvoie le nouvel état.
        Annulable (Ctrl+Z), comme une épingle."""
        with self.uow() as probe:
            title = self._check_item(probe.session, item_type, item_id)
            current = probe.session.get(ItemMute, (self.actor.id, item_type, item_id)) is not None
        if current == muted:
            return muted
        verb = "Couper" if muted else "Rétablir"
        with self.uow(label=f"{verb} les notifications de {quoted(title)}") as w:
            s = w.session
            row = s.get(ItemMute, (self.actor.id, item_type, item_id))
            if muted and row is None:
                s.add(ItemMute(user_id=self.actor.id, item_type=item_type, item_id=item_id))
            elif not muted and row is not None:
                s.delete(row)
        return muted

    def unread_count(self) -> int:
        with self.uow() as w:
            return int(
                w.session.exec(
                    select(func.count())
                    .select_from(Notification)
                    .where(Notification.user_id == self.actor.id, Notification.read_at.is_(None))
                ).one()
            )

    def mark_read(self, ids: list[int] | None = None) -> int:
        """Marque comme lues les notifications ``ids`` (toutes si None) ; renvoie le nombre de non lues."""
        me = self.actor.id
        with self.uow() as w:
            s = w.session
            query = update(Notification).where(Notification.user_id == me, Notification.read_at.is_(None))
            if ids is not None:
                if not ids:
                    return self._count(s)
                query = query.where(Notification.id.in_(ids))
            s.exec(query.values(read_at=utcnow()))
            return self._count(s)

    def _count(self, s: Session) -> int:
        return int(
            s.exec(
                select(func.count())
                .select_from(Notification)
                .where(Notification.user_id == self.actor.id, Notification.read_at.is_(None))
            ).one()
        )
