"""Restauration d'une sauvegarde (archive produite par :mod:`organizer.server.backup`).

Deux temps, pour que le serveur ne soit arrêté que quelques secondes (``deploy/restore.sh`` les enchaîne) :

1. ``prepare`` (serveur en marche) : lit l'archive **en un seul passage** (fichier ou flux, ex.
   ``borg export-tar … -``), extrait son contenu dans un dossier temporaire du dossier des données et le
   vérifie : rien d'autre que ``organizer.db``, ``uploads/<id>`` et ``manifest.json`` ; manifeste présent
   (sinon l'archive est tronquée) ; taille et empreinte SHA-256 de chaque fichier ; intégrité de la base ;
   version de l'application qui l'a produite. En cas de problème, le dossier temporaire est supprimé et rien
   n'a changé.
2. ``swap`` (serveur arrêté) : met les données actuelles de côté dans ``avant-restauration-<date>/`` (rien
   n'est effacé), puis met en place celles de l'archive. Ce ne sont que des renommages (même disque) :
   instantané.

Ligne de commande : ``python -m organizer.server.restore prepare|swap …`` (voir ``--help``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tarfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import IO

from organizer import __version__
from organizer.server.backup import DB_NAME, FORMAT, FORMAT_VERSION, MANIFEST_NAME, UPLOADS_DIR
from organizer.versioning import parse

CHUNK = 1024 * 1024
MANIFEST_MAX = 50 * 1024 * 1024
DB_FILES = (DB_NAME, f"{DB_NAME}-wal", f"{DB_NAME}-shm")  # la base et ses fichiers de journal (mode WAL)
ASIDE_PREFIX = "avant-restauration-"
EXIT_NEWER = 3  # code de sortie : archive d'une version plus récente (refusée sans --force)


class RestoreError(Exception):
    """Archive refusée ou restauration impossible ; message en français, affichable tel quel."""


@dataclass
class Prepared:
    staging: Path
    manifest: dict
    uploads: int = 0  # pièces jointes extraites
    uploads_size: int = 0
    newer: bool = False  # produite par une version plus récente que celle installée
    sizes: dict[str, int] = field(default_factory=dict)

    @property
    def includes_uploads(self) -> bool:
        return bool(self.manifest.get("includes_uploads"))


def _normalize(name: str) -> str:
    """Nom d'un élément sans ``./`` initial ni ``/`` final (selon l'outil qui a recréé l'archive)."""
    return name.removeprefix("./").rstrip("/")


def _member_kind(name: str) -> str | None:
    """« db », « uploads-dir », « upload », « manifest », ou None (élément interdit)."""
    if name == DB_NAME:
        return "db"
    if name == MANIFEST_NAME:
        return "manifest"
    if name == UPLOADS_DIR:
        return "uploads-dir"
    prefix = UPLOADS_DIR + "/"
    if name.startswith(prefix) and name[len(prefix) :].isalnum():
        return "upload"
    return None


def _copy(source: IO[bytes], target: Path | None, size: int) -> str:
    """Copie ``size`` octets (ou les lit seulement si ``target`` est None) ; renvoie l'empreinte SHA-256."""
    digest = hashlib.sha256()
    out = target.open("wb") if target is not None else None
    try:
        remaining = size
        while remaining > 0:
            chunk = source.read(min(CHUNK, remaining))
            if not chunk:
                raise RestoreError("Archive tronquée (fichier incomplet).")
            digest.update(chunk)
            if out is not None:
                out.write(chunk)
            remaining -= len(chunk)
    finally:
        if out is not None:
            out.close()
    return digest.hexdigest()


def _open(source: Path | IO[bytes]) -> tarfile.TarFile:
    try:
        if isinstance(source, Path):
            return tarfile.open(source, mode="r|*")
        return tarfile.open(fileobj=source, mode="r|*")
    except (tarfile.TarError, OSError) as exc:
        raise RestoreError(f"Ce n'est pas une archive .tar lisible ({exc}).") from exc


