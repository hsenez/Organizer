"""``RemoteDataSource`` : la source de données de l'interface sur le client bureau.

Mêmes sous-objets et mêmes méthodes (signatures, types de retour, erreurs) que les services utilisés par
:class:`organizer.core.datasource.LocalDataSource`, mais chaque appel passe par l'API REST du serveur.
Les objets envoyés ne contiennent que les champs **explicitement fournis** (``exclude_unset``), comme les
services l'attendent (patch partiel, héritage des attributs d'une sous-tâche…).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import quote

from pydantic import BaseModel

from organizer.client import system
from organizer.client.api import ApiClient
from organizer.core.events import ORIGIN_HEADER
from organizer.core.schemas import (
    AdminUserPatch,
    BoardContent,
    BoardIn,
    BoardOut,
    BoardPatch,
    ColumnIn,
    ColumnPatch,
    LinkIn,
    LinkOut,
    LinkPatch,
    PasswordChange,
    ProfilePatch,
    ProjectIn,
    ProjectOut,
    ProjectPatch,
    SessionOut,
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


class RemoteProjects(_Part):
    def list(self, include_archived: bool = False) -> list[ProjectOut]:
        return self.api.call(
            "GET", "/projects", list[ProjectOut], params={"include_archived": include_archived}
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


class RemoteTags(_Part):
    def list(self) -> list[TagOut]:
        return self.api.call("GET", "/tags", list[TagOut])

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
        return self.api.call("GET", "/undo", UndoStatus)

    def undo(self) -> UndoResult | None:
        return self.api.call("POST", "/undo", UndoResult)

    def redo(self) -> UndoResult | None:
        return self.api.call("POST", "/redo", UndoResult)


class RemoteAttachments(_Part):
    def upload(
        self, task_id: int, filename: str, stream: BinaryIO, content_type: str | None = None
    ) -> LinkOut:
        files = {"file": (filename, stream, content_type or "application/octet-stream")}
        return self.api.call("POST", f"/tasks/{task_id}/attachments", LinkOut, files=files)

    def download(self, attachment_id: str) -> tuple[str, bytes]:
        """Contenu d'une pièce jointe et son nom de fichier."""
        response = self.api.request("GET", f"/attachments/{quote(attachment_id)}", params={"download": True})
        return system.filename_from_disposition(response.headers.get("content-disposition", "")), (
            response.content
        )


class RemoteBoards(_Part):
    def list(self) -> list[BoardOut]:
        return self.api.call("GET", "/boards", list[BoardOut])

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
        return self.api.call("GET", "/auth/me", UserOut)

    def update_profile(self, patch: ProfilePatch) -> UserOut:
        return self.api.call("PATCH", "/users/me", UserOut, json=_sent(patch))

    def change_password(self, change: PasswordChange) -> None:
        self.api.call("POST", "/users/me/password", json=_full(change))

    def get_pref(self, key: str, default: Any = None) -> Any:
        value = self.api.call("GET", f"/users/me/prefs/{quote(key, safe='')}", Any)
        return default if value is None else value

    def set_pref(self, key: str, value: Any) -> None:
        self.api.call("PUT", f"/users/me/prefs/{quote(key, safe='')}", json=value)

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
        self.projects = RemoteProjects(api)
        self.tags = RemoteTags(api)
        self.undo = RemoteUndo(api)
        self.attachments = RemoteAttachments(api)
        self.boards = RemoteBoards(api)
        self.account = RemoteAccount(api)
        self.user = user if user is not None else self.account.me()
        self._opener = opener
        self._browser = browser
        self._cache_dir = cache_dir or system.cache_dir()

    def users_public(self) -> list[UserPublic]:
        return self.api.call("GET", "/users", list[UserPublic])

    def attachment_url(self, attachment_id: str) -> str:
        return f"{self.api.base_url}/api/v1/attachments/{quote(attachment_id)}"

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
