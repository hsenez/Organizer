"""Sauvegarde du serveur : archive ``.tar`` de la base et des pièces jointes.

Contenu de l'archive (dans cet ordre) :

- ``organizer.db`` : image **cohérente** de la base, prise par l'API de sauvegarde de SQLite (le serveur
  continue de tourner ; la base est en mode WAL, une simple copie du fichier pourrait être incomplète).
  L'image est un fichier unique (journal ``DELETE``), sans ``-wal`` ni ``-shm`` à côté ;
- ``uploads/<id>`` : fichiers des pièces jointes (facultatif) ;
- ``manifest.json`` : date, version de l'application, nombre d'utilisateurs / tâches…, taille et empreinte
  SHA-256 de chaque fichier. Placé **en dernier** : une archive tronquée (téléchargement interrompu) n'a pas
  de manifeste, ce qui la rend reconnaissable.

L'archive n'est **pas compressée** : un outil de sauvegarde qui dédoublonne (borg…) retrouve ainsi d'un jour à
l'autre les mêmes blocs (pièces jointes inchangées, pages de la base inchangées) et ne stocke que ce qui a
changé ; il compresse lui-même ensuite.

Elle est produite **au fil de l'envoi** (:meth:`BackupArchive.chunks`), sans copie complète sur le disque :
seule l'image de la base passe par un fichier temporaire dans le dossier des données.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tarfile
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from organizer import API_VERSION, __version__
from organizer.config import Settings
from organizer.core.errors import OrganizerError

FORMAT = "organizer-backup"
FORMAT_VERSION = 1
DB_NAME = "organizer.db"
UPLOADS_DIR = "uploads"
MANIFEST_NAME = "manifest.json"
CHUNK = 1024 * 1024
BLOCK = tarfile.BLOCKSIZE  # 512 octets
# Tables dont le nombre de lignes figure dans le manifeste (aperçu avant une restauration).
COUNTED_TABLES = ("user", "task", "project", "tag", "board", "attachment")


class BackupError(OrganizerError):
    status_code = 500


@dataclass(frozen=True)
class _Member:
    name: str  # chemin dans l'archive
    path: Path
    size: int
    mtime: float


def snapshot_database(db_path: Path, dest: Path) -> dict[str, int]:
    """Copie cohérente de la base ``db_path`` dans ``dest`` (fichier unique, vérifié) ; renvoie le nombre de
    lignes des tables principales."""
    source = sqlite3.connect(db_path)
    target = sqlite3.connect(dest)
    try:
        source.backup(target)
        target.execute("PRAGMA journal_mode = DELETE")  # tout dans un seul fichier
        check = target.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise BackupError(f"La copie de la base est abîmée ({check}).")
        tables = {row[0] for row in target.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        return {
            name: target.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            for name in COUNTED_TABLES
            if name in tables
        }
    finally:
        target.close()
        source.close()


def _uploads(folder: Path) -> list[_Member]:
    """Fichiers des pièces jointes (nom = identifiant hexadécimal ; les envois en cours ``.part`` sont
    ignorés), triés par nom."""
    if not folder.is_dir():
        return []
    members = []
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.name.isalnum():
            st = path.stat()
            members.append(_Member(f"{UPLOADS_DIR}/{path.name}", path, st.st_size, st.st_mtime))
    return members


def _header(name: str, size: int, mtime: float, kind: bytes = tarfile.REGTYPE) -> bytes:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mtime = int(mtime)
    info.type = kind
    info.mode = 0o755 if kind == tarfile.DIRTYPE else 0o644
    return info.tobuf(tarfile.PAX_FORMAT, "utf-8", "surrogateescape")


def _padding(size: int) -> bytes:
    return b"\0" * (-size % BLOCK)


class BackupArchive:
    """Une sauvegarde : l'image de la base est prise **à la création** de l'objet (instant de la
    sauvegarde) ; :meth:`chunks` produit ensuite l'archive morceau par morceau.

    Les pièces jointes sont listées juste après l'image : un fichier n'est jamais modifié ni supprimé une
    fois envoyé, donc toutes celles que la base référence sont bien présentes.
    """

    def __init__(self, settings: Settings, include_uploads: bool = True, now: datetime | None = None):
        self.created_at = now or datetime.now(UTC)
        self.include_uploads = include_uploads
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        # Dans le dossier des données (et non /tmp, parfois en mémoire sur le Pi) ; nom en « . » : caché.
        handle = tempfile.NamedTemporaryFile(
            dir=settings.data_dir, prefix=".backup-", suffix=".db", delete=False
        )
        handle.close()
        self._snapshot = Path(handle.name)
        try:
            self.counts = snapshot_database(settings.db_path, self._snapshot)
            st = self._snapshot.stat()
        except BaseException:
            self.cleanup()
            raise
        self.members = [_Member(DB_NAME, self._snapshot, st.st_size, self.created_at.timestamp())]
        if include_uploads:
            self.members += _uploads(settings.uploads_dir)

    @property
    def filename(self) -> str:
        local = self.created_at.astimezone()
        return f"organizer-{local:%Y%m%d-%H%M%S}.tar"

    def cleanup(self) -> None:
        self._snapshot.unlink(missing_ok=True)

    def manifest(self, files: list[dict]) -> dict:
        return {
            "format": FORMAT,
            "format_version": FORMAT_VERSION,
            "created_at": self.created_at.isoformat(),
            "version": __version__,
            "api_version": API_VERSION,
            "includes_uploads": self.include_uploads,
            "counts": self.counts,
            "files": files,
        }

    def chunks(self) -> Iterator[bytes]:
        """L'archive, morceau par morceau (au plus 1 Mo à la fois en mémoire). Supprime l'image de la base à
        la fin, même si l'envoi est interrompu."""
        try:
            files: list[dict] = []
            written = 0
            directory_done = False
            for member in self.members:
                if member.name.startswith(UPLOADS_DIR + "/") and not directory_done:
                    block = _header(UPLOADS_DIR + "/", 0, self.created_at.timestamp(), tarfile.DIRTYPE)
                    written += len(block)
                    yield block
                    directory_done = True
                block = _header(member.name, member.size, member.mtime)
                written += len(block)
                yield block
                digest = hashlib.sha256()
                remaining = member.size
                with member.path.open("rb") as f:
                    while remaining > 0:
                        chunk = f.read(min(CHUNK, remaining))
                        if not chunk:
                            raise BackupError(f"Fichier raccourci pendant la sauvegarde : {member.name}.")
                        digest.update(chunk)
                        remaining -= len(chunk)
                        yield chunk
                pad = _padding(member.size)
                written += member.size + len(pad)
                yield pad
                files.append({"name": member.name, "size": member.size, "sha256": digest.hexdigest()})
            data = json.dumps(self.manifest(files), ensure_ascii=False, indent=2).encode() + b"\n"
            block = _header(MANIFEST_NAME, len(data), self.created_at.timestamp())
            ending = data + _padding(len(data)) + b"\0" * (2 * BLOCK)
            written += len(block) + len(ending)
            # Fin d'archive : deux blocs nuls, puis complément jusqu'à un multiple de 10 Kio (comme ``tar``).
            yield block + ending + b"\0" * (-written % tarfile.RECORDSIZE)
        finally:
            self.cleanup()
