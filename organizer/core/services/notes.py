"""Notes (module 📝 Notes) : création, modification, partage, épingles, liens internes et liens retour.

Droits (comme les événements) :
- **voir** : le propriétaire, les utilisateurs avec qui la note est partagée, et tout le monde si elle est
  **publique** ;
- **modifier et supprimer** : le propriétaire et les partages « modifiables » ; une note publique ou
  partagée en lecture seule ne se modifie ni ne se supprime ;
- **partager, rendre publique** : le propriétaire seulement.

**Épingler** est personnel : chacun épingle les notes qu'il voit (table ``note_pin``), sans rien changer
pour les autres.

**Liens internes** : ``[texte](task:12)``, ``[texte](event:8)``, ``[texte](note:5)`` dans le texte d'une
note (ou les notes d'une tâche / d'un événement). :meth:`NoteService.resolve` dit ce que désigne chaque lien
pour l'utilisateur courant (titre actuel, ou inaccessible) ; :meth:`NoteService.backlinks` trouve les notes,
tâches et événements visibles qui pointent vers un élément.
"""

from __future__ import annotations

from sqlalchemy import or_
from sqlmodel import Session, select

from organizer.core import rules
from organizer.core.enums import NOTE_DEFAULT_EMOJI, REF_EMOJI
from organizer.core.errors import Forbidden, InvalidOperation, NotFound
from organizer.core.models import Event, Note, NotePin, NoteShare, NoteTag, Task, User
from organizer.core.schemas import NoteCreate, NoteFilter, NoteOut, NotePatch, RefOut, ShareSpec
from organizer.core.services.base import ServiceContext, quoted
from organizer.core.services.items import ItemService
from organizer.core.services.labels import ProjectService, TagService
from organizer.core.services.notifications import forget_mutes

_REQUIRED_FIELDS = {"title", "notes", "emoji", "is_public"}
BACKLINKS_LIMIT = 100
_KIND_ORDER = {"note": 0, "task": 1, "event": 2}


