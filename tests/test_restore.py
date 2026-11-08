"""Restauration d'une sauvegarde : vérification de l'archive (``prepare``), échange des dossiers (``swap``),
script ``deploy/restore.sh`` de bout en bout (avec un faux ``systemctl``)."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from organizer.config import Settings
from organizer.core.schemas import TaskCreate
from organizer.server import restore
from organizer.server.backup import MANIFEST_NAME, BackupArchive
from organizer.server.restore import RestoreError
from organizer.server.state import create_state

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def state(data_dir):
    st = create_state(Settings(data_dir=data_dir))
    yield st
    st.engine.dispose()


@pytest.fixture
def alice(state):
    return state.users.create_user("alice", "motdepasse-12", "Alice")


def titles(data_dir: Path) -> list[str]:
    st = create_state(Settings(data_dir=data_dir))
    try:
        user = st.users.list()[0]
        return sorted(t.title for t in st.services_for(user).tasks.list())
    finally:
        st.engine.dispose()


@pytest.fixture
def archive(state, alice, tmp_path) -> Path:
    """Sauvegarde contenant la tâche « Avant » et une pièce jointe."""
    sv = state.services_for(alice)
    task = sv.tasks.create(TaskCreate(title="Avant"))
    sv.attachments.upload(task.id, "a.txt", io.BytesIO(b"ancienne piece jointe"))
    path = tmp_path / "sauvegarde.tar"
    path.write_bytes(b"".join(BackupArchive(state.settings).chunks()))
    return path


def later_changes(state, alice) -> str:
    """Modifications faites après la sauvegarde (qui seront perdues… mais mises de côté)."""
    sv = state.services_for(alice)
    task = sv.tasks.create(TaskCreate(title="Après"))
    return sv.attachments.upload(task.id, "b.txt", io.BytesIO(b"nouvelle")).target


def rewrite(source: Path, target: Path, change) -> Path:
    """Recopie une archive en modifiant ses éléments : ``change(info, data)`` → liste de (info, data)."""
    with tarfile.open(source) as tar, tarfile.open(target, "w") as out:
        for info in tar.getmembers():
            data = tar.extractfile(info).read() if info.isreg() else None
            for new_info, new_data in change(info, data):
                out.addfile(new_info, io.BytesIO(new_data) if new_data is not None else None)
    return target


# --- prepare / swap ---------------------------------------------------------------------------------------


def test_restore_puts_backup_back_and_keeps_current_data_aside(state, alice, archive, data_dir):
    newer_upload = later_changes(state, alice)
    state.engine.dispose()  # « serveur arrêté »
    staging = data_dir / ".restauration-x"
    prepared = restore.prepare(archive, staging)
    assert prepared.uploads == 1 and prepared.manifest["counts"]["task"] == 1 and not prepared.newer
    assert "1 tâche(s)" in restore.summary(prepared)

    aside = restore.swap(data_dir, staging, "20261108-120000")
    assert aside == data_dir / "avant-restauration-20261108-120000" and not staging.exists()
    assert titles(data_dir) == ["Avant"]
    assert not (data_dir / "uploads" / newer_upload).exists()
    assert len(list((data_dir / "uploads").iterdir())) == 1
    # Rien n'est perdu : l'état d'avant est de côté, et il se relit.
    assert (aside / "uploads" / newer_upload).read_bytes() == b"nouvelle"
    assert "Pour revenir à ces données" in (aside / "LISEZMOI.txt").read_text(encoding="utf-8")
    copy = data_dir.parent / "copie"
    shutil.copytree(aside, copy)
    assert titles(copy) == ["Après", "Avant"]


def test_restore_from_stream(archive, tmp_path):
    with archive.open("rb") as stream:
        prepared = restore.prepare(stream, tmp_path / "staging")
    assert (tmp_path / "staging" / "organizer.db").is_file() and prepared.uploads == 1


def test_db_only_keeps_current_attachments(state, alice, archive, data_dir):
    newer_upload = later_changes(state, alice)
    state.engine.dispose()
    staging = data_dir / ".restauration-x"
    prepared = restore.prepare(archive, staging, keep_uploads=False)
    assert prepared.uploads == 1 and not (staging / "uploads").exists()  # vérifiées, pas extraites
    assert "non restaurées" in restore.summary(prepared, db_only=True)
    aside = restore.swap(data_dir, staging, "x", db_only=True)
    assert titles(data_dir) == ["Avant"]
    assert (data_dir / "uploads" / newer_upload).exists() and not (aside / "uploads").exists()


def test_archive_without_attachments_keeps_current_ones(state, alice, data_dir, tmp_path):
    later_changes(state, alice)
    path = tmp_path / "base.tar"
    path.write_bytes(b"".join(BackupArchive(state.settings, include_uploads=False).chunks()))
    state.engine.dispose()
    prepared = restore.prepare(path, data_dir / ".r")
    assert "celles du serveur sont conservées" in restore.summary(prepared)
    restore.swap(data_dir, data_dir / ".r", "x")
    assert len(list((data_dir / "uploads").iterdir())) == 1


def test_damaged_file_is_refused(archive, tmp_path):
    def corrupt(info, data):
        if info.name.startswith("uploads/") and info.isreg():
            data = b"X" + data[1:]
        return [(info, data)]

    bad = rewrite(archive, tmp_path / "abimee.tar", corrupt)
    with pytest.raises(RestoreError, match="abîmé"):
        restore.prepare(bad, tmp_path / "staging")
    assert not (tmp_path / "staging").exists()  # rien ne reste


def test_truncated_archive_is_refused(archive, tmp_path):
    data = archive.read_bytes()
    for cut in (len(data) // 2, len(data) - 12 * 1024):  # au milieu ; juste avant le manifeste
        bad = tmp_path / f"tronquee-{cut}.tar"
        bad.write_bytes(data[:cut])
        with pytest.raises(RestoreError, match=r"tronquée|incomplète|abîmée"):
            restore.prepare(bad, tmp_path / "staging")
        assert not (tmp_path / "staging").exists()


@pytest.mark.parametrize("name", ["../evil", "/etc/passwd", "uploads/../../x", "autre.txt", "uploads/a/b"])
def test_unexpected_members_are_refused(archive, tmp_path, name):
    def add(info, data):
        result = [(info, data)]
        if info.name == "organizer.db":
            extra = tarfile.TarInfo(name)
            extra.size = 1
            result.append((extra, b"x"))
        return result

    bad = rewrite(archive, tmp_path / "piege.tar", add)
    with pytest.raises(RestoreError, match="inattendu"):
        restore.prepare(bad, tmp_path / "staging")


def test_symlink_is_refused(archive, tmp_path):
    def link(info, data):
        if info.name.startswith("uploads/") and info.isreg():
            info.type, info.linkname, info.size = tarfile.SYMTYPE, "/etc/passwd", 0
            return [(info, None)]
        return [(info, data)]

    with pytest.raises(RestoreError, match="fichier ordinaire"):
        restore.prepare(rewrite(archive, tmp_path / "lien.tar", link), tmp_path / "staging")


def test_not_an_organizer_archive(tmp_path):
    other = tmp_path / "autre.tar"
    with tarfile.open(other, "w") as tar:
        info = tarfile.TarInfo(MANIFEST_NAME)
        info.size = 2
        tar.addfile(info, io.BytesIO(b"{}"))
    with pytest.raises(RestoreError, match="pas une sauvegarde d'Organizer"):
        restore.prepare(other, tmp_path / "staging")
    (tmp_path / "texte.tar").write_text("bonjour")
    with pytest.raises(RestoreError):
        restore.prepare(tmp_path / "texte.tar", tmp_path / "staging")


def edit_manifest(archive: Path, target: Path, **changes) -> Path:
    def change(info, data):
        if info.name == MANIFEST_NAME:
            data = json.dumps({**json.loads(data), **changes}).encode()
            info.size = len(data)
        return [(info, data)]

    return rewrite(archive, target, change)


def test_newer_version_needs_force(archive, tmp_path, capsys):
    newer = edit_manifest(archive, tmp_path / "recente.tar", version="99.0.0")
    staging = tmp_path / "staging"
    assert restore.main(["prepare", "--staging", str(staging), str(newer)]) == restore.EXIT_NEWER
    assert "mettez d'abord le serveur à jour" in capsys.readouterr().err and not staging.exists()
    assert restore.main(["prepare", "--force", "--staging", str(staging), str(newer)]) == 0
    assert "version plus récente" in capsys.readouterr().out
    future = edit_manifest(archive, tmp_path / "format.tar", format_version=2)
    with pytest.raises(RestoreError, match="Format de sauvegarde plus récent"):
        restore.prepare(future, tmp_path / "s2")


def test_command_line_errors(tmp_path, capsys):
    assert restore.main(["prepare", "--staging", str(tmp_path / "s"), str(tmp_path / "absente.tar")]) == 1
    assert "introuvable" in capsys.readouterr().err
    assert (
        restore.main(["swap", "--data-dir", str(tmp_path), "--staging", str(tmp_path / "s"), "--stamp", "x"])
        == 1
    )
    assert "Rien à restaurer" in capsys.readouterr().err


# --- deploy/restore.sh ------------------------------------------------------------------------------------


def fake_systemctl(folder: Path) -> Path:
    """Faux systemctl (et sudo) qui notent leurs appels dans ``calls.log``."""
    folder.mkdir()
    log = folder / "calls.log"
    (folder / "systemctl").write_text(f'#!/bin/sh\necho "systemctl $*" >> "{log}"\n')
    (folder / "sudo").write_text('#!/bin/sh\n[ "$1" = "--" ] && shift\nexec "$@"\n')
    for f in ("systemctl", "sudo"):
        (folder / f).chmod(0o755)
    return log


def run_script(*args: str, stdin: bytes | None = None, path_prefix: Path | None = None, **env: str):
    clean = {k: v for k, v in os.environ.items() if k not in ("SUDO_USER", "ORG_EUID")}
    if path_prefix is not None:
        clean["PATH"] = f"{path_prefix}:{clean['PATH']}"
    return subprocess.run(
        ["bash", str(ROOT / "deploy" / "restore.sh"), *args],
        input=stdin,
        capture_output=True,
        env={**clean, **env},
        cwd=ROOT,
        check=False,
    )


pytestmark_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="bash requis")


@pytestmark_bash
def test_script_without_service(state, alice, archive, data_dir):
    later_changes(state, alice)
    state.engine.dispose()
    result = run_script("--yes", "--no-service", "--data-dir", str(data_dir), str(archive))
    out = result.stdout.decode()
    assert result.returncode == 0, result.stderr.decode()
    assert "📅 Sauvegarde du" in out and "1 tâche(s)" in out and "Restauration terminée" in out
    assert titles(data_dir) == ["Avant"]
    (aside,) = data_dir.glob("avant-restauration-*")
    assert (aside / "organizer.db").exists()
    assert not list(data_dir.glob(".restauration-*"))


@pytestmark_bash
def test_script_needs_yes_without_terminal(archive, data_dir, state):
    result = run_script("--no-service", "--data-dir", str(data_dir), "-", stdin=archive.read_bytes())
    assert result.returncode != 0 and "--yes" in result.stderr.decode()


@pytestmark_bash
def test_script_from_stdin_with_service(state, alice, archive, data_dir, tmp_path):
    """``borg export-tar … - | deploy/restore.sh -`` : arrêt du service, échange, redémarrage, vérification
    (ici le faux service ne répond pas : le script le signale et dit comment revenir en arrière)."""
    later_changes(state, alice)
    state.engine.dispose()
    log = fake_systemctl(tmp_path / "bin")
    result = run_script(
        "--yes",
        "--data-dir",
        str(data_dir),
        "-",
        stdin=archive.read_bytes(),
        path_prefix=tmp_path / "bin",
        ORG_WAIT_TRIES="1",
        ORGANIZER_PORT="2690",
    )
    out = result.stdout.decode()
    assert result.returncode == 1 and "Le serveur ne répond pas" in out and "LISEZMOI.txt" in out
    assert log.read_text().splitlines() == ["systemctl stop organizer", "systemctl start organizer"]
    assert titles(data_dir) == ["Avant"]


@pytestmark_bash
def test_script_refuses_damaged_archive_without_touching_anything(state, alice, archive, data_dir, tmp_path):
    later_changes(state, alice)
    state.engine.dispose()
    log = fake_systemctl(tmp_path / "bin")
    data = bytearray(archive.read_bytes())
    data[len(data) // 2] ^= 0xFF  # un octet abîmé
    bad = tmp_path / "abimee.tar"
    bad.write_bytes(bytes(data))
    result = run_script("--yes", "--data-dir", str(data_dir), str(bad), path_prefix=tmp_path / "bin")
    assert result.returncode != 0 and "rien n'a été modifié" in result.stderr.decode()
    assert not log.exists()  # service jamais arrêté
    assert titles(data_dir) == ["Après", "Avant"]
    assert not list(data_dir.glob(".restauration-*")) and not list(data_dir.glob("avant-restauration-*"))
