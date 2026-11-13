"""``RemoteDataSource`` : la source de données de l'interface sur le client bureau.

Mêmes sous-objets et mêmes méthodes (signatures, types de retour, erreurs) que les services utilisés par
:class:`organizer.core.datasource.LocalDataSource`, mais chaque appel passe par l'API REST du serveur.
Les objets envoyés ne contiennent que les champs **explicitement fournis** (``exclude_unset``), comme les
services l'attendent (patch partiel, héritage des attributs d'une sous-tâche…).

Les données qui changent rarement (projets, tags, boards, utilisateurs, préférences, état « annuler »)
sont gardées en mémoire (``ApiClient.cache``, voir :mod:`organizer.client.cache`) : chaque requête coûte un
aller-retour réseau, ≈ 300 ms par Internet.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import quote

from pydantic import BaseModel

from organizer.client import system
from organizer.client.api import UNDO_KEY, ApiClient
from organizer.client.cache import EVERYTHING
from organizer.core.events import ORIGIN_HEADER
from organizer.core.schemas import (
    AdminUserPatch,
    ApiKeyCreated,
    ApiKeyOut,
    BoardContent,
    BoardIn,
    BoardOut,
    BoardPatch,
    ColumnIn,
    ColumnPatch,
    EventCreate,
    EventFilter,
    EventOut,
    EventPatch,
    EventTimes,
    LinkIn,
    LinkOut,
    LinkPatch,
    NoteCreate,
    NoteFilter,
    NoteOut,
    NotePatch,
    NotificationOut,
    PasswordChange,
    ProfilePatch,
    ProjectIn,
    ProjectOut,
    ProjectPatch,
    RefOut,
    SessionOut,
    ShareSpec,
    TagIn,
    TagOut,
    TagPatch,
    TaskCreate,
    TaskFilter,
    TaskOut,
    TaskPatch,
    TaskSort,
    UndoResult,
    UndoStatus,
    UserCreateIn,
    UserOut,
    UserPublic,
)

NOTIFICATIONS_KEY = "notifications:unread"


def _sent(model: BaseModel) -> dict[str, Any]:
    """Champs explicitement fournis, en JSON."""
    return model.model_dump(mode="json", exclude_unset=True)


def _full(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")


class _Part:
    def __init__(self, api: ApiClient) -> None:
        self.api = api


class RemoteTasks(_Part):
    def get(self, task_id: int) -> TaskOut:
        return self.api.call("GET", f"/tasks/{task_id}", TaskOut)

    def subtasks(self, parent_id: int) -> list[TaskOut]:
        return self.api.call("GET", f"/tasks/{parent_id}/subtasks", list[TaskOut])

    def list(self, flt: TaskFilter | None = None, sort: TaskSort | None = None) -> list[TaskOut]:
        body = {"filter": _full(flt or TaskFilter()), "sort": _full(sort or TaskSort())}
        return self.api.call("POST", "/tasks/query", list[TaskOut], json=body)

    def reminders_due(self) -> list[TaskOut]:
        return self.api.call("GET", "/tasks/reminders", list[TaskOut])

    def create(self, data: TaskCreate) -> TaskOut:
        return self.api.call("POST", "/tasks", TaskOut, json=_sent(data))

    def update(self, task_id: int, patch: TaskPatch) -> TaskOut:
        return self.api.call("PATCH", f"/tasks/{task_id}", TaskOut, json=_sent(patch))

    def move(self, task_id: int, patch: TaskPatch | None = None, order: list[int] | None = None) -> TaskOut:
        body = {"patch": _sent(patch) if patch is not None else None, "order": order}
        return self.api.call("POST", f"/tasks/{task_id}/move", TaskOut, json=body)

    def delete(self, task_id: int, with_subtasks: bool = False) -> None:
        self.api.call("DELETE", f"/tasks/{task_id}", params={"with_subtasks": with_subtasks})

    def duplicate(self, task_id: int) -> TaskOut:
        return self.api.call("POST", f"/tasks/{task_id}/duplicate", TaskOut)

    def attach(self, child_id: int, parent_id: int) -> TaskOut:
        return self.api.call("POST", f"/tasks/{child_id}/attach", TaskOut, json={"parent_id": parent_id})

    def detach(self, child_id: int) -> TaskOut:
        return self.api.call("POST", f"/tasks/{child_id}/detach", TaskOut)

    def reorder_subtasks(self, parent_id: int, ordered_ids: list[int]) -> list[TaskOut]:
        return self.api.call(
            "POST", f"/tasks/{parent_id}/subtasks/reorder", list[TaskOut], json={"ids": ordered_ids}
        )

    def set_shares(self, task_id: int, user_ids: list[int]) -> TaskOut:
        return self.api.call("PUT", f"/tasks/{task_id}/shares", TaskOut, json={"user_ids": user_ids})

    def add_link(self, task_id: int, data: LinkIn) -> LinkOut:
        return self.api.call("POST", f"/tasks/{task_id}/links", LinkOut, json=_sent(data))

    def update_link(self, link_id: int, patch: LinkPatch) -> LinkOut:
        return self.api.call("PATCH", f"/links/{link_id}", LinkOut, json=_sent(patch))

    def remove_link(self, link_id: int) -> None:
        self.api.call("DELETE", f"/links/{link_id}")


class RemoteAgenda(_Part):
    """Événements du calendrier (``AgendaService``)."""

    def get(self, event_id: int) -> EventOut:
        return self.api.call("GET", f"/agenda/{event_id}", EventOut)

    def list(self, flt: EventFilter | None = None) -> list[EventOut]:
        return self.api.call("POST", "/agenda/query", list[EventOut], json=_full(flt or EventFilter()))

    def reminders_due(self, now: datetime) -> list[EventOut]:
        return self.api.call(
            "GET", "/agenda/reminders", list[EventOut], params={"now": now.replace(tzinfo=None).isoformat()}
        )

    def create(self, data: EventCreate) -> EventOut:
        return self.api.call("POST", "/agenda", EventOut, json=_sent(data))

    def update(self, event_id: int, patch: EventPatch) -> EventOut:
        return self.api.call("PATCH", f"/agenda/{event_id}", EventOut, json=_sent(patch))

    def delete(self, event_id: int) -> None:
        self.api.call("DELETE", f"/agenda/{event_id}")

    def set_shares(self, event_id: int, shares: list[ShareSpec]) -> EventOut:
        body = {"shares": [_full(share) for share in shares]}
        return self.api.call("PUT", f"/agenda/{event_id}/shares", EventOut, json=body)

    def add_link(self, event_id: int, data: LinkIn) -> LinkOut:
        return self.api.call("POST", f"/agenda/{event_id}/links", LinkOut, json=_sent(data))

    def update_link(self, link_id: int, patch: LinkPatch) -> LinkOut:
        return self.api.call("PATCH", f"/agenda-links/{link_id}", LinkOut, json=_sent(patch))

    def remove_link(self, link_id: int) -> None:
        self.api.call("DELETE", f"/agenda-links/{link_id}")

    def from_task(
        self, task_id: int, times: EventTimes | None = None, extra: EventPatch | None = None
    ) -> EventOut:
        body = {
            "times": _full(times) if times is not None else None,
            "extra": _sent(extra) if extra is not None else None,
        }
        return self.api.call("POST", f"/tasks/{task_id}/to-event", EventOut, json=body)

    def to_task(self, event_id: int, extra: TaskPatch | None = None) -> TaskOut:
        body = _sent(extra) if extra is not None else None
        return self.api.call("POST", f"/agenda/{event_id}/to-task", TaskOut, json=body)


class RemoteNotes(_Part):
    """Notes et liens internes (``NoteService``)."""

    def get(self, note_id: int) -> NoteOut:
        return self.api.call("GET", f"/notes/{note_id}", NoteOut)

    def list(self, flt: NoteFilter | None = None) -> list[NoteOut]:
        return self.api.call("POST", "/notes/query", list[NoteOut], json=_full(flt or NoteFilter()))

    def create(self, data: NoteCreate) -> NoteOut:
        return self.api.call("POST", "/notes", NoteOut, json=_sent(data))

    def update(self, note_id: int, patch: NotePatch) -> NoteOut:
        return self.api.call("PATCH", f"/notes/{note_id}", NoteOut, json=_sent(patch))

    def delete(self, note_id: int) -> None:
        self.api.call("DELETE", f"/notes/{note_id}")

    def set_shares(self, note_id: int, shares: list[ShareSpec]) -> NoteOut:
        body = {"shares": [_full(share) for share in shares]}
        return self.api.call("PUT", f"/notes/{note_id}/shares", NoteOut, json=body)

    def set_pinned(self, note_id: int, pinned: bool) -> NoteOut:
        return self.api.call("PUT", f"/notes/{note_id}/pin", NoteOut, json={"pinned": pinned})

    def resolve(self, refs: list[str]) -> list[RefOut]:
        if not refs:
            return []
        return self.api.call("POST", "/refs/resolve", list[RefOut], json={"refs": list(refs)})

    def backlinks(self, ref: str) -> list[RefOut]:
        return self.api.call("GET", "/refs/backlinks", list[RefOut], params={"ref": ref})


class RemoteProjects(_Part):
    def list(self, include_archived: bool = False) -> list[ProjectOut]:
        return self.api.cache.get(
            f"projects:{include_archived}",
            lambda: self.api.call(
                "GET", "/projects", list[ProjectOut], params={"include_archived": include_archived}
            ),
            tables=["project"],
        )

    def get(self, project_id: int) -> ProjectOut:
        return self.api.call("GET", f"/projects/{project_id}", ProjectOut)

    def create(self, data: ProjectIn) -> ProjectOut:
        return self.api.call("POST", "/projects", ProjectOut, json=_sent(data))

    def update(self, obj_id: int, patch: ProjectPatch) -> ProjectOut:
        return self.api.call("PATCH", f"/projects/{obj_id}", ProjectOut, json=_sent(patch))

    def delete(self, project_id: int) -> None:
        self.api.call("DELETE", f"/projects/{project_id}")

    def reorder(self, ordered_ids: list[int]) -> None:
        self.api.call("POST", "/projects/reorder", json={"ids": ordered_ids})

    def merge(self, source_id: int, target_id: int) -> ProjectOut:
        return self.api.call(
            "POST", f"/projects/{source_id}/merge", ProjectOut, json={"target_id": target_id}
        )


class RemoteTags(_Part):
    def list(self) -> list[TagOut]:
        return self.api.cache.get("tags", lambda: self.api.call("GET", "/tags", list[TagOut]), tables=["tag"])

    def get(self, tag_id: int) -> TagOut:
        return self.api.call("GET", f"/tags/{tag_id}", TagOut)

    def create(self, data: TagIn) -> TagOut:
        return self.api.call("POST", "/tags", TagOut, json=_sent(data))

    def suggest_color(self, avoid: list[str] | None = None) -> str:
        return self.api.call("GET", "/tags/suggest-color", str, params={"avoid": list(avoid or [])})

    def update(self, obj_id: int, patch: TagPatch) -> TagOut:
        return self.api.call("PATCH", f"/tags/{obj_id}", TagOut, json=_sent(patch))

    def delete(self, tag_id: int) -> None:
        self.api.call("DELETE", f"/tags/{tag_id}")

    def merge(self, source_id: int, target_id: int) -> TagOut:
        return self.api.call("POST", f"/tags/{source_id}/merge", TagOut, json={"target_id": target_id})

    def reorder(self, ordered_ids: list[int]) -> None:
        self.api.call("POST", "/tags/reorder", json={"ids": ordered_ids})


class RemoteUndo(_Part):
    def status(self) -> UndoStatus:
        # Mis à jour par la réponse de chaque écriture (en-tête ``X-Organizer-Undo``), oublié à chaque
        # modification signalée par le temps réel (autre appareil).
        return self.api.cache.get(UNDO_KEY, lambda: self.api.call("GET", "/undo", UndoStatus), [EVERYTHING])

    def undo(self) -> UndoResult | None:
        return self.api.call("POST", "/undo", UndoResult)

    def redo(self) -> UndoResult | None:
        return self.api.call("POST", "/redo", UndoResult)


class RemoteNotifications(_Part):
    def list(self, limit: int = 200, after: int | None = None) -> list[NotificationOut]:
        params = {"after": after} if after is not None else None
        return self.api.call("GET", "/notifications", list[NotificationOut], params=params)[:limit]

    def muted(self, item_type: str, item_id: int) -> bool:
        return self.api.call("GET", f"/notifications/mute/{quote(item_type)}/{item_id}", bool)

    def set_muted(self, item_type: str, item_id: int, muted: bool) -> bool:
        return self.api.call(
            "PUT", f"/notifications/mute/{quote(item_type)}/{item_id}", bool, json={"muted": muted}
        )

    def unread_count(self) -> int:
        # Demandé à chaque rafraîchissement de page (bulle de la colonne de gauche) : gardé en mémoire,
        # oublié à chaque modification signalée par le temps réel.
        return self.api.cache.get(
            NOTIFICATIONS_KEY, lambda: self.api.call("GET", "/notifications/unread-count", int), [EVERYTHING]
        )

    def conflict_target(self, item_type: str, item_id: int) -> int | None:
        return self.api.call(
            "GET", f"/notifications/conflict-target/{quote(item_type)}/{item_id}", int | None
        )

    def mark_read(self, ids: list[int] | None = None) -> int:
        count = self.api.call("POST", "/notifications/read", int, json={"ids": ids})
        self.api.cache.put(NOTIFICATIONS_KEY, count, [EVERYTHING])
        return count


class RemoteAttachments(_Part):
    def upload(
        self, task_id: int, filename: str, stream: BinaryIO, content_type: str | None = None
    ) -> LinkOut:
        files = {"file": (filename, stream, content_type or "application/octet-stream")}
        return self.api.call("POST", f"/tasks/{task_id}/attachments", LinkOut, files=files)

    def upload_event(
        self, event_id: int, filename: str, stream: BinaryIO, content_type: str | None = None
    ) -> LinkOut:
        files = {"file": (filename, stream, content_type or "application/octet-stream")}
        return self.api.call("POST", f"/agenda/{event_id}/attachments", LinkOut, files=files)

    def download(self, attachment_id: str) -> tuple[str, bytes]:
        """Contenu d'une pièce jointe et son nom de fichier."""
        response = self.api.request("GET", f"/attachments/{quote(attachment_id)}", params={"download": True})
        return system.filename_from_disposition(response.headers.get("content-disposition", "")), (
            response.content
        )