class NoteService(ItemService):
    model = Note
    tag_model = NoteTag
    share_model = NoteShare
    link_model = None  # pas de liste de liens : ils sont dans le texte
    fk = "note_id"
    not_found = "Note introuvable."

    def __init__(self, ctx: ServiceContext, projects: ProjectService, tags: TagService, tasks, agenda):
        super().__init__(ctx, projects, tags)
        self.tasks = tasks
        self.agenda = agenda

    # ==================================================================================================
    # Visibilité et droits
    # ==================================================================================================

    def _visible_clause(self):
        return self._shared_visible_clause()

    def _get(self, s: Session, note_id: int) -> Note:
        note = s.exec(select(Note).where(Note.id == note_id, self._visible_clause())).first()
        if note is None:
            raise NotFound(self.not_found)
        return note

    def _can_edit(self, s: Session, note: Note) -> bool:
        if note.owner_id == self.actor.id:
            return True
        share = s.get(NoteShare, (note.id, self.actor.id))
        return share is not None and share.can_edit

    def _get_editable(self, s: Session, note_id: int) -> Note:
        note = self._get(s, note_id)
        if not self._can_edit(s, note):
            raise Forbidden("Cette note est en lecture seule pour vous.")
        return note

    def _get_owned(self, s: Session, note_id: int, action: str) -> Note:
        note = self._get(s, note_id)
        if note.owner_id != self.actor.id:
            raise Forbidden(f"Seul le propriétaire peut {action} cette note.")
        return note

    # ==================================================================================================
    # Lecture
    # ==================================================================================================

    def _build(self, s: Session, notes: list[Note]) -> list[NoteOut]:
        if not notes:
            return []
        ids = [n.id for n in notes]
        me = self.actor.id
        projects = self._visible_projects(s)
        tags = self._tags_by_item(s, ids)
        shares = self._shares_by_item(s, ids)
        pinned = set(
            s.exec(select(NotePin.note_id).where(NotePin.user_id == me, NotePin.note_id.in_(ids))).all()
        )
        outs = []
        for n in notes:
            mine = {share.user_id: share for share in shares[n.id]}
            can_edit = n.owner_id == me or (me in mine and mine[me].can_edit)
            outs.append(
                NoteOut(
                    id=n.id,
                    owner_id=n.owner_id,
                    title=n.title,
                    notes=n.notes,
                    project=self._project_out(projects, n.project_id),
                    tags=tags[n.id],
                    shared_with=sorted(mine),
                    shares=[ShareSpec(user_id=u, can_edit=mine[u].can_edit) for u in sorted(mine)],
                    created_at=n.created_at,
                    updated_at=n.updated_at,
                    can_delete=can_edit,
                    emoji=n.emoji,
                    is_public=n.is_public,
                    can_edit=can_edit,
                    pinned=n.id in pinned,
                )
            )
        return outs

    def _out(self, s: Session, note: Note) -> NoteOut:
        return self._build(s, [note])[0]

    def get(self, note_id: int) -> NoteOut:
        with self.uow() as w:
            return self._out(w.session, self._get(w.session, note_id))

    def list(self, flt: NoteFilter | None = None) -> list[NoteOut]:
        """Notes visibles : épinglées d'abord, puis les plus récemment modifiées."""
        flt = flt or NoteFilter()
        me = self.actor.id
        with self.uow() as w:
            s = w.session
            query = select(Note).where(self._visible_clause())
            if flt.scope == "mine":
                query = query.where(Note.owner_id == me)
            elif flt.scope == "shared":
                query = query.where(Note.owner_id != me)
            if flt.project_ids:
                real = [p for p in flt.project_ids if p is not None]
                clauses = [Note.project_id.in_(real)] if real else []
                if None in flt.project_ids:
                    clauses.append(Note.project_id.is_(None))
                query = query.where(or_(*clauses))
            if flt.tag_ids:
                tagged = select(NoteTag.note_id).where(NoteTag.tag_id.in_(flt.tag_ids))
                query = query.where(Note.id.in_(tagged))
            outs = self._build(s, list(s.exec(query).all()))
        if flt.text.strip():
            needles = rules.normalize_text(flt.text).split()
            outs = [n for n in outs if all(needle in _haystack(n) for needle in needles)]
        outs.sort(key=lambda n: (n.updated_at, n.id), reverse=True)
        outs.sort(key=lambda n: not n.pinned)  # tri stable : épinglées d'abord
        return outs

    # ==================================================================================================
    # Écriture
    # ==================================================================================================

    def create(self, data: NoteCreate) -> NoteOut:
        title = data.title.strip()
        if not title:
            raise InvalidOperation("Le titre est obligatoire.")
        with self.uow(label=f"Créer la note {quoted(title)}") as w:
            s = w.session
            self._check_project(s, data.project_id)
            note = Note(
                owner_id=self.actor.id,
                title=title,
                notes=data.notes,
                emoji=data.emoji.strip() or NOTE_DEFAULT_EMOJI,
                project_id=data.project_id,
                is_public=data.is_public,
            )
            s.add(note)
            s.flush()
            if data.tag_ids:
                self._set_tags(s, note, data.tag_ids)
            s.flush()
            return self._out(s, note)

    def update(self, note_id: int, patch: NotePatch) -> NoteOut:
        fields = {k: getattr(patch, k) for k in patch.model_fields_set}
        if not fields:
            return self.get(note_id)
        for key in _REQUIRED_FIELDS & fields.keys():
            if fields[key] is None:
                raise InvalidOperation(f"Le champ « {key} » ne peut pas être vide.")
        with self.uow() as probe:
            label = _update_label(self._get(probe.session, note_id).title, fields)
        group_key = f"note:{note_id}:{','.join(sorted(fields))}"
        with self.uow(label=label, group_key=group_key) as w:
            s = w.session
            note = self._get_editable(s, note_id)
            self._apply(s, note, fields)
            s.flush()
            return self._out(s, note)

    def _apply(self, s: Session, note: Note, fields: dict) -> None:
        if "is_public" in fields and fields["is_public"] != note.is_public and note.owner_id != self.actor.id:
            raise Forbidden("Seul le propriétaire peut rendre cette note publique ou privée.")
        if "title" in fields:
            title = fields["title"].strip()
            if not title:
                raise InvalidOperation("Le titre est obligatoire.")
            note.title = title
        if "emoji" in fields:
            note.emoji = fields["emoji"].strip() or NOTE_DEFAULT_EMOJI
        for key in ("notes", "is_public"):
            if key in fields:
                setattr(note, key, fields[key])
        if "project_id" in fields:
            self._check_project(s, fields["project_id"])
            note.project_id = fields["project_id"]
        if "tag_ids" in fields:
            self._set_tags(s, note, fields["tag_ids"] or [])
        self._touch(s, note)

    def delete(self, note_id: int) -> None:
        with self.uow() as probe:
            title = self._get(probe.session, note_id).title
        with self.uow(label=f"Supprimer la note {quoted(title)}") as w:
            s = w.session
            note = self._get_editable(s, note_id)
            for model in (NoteTag, NoteShare, NotePin):
                for row in s.exec(select(model).where(model.note_id == note.id)).all():
                    s.delete(row)
            forget_mutes(s, "note", note.id)
            s.flush()
            s.delete(note)

    def set_shares(self, note_id: int, shares: list[ShareSpec]) -> NoteOut:
        """Avec qui la note est partagée, et si chacun peut la modifier (réservé au propriétaire)."""
        with self.uow() as probe:
            title = self._get(probe.session, note_id).title
        with self.uow(label=f"Partager la note {quoted(title)}") as w:
            s = w.session
            note = self._get_owned(s, note_id, "partager")
            wanted = {share.user_id: share.can_edit for share in shares if share.user_id != note.owner_id}
            existing = set(s.exec(select(User.id).where(User.id.in_(wanted))).all())
            if wanted.keys() - existing:
                raise NotFound("Utilisateur introuvable.")
            current = {sh.user_id: sh for sh in s.exec(select(NoteShare).where(NoteShare.note_id == note_id))}
            for user_id, share in current.items():
                if user_id not in wanted:
                    s.delete(share)
                    pin = s.get(NotePin, (note_id, user_id))
                    if pin is not None and not note.is_public:
                        s.delete(pin)  # elle disparaît de sa liste : son épingle aussi
                elif share.can_edit != wanted[user_id]:
                    share.can_edit = wanted[user_id]
                    s.add(share)
            for user_id in wanted.keys() - current.keys():
                s.add(NoteShare(note_id=note_id, user_id=user_id, can_edit=wanted[user_id]))
            self._touch(s, note)
            s.flush()
            return self._out(s, note)

    def set_pinned(self, note_id: int, pinned: bool) -> NoteOut:
        """Épingle (ou non) la note en haut de **ma** liste."""
        with self.uow() as probe:
            title = self._get(probe.session, note_id).title
        label = f"{'Épingler' if pinned else 'Désépingler'} la note {quoted(title)}"
        with self.uow(label=label) as w:
            s = w.session
            note = self._get(s, note_id)
            pin = s.get(NotePin, (note_id, self.actor.id))
            if pinned and pin is None:
                s.add(NotePin(note_id=note_id, user_id=self.actor.id))
            elif not pinned and pin is not None:
                s.delete(pin)
            s.flush()
            return self._out(s, note)

    # ==================================================================================================
    # Liens internes
    # ==================================================================================================

    def resolve(self, refs: list[str]) -> list[RefOut]:
        """Ce que désigne chaque lien interne (``"task:12"``…) pour l'utilisateur courant : titre actuel et
        pictogramme, ou ``available=False`` (supprimé, ou pas visible)."""
        wanted: dict[str, list[int]] = {kind: [] for kind in rules.REF_KINDS}
        parsed = []
        for ref in refs:
            found = rules.parse_ref(ref)
            if found is not None:
                parsed.append(found)
                wanted[found[0]].append(found[1])
        with self.uow() as w:
            known = self._titles(w.session, wanted)
        result = []
        for kind, item_id in dict.fromkeys(parsed):
            title, emoji = known.get((kind, item_id), ("", REF_EMOJI[kind]))
            result.append(
                RefOut(
                    ref=f"{kind}:{item_id}",
                    kind=kind,
                    id=item_id,
                    title=title,
                    emoji=emoji,
                    available=(kind, item_id) in known,
                )
            )
        return result

    def _titles(self, s: Session, wanted: dict[str, list[int]]) -> dict[tuple[str, int], tuple[str, str]]:
        known: dict[tuple[str, int], tuple[str, str]] = {}
        if wanted["task"]:
            rows = s.exec(
                select(Task.id, Task.title).where(Task.id.in_(wanted["task"]), self.tasks._visible_clause())
            ).all()
            known.update({("task", i): (t, REF_EMOJI["task"]) for i, t in rows})
        if wanted["event"]:
            rows = s.exec(
                select(Event.id, Event.title).where(
                    Event.id.in_(wanted["event"]), self.agenda._visible_clause()
                )
            ).all()
            known.update({("event", i): (t, REF_EMOJI["event"]) for i, t in rows})
        if wanted["note"]:
            rows = s.exec(
                select(Note.id, Note.title, Note.emoji).where(
                    Note.id.in_(wanted["note"]), self._visible_clause()
                )
            ).all()
            known.update({("note", i): (t, e) for i, t, e in rows})
        return known

    def backlinks(self, ref: str) -> list[RefOut]:
        """Notes, tâches et événements visibles dont le texte contient un lien vers ``ref`` (« Cité
        dans »)."""
        target = rules.parse_ref(ref)
        if target is None:
            raise InvalidOperation("Lien interne invalide.")
        pattern = rules.ref_pattern(*target)
        result: list[RefOut] = []
        with self.uow() as w:
            s = w.session
            sources = (
                ("note", Note, self._visible_clause()),
                ("task", Task, self.tasks._visible_clause()),
                ("event", Event, self.agenda._visible_clause()),
            )
            for kind, model, visible in sources:
                rows = s.exec(
                    select(model).where(model.notes.like(pattern), visible).limit(BACKLINKS_LIMIT)
                ).all()
                for row in rows:
                    if (kind, row.id) == target or f"]({ref})" not in row.notes:
                        continue  # (LIKE ignore la casse et « _ » : on revérifie)
                    result.append(
                        RefOut(
                            ref=f"{kind}:{row.id}",
                            kind=kind,
                            id=row.id,
                            title=row.title,
                            emoji=getattr(row, "emoji", None) or REF_EMOJI[kind],
                            available=True,
                        )
                    )
        return sorted(result, key=lambda r: (_KIND_ORDER[r.kind], r.title.lower()))


def _haystack(note: NoteOut) -> str:
    parts = [note.title, note.notes, *(tag.name for tag in note.tags)]
    if note.project:
        parts.append(note.project.name)
    return rules.normalize_text(" ".join(parts))


def _update_label(title: str, fields: dict) -> str:
    name = quoted(title)
    keys = set(fields)
    if keys == {"title"}:
        return f"Renommer la note {name}"
    if keys == {"notes"}:
        return f"Modifier le texte de la note {name}"
    return f"Modifier la note {name}"