def prepare(source: Path | IO[bytes], staging: Path, keep_uploads: bool = True) -> Prepared:
    """Extrait et vérifie l'archive dans ``staging`` (qui ne doit pas exister). ``keep_uploads=False`` :
    les pièces jointes sont vérifiées mais pas extraites (restauration de la base seule)."""
    if staging.exists():
        raise RestoreError(f"Le dossier de travail existe déjà : {staging}")
    staging.mkdir(parents=True)
    try:
        return _prepare(source, staging, keep_uploads)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _prepare(source: Path | IO[bytes], staging: Path, keep_uploads: bool) -> Prepared:
    found: dict[str, tuple[int, str]] = {}  # nom → (taille, empreinte)
    manifest: dict | None = None
    try:
        with _open(source) as tar:
            for member in tar:
                name = _normalize(member.name)
                kind = _member_kind(name)
                if kind is None:
                    raise RestoreError(
                        f"Élément inattendu dans l'archive : {member.name!r}. Restauration refusée."
                    )
                if kind == "uploads-dir":
                    continue
                if not member.isreg():
                    raise RestoreError(
                        f"{member.name!r} n'est pas un fichier ordinaire. Restauration refusée."
                    )
                if name in found or (kind == "manifest" and manifest is not None):
                    raise RestoreError(f"{name!r} figure deux fois dans l'archive.")
                stream = tar.extractfile(member)
                assert stream is not None
                if kind == "manifest":
                    if member.size > MANIFEST_MAX:
                        raise RestoreError("Manifeste anormalement gros.")
                    try:
                        manifest = json.loads(stream.read())
                    except ValueError as exc:
                        raise RestoreError("Manifeste illisible.") from exc
                    continue
                if manifest is not None:
                    raise RestoreError("Le manifeste doit être le dernier élément de l'archive.")
                if kind == "db":
                    target: Path | None = staging / DB_NAME
                else:
                    target = staging / name if keep_uploads else None
                    if target is not None:
                        target.parent.mkdir(exist_ok=True)
                found[name] = (member.size, _copy(stream, target, member.size))
    except tarfile.TarError as exc:
        raise RestoreError(f"Archive abîmée ou tronquée ({exc}).") from exc
    except EOFError as exc:
        raise RestoreError("Archive tronquée.") from exc

    if manifest is None:
        raise RestoreError(
            "Pas de manifeste : l'archive est incomplète (téléchargement interrompu ?) ou ne vient pas "
            "d'Organizer."
        )
    _check_manifest(manifest, found)
    _check_database(staging / DB_NAME)
    uploads = {n: v for n, v in found.items() if n != DB_NAME}
    return Prepared(
        staging=staging,
        manifest=manifest,
        uploads=len(uploads),
        uploads_size=sum(size for size, _ in uploads.values()),
        newer=parse(str(manifest.get("version", "0"))) > parse(__version__),
        sizes={n: size for n, (size, _) in found.items()},
    )