class RemoteBoards(_Part):
    def list(self) -> list[BoardOut]:
        return self.api.cache.get(
            "boards",
            lambda: self.api.call("GET", "/boards", list[BoardOut]),
            tables=["board", "board_column", "board_share"],
        )

    def get(self, board_id: int) -> BoardOut:
        return self.api.call("GET", f"/boards/{board_id}", BoardOut)

    def content(self, board_id: int, flt: TaskFilter | None = None) -> BoardContent:
        body = {"json": _full(flt)} if flt is not None else {}
        return self.api.call("POST", f"/boards/{board_id}/content", BoardContent, **body)

    def create(self, data: BoardIn) -> BoardOut:
        return self.api.call("POST", "/boards", BoardOut, json=_sent(data))

    def update(self, board_id: int, patch: BoardPatch) -> BoardOut:
        return self.api.call("PATCH", f"/boards/{board_id}", BoardOut, json=_sent(patch))

    def delete(self, board_id: int) -> None:
        self.api.call("DELETE", f"/boards/{board_id}")

    def set_shares(self, board_id: int, user_ids: list[int]) -> BoardOut:
        return self.api.call("PUT", f"/boards/{board_id}/shares", BoardOut, json={"user_ids": user_ids})

    def add_column(self, board_id: int, data: ColumnIn) -> BoardOut:
        return self.api.call("POST", f"/boards/{board_id}/columns", BoardOut, json=_sent(data))

    def update_column(self, column_id: int, patch: ColumnPatch) -> BoardOut:
        return self.api.call("PATCH", f"/columns/{column_id}", BoardOut, json=_sent(patch))

    def delete_column(self, column_id: int) -> BoardOut:
        return self.api.call("DELETE", f"/columns/{column_id}", BoardOut)

    def reorder_columns(self, board_id: int, column_ids: list[int]) -> BoardOut:
        return self.api.call(
            "POST", f"/boards/{board_id}/columns/reorder", BoardOut, json={"ids": column_ids}
        )

    def place(self, board_id: int, task_id: int, column_id: int, index: int | None = None) -> None:
        self.api.call(
            "PUT", f"/boards/{board_id}/cards/{task_id}", json={"column_id": column_id, "index": index}
        )

    def remove(self, board_id: int, task_id: int) -> None:
        self.api.call("DELETE", f"/boards/{board_id}/cards/{task_id}")


class RemoteAccount(_Part):
    def me(self) -> UserOut:
        return self.api.cache.get("me", lambda: self.api.call("GET", "/auth/me", UserOut))

    def update_profile(self, patch: ProfilePatch) -> UserOut:
        return self.api.call("PATCH", "/users/me", UserOut, json=_sent(patch))

    def change_password(self, change: PasswordChange) -> None:
        self.api.call("POST", "/users/me/password", json=_full(change))

    def get_pref(self, key: str, default: Any = None) -> Any:
        value = self.api.cache.get(
            f"pref:{key}", lambda: self.api.call("GET", f"/users/me/prefs/{quote(key, safe='')}", Any)
        )
        return default if value is None else copy.deepcopy(value)

    def set_pref(self, key: str, value: Any) -> None:
        self.api.call("PUT", f"/users/me/prefs/{quote(key, safe='')}", json=value)
        self.api.cache.put(f"pref:{key}", copy.deepcopy(value))

    def public_url(self) -> str | None:
        data = self.api.cache.get("public_url", lambda: self.api.call("GET", "/server/public-url", Any))
        return (data or {}).get("url")

    def set_public_url(self, url: str | None) -> str | None:
        data = self.api.call("PUT", "/server/public-url", Any, json={"url": url})
        self.api.cache.put("public_url", data)
        return data.get("url")

    def sessions(self) -> list[SessionOut]:
        return self.api.call("GET", "/auth/sessions", list[SessionOut])

    def revoke_session(self, session_id: int) -> None:
        self.api.call("DELETE", f"/auth/sessions/{session_id}")

    def revoke_other_sessions(self) -> None:
        self.api.call("POST", "/auth/sessions/revoke-others")

    def all_users(self) -> list[UserOut]:
        return self.api.call("GET", "/users/all", list[UserOut])

    def create_user(self, data: UserCreateIn) -> UserOut:
        return self.api.call("POST", "/users", UserOut, json=_full(data))

    def admin_update(self, user_id: int, patch: AdminUserPatch) -> UserOut:
        return self.api.call("PATCH", f"/users/{user_id}", UserOut, json=_sent(patch))

    def backup_keys(self) -> list[ApiKeyOut]:
        return self.api.call("GET", "/admin/backup-keys", list[ApiKeyOut])

    def create_backup_key(self, label: str = "") -> ApiKeyCreated:
        return self.api.call("POST", "/admin/backup-keys", ApiKeyCreated, json={"label": label})

    def revoke_backup_key(self, key_id: int) -> None:
        self.api.call("DELETE", f"/admin/backup-keys/{key_id}")