def _check_manifest(manifest: dict, found: dict[str, tuple[int, str]]) -> None:
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise RestoreError("Ce n'est pas une sauvegarde d'Organizer (manifeste inconnu).")
    if not isinstance(manifest.get("format_version"), int) or manifest["format_version"] > FORMAT_VERSION:
        raise RestoreError(
            "Format de sauvegarde plus récent que cette version d'Organizer : mettez d'abord le serveur à "
            "jour (deploy/update.sh)."
        )
    listed = {}
    for entry in manifest.get("files", []):
        try:
            listed[entry["name"]] = (int(entry["size"]), str(entry["sha256"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise RestoreError("Manifeste incomplet (liste des fichiers).") from exc
    if DB_NAME not in found:
        raise RestoreError("L'archive ne contient pas de base de données.")
    missing = sorted(set(listed) - set(found))
    extra = sorted(set(found) - set(listed))
    if missing or extra:
        detail = ", ".join([f"absent : {n}" for n in missing[:3]] + [f"en trop : {n}" for n in extra[:3]])
        raise RestoreError(f"Le contenu ne correspond pas au manifeste ({detail}).")
    damaged = sorted(name for name, value in found.items() if listed[name] != value)
    if damaged:
        raise RestoreError(
            f"Fichier(s) abîmé(s) (empreinte différente) : {', '.join(damaged[:3])}. Restauration refusée."
        )


def _check_database(path: Path) -> None:
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            check = db.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        finally:
            db.close()
    except sqlite3.DatabaseError as exc:
        raise RestoreError(f"La base de l'archive est illisible ({exc}).") from exc
    if check != "ok":
        raise RestoreError(f"La base de l'archive est abîmée ({check}).")
    if "user" not in tables or "task" not in tables:
        raise RestoreError("La base de l'archive n'est pas une base d'Organizer.")


def _size(n: int) -> str:
    for unit in ("o", "Ko", "Mo", "Go"):
        if n < 1024 or unit == "Go":
            return f"{n:.0f} {unit}" if unit == "o" else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024  # type: ignore[assignment]
    return str(n)


def summary(prepared: Prepared, db_only: bool = False) -> str:
    """Description lisible de la sauvegarde (avant de demander confirmation)."""
    m = prepared.manifest
    try:
        created = datetime.fromisoformat(str(m["created_at"])).astimezone().strftime("%d/%m/%Y à %H:%M:%S")
    except (KeyError, ValueError):
        created = "date inconnue"
    counts = m.get("counts") or {}
    labels = (("user", "utilisateur(s)"), ("task", "tâche(s)"), ("project", "projet(s)"), ("tag", "tag(s)"))
    content = ", ".join(f"{counts[k]} {label}" for k, label in labels if k in counts)
    lines = [
        f"   📅 Sauvegarde du {created} (Organizer {m.get('version', '?')})",
        f"   🗃️ Base : {_size(prepared.sizes.get(DB_NAME, 0))}{f' — {content}' if content else ''}",
    ]
    if not prepared.includes_uploads:
        lines.append("   📎 Pièces jointes : absentes de l'archive → celles du serveur sont conservées")
    elif db_only:
        lines.append(f"   📎 Pièces jointes : {prepared.uploads} vérifiées, non restaurées (--db-only)")
    else:
        lines.append(f"   📎 Pièces jointes : {prepared.uploads} ({_size(prepared.uploads_size)})")
    if prepared.newer:
        lines.append(f"   ⚠️ Produite par une version plus récente que celle installée ({__version__}).")
    return "\n".join(lines)


def swap(data_dir: Path, staging: Path, stamp: str, db_only: bool = False) -> Path:
    """Met les données actuelles de côté (``avant-restauration-<stamp>/``) et installe celles de
    ``staging``. À faire **serveur arrêté**. Renvoie le dossier des anciennes données."""
    if not (staging / DB_NAME).is_file():
        raise RestoreError(f"Rien à restaurer dans {staging} (lancez d'abord « prepare »).")
    aside = data_dir / f"{ASIDE_PREFIX}{stamp}"
    aside.mkdir()
    moved: list[str] = []
    for name in DB_FILES:
        if (data_dir / name).exists():
            (data_dir / name).rename(aside / name)
            moved.append(name)
    with_uploads = not db_only and (staging / UPLOADS_DIR).is_dir()
    if with_uploads:
        if (data_dir / UPLOADS_DIR).exists():
            (data_dir / UPLOADS_DIR).rename(aside / UPLOADS_DIR)
            moved.append(UPLOADS_DIR + "/")
        (staging / UPLOADS_DIR).rename(data_dir / UPLOADS_DIR)
    (data_dir / UPLOADS_DIR).mkdir(exist_ok=True)
    (staging / DB_NAME).rename(data_dir / DB_NAME)
    shutil.rmtree(staging, ignore_errors=True)
    _write_note(aside, data_dir, moved)
    return aside


def _write_note(aside: Path, data_dir: Path, moved: list[str]) -> None:
    names = " ".join(n.rstrip("/") for n in moved) or "(rien)"
    (aside / "LISEZMOI.txt").write_text(
        f"""Données d'Organizer en place avant la restauration du {datetime.now():%d/%m/%Y à %H:%M}.

Contenu mis de côté : {names}

Pour revenir à ces données (serveur arrêté) :
    sudo systemctl stop organizer
    cd {data_dir}
    rm -f {" ".join(DB_FILES)}
    {"rm -rf uploads" if UPLOADS_DIR + "/" in moved else "# (pièces jointes non concernées)"}
    mv {aside.name}/* .  &&  rm LISEZMOI.txt  &&  rmdir {aside.name}
    sudo systemctl start organizer

Ce dossier peut être supprimé une fois la restauration vérifiée.
""",
        encoding="utf-8",
    )


# --- ligne de commande -------------------------------------------------------------------------------------


def _fail(message: str, code: int = 1) -> int:
    print(f"❌ {message}", file=sys.stderr)
    return code


def main(argv: list[str] | None = None, stdin: Callable[[], IO[bytes]] = lambda: sys.stdin.buffer) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m organizer.server.restore", description=__doc__.split("\n")[0]
    )
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare", help="extraire et vérifier une archive (serveur en marche)")
    p.add_argument("archive", help="fichier .tar, ou - pour l'entrée standard")
    p.add_argument("--staging", required=True, type=Path, help="dossier de travail (à créer)")
    p.add_argument("--db-only", action="store_true", help="ne pas extraire les pièces jointes")
    p.add_argument("--force", action="store_true", help="accepter une archive d'une version plus récente")
    s = commands.add_parser("swap", help="mettre en place les données préparées (serveur arrêté)")
    s.add_argument("--data-dir", required=True, type=Path)
    s.add_argument("--staging", required=True, type=Path)
    s.add_argument("--stamp", required=True)
    s.add_argument("--db-only", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.command == "prepare":
            source: Path | IO[bytes] = stdin() if args.archive == "-" else Path(args.archive)
            if isinstance(source, Path) and not source.is_file():
                return _fail(f"Archive introuvable : {source}")
            prepared = prepare(source, args.staging, keep_uploads=not args.db_only)
            print(summary(prepared, args.db_only))
            if prepared.newer and not args.force:
                shutil.rmtree(args.staging, ignore_errors=True)
                return _fail(
                    f"Cette sauvegarde vient d'Organizer {prepared.manifest.get('version')}, plus récent que "
                    f"celui installé ({__version__}) : mettez d'abord le serveur à jour (deploy/update.sh), "
                    "ou forcez avec --force.",
                    EXIT_NEWER,
                )
            return 0
        aside = swap(args.data_dir, args.staging, args.stamp, args.db_only)
        print(aside)
        return 0
    except RestoreError as exc:
        return _fail(str(exc))
    except OSError as exc:
        return _fail(f"Erreur d'accès aux fichiers : {exc}")


if __name__ == "__main__":
    sys.exit(main())