class RemoteDataSource:
    """Accès aux données par l'API du serveur (client bureau)."""

    is_desktop = True

    def __init__(
        self,
        api: ApiClient,
        user: UserOut | None = None,
        *,
        opener: Callable[[str], None] = system.open_path,
        browser: Callable[[str], None] = system.open_url,
        cache_dir: Path | None = None,
        origin: str | None = None,
    ) -> None:
        """``origin`` : identifiant de la page, envoyé avec chaque requête pour que le serveur ne la
        prévienne pas de ses propres modifications (temps réel)."""
        if origin:
            api = api.with_headers({ORIGIN_HEADER: origin})
        self.api = api
        self.tasks = RemoteTasks(api)
        self.agenda = RemoteAgenda(api)
        self.notes = RemoteNotes(api)
        self.projects = RemoteProjects(api)
        self.tags = RemoteTags(api)
        self.undo = RemoteUndo(api)
        self.notifications = RemoteNotifications(api)
        self.attachments = RemoteAttachments(api)
        self.boards = RemoteBoards(api)
        self.account = RemoteAccount(api)
        self.user = user if user is not None else self.account.me()
        self._opener = opener
        self._browser = browser
        self._cache_dir = cache_dir or system.cache_dir()

    def users_public(self) -> list[UserPublic]:
        return self.api.cache.get("users", lambda: self.api.call("GET", "/users", list[UserPublic]))

    def attachment_url(self, attachment_id: str) -> str:
        return f"{self.api.base_url}/api/v1/attachments/{quote(attachment_id)}"

    def web_url(self, path: str) -> str | None:
        """Adresse web d'une page (« copier le lien ») : l'adresse publique réglée sur le serveur, sinon
        celle du serveur configuré (jamais l'adresse locale de la fenêtre du client)."""
        base = self.account.public_url() or self.api.server_url
        return f"{base.rstrip('/')}{path}"

    def backup_url(self, uploads: bool = True) -> str:
        return f"{self.api.base_url}/api/v1/admin/backup" + ("" if uploads else "?uploads=false")

    def save_backup(self, uploads: bool = True, folder: Path | None = None) -> Path:
        """Télécharge une sauvegarde du serveur (admin) dans ``folder`` (par défaut le dossier
        Téléchargements) ; renvoie le chemin de l'archive."""
        return self.api.save("/admin/backup", folder or system.downloads_dir(), params={"uploads": uploads})

    # --- ouverture avec le système (spécifications §4.4) ---

    def open_url(self, url: str) -> None:
        """Ouvre une adresse web dans le navigateur par défaut."""
        self._browser(url)

    def open_path(self, target: str) -> None:
        """Ouvre un fichier / dossier local avec l'application par défaut du système."""
        self._opener(str(system.resolve_local_path(target)))

    def open_attachment(self, attachment_id: str) -> Path:
        """Télécharge la pièce jointe dans le cache local, puis l'ouvre ; renvoie le chemin du fichier."""
        filename, content = self.attachments.download(attachment_id)
        path = system.cache_file(self._cache_dir, attachment_id, filename)
        path.write_bytes(content)
        self._opener(str(path))
        return path
