"""Migrations du schéma de la base : base neuve, base de la version 0.9.0 (fichier créé par le vrai code de
cette version), étape à venir simulée, échec d'une étape, base trop récente."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from organizer.config import Settings
from organizer.core import migrations
from organizer.core.db import init_db, make_engine
from organizer.core.migrations import SCHEMA_VERSION, Migration, SchemaTooNew, add_column, table_columns
from organizer.core.schemas import TaskCreate
from organizer.server.state import create_state
from organizer.server.wiring import create_api_app

OLD_DB = Path(__file__).parent / "fixtures" / "organizer-0.9.0.db"


def user_version(path: Path) -> int:
    con = sqlite3.connect(path)
    try:
        return con.execute("PRAGMA user_version").fetchone()[0]
    finally:
        con.close()


@pytest.fixture
def old_copy(tmp_path) -> Path:
    """Copie de la base 0.9.0 (le fichier de référence ne doit jamais être modifié)."""
    data = tmp_path / "data"
    data.mkdir()
    target = data / "organizer.db"
    shutil.copy(OLD_DB, target)
    return target


@pytest.fixture
def fresh_schema(tmp_path):
    engine = make_engine(tmp_path / "neuve" / "organizer.db")
    init_db(engine)
    yield table_columns(engine)
    engine.dispose()


def test_fresh_database_starts_at_the_latest_schema(tmp_path):
    engine = make_engine(tmp_path / "organizer.db")
    assert init_db(engine) == SCHEMA_VERSION
    engine.dispose()
    assert user_version(tmp_path / "organizer.db") == SCHEMA_VERSION


def test_old_database_reaches_the_current_schema(old_copy, fresh_schema):
    """Une base de la version 0.9.0 arrive **exactement** au schéma d'une base neuve, données intactes."""
    assert user_version(old_copy) == 0
    engine = make_engine(old_copy)
    assert init_db(engine) == SCHEMA_VERSION
    assert table_columns(engine) == fresh_schema
    engine.dispose()
    assert user_version(old_copy) == SCHEMA_VERSION


def test_old_database_works_with_the_current_code(old_copy):
    """Avec le code actuel : connexion, tâches, partage, sous-tâches, pièces jointes, historique."""
    state = create_state(Settings(data_dir=old_copy.parent))
    try:
        alice, bob = state.users.list()
        assert (alice.username, bob.username) == ("alice", "bob")
        assert state.users.authenticate("alice", "motdepasse-12").id == alice.id
        a, b = state.services_for(alice), state.services_for(bob)
        titles = sorted(t.title for t in a.tasks.list())
        assert "Réparer la fuite" in titles and "Relancer l'assurance" in titles
        fuite = next(t for t in a.tasks.list() if t.title == "Réparer la fuite")
        assert [s.title for s in a.tasks.subtasks(fuite.id)] == ["Acheter un joint"]
        assert {link.kind.value for link in fuite.links} == {"url", "attachment"}
        assert [t.title for t in b.tasks.list() if t.id == fuite.id] == ["Réparer la fuite"]  # partagée
        assert [bd.name for bd in a.boards.list()] == ["Travaux"]
        assert state.users.get_pref(alice.id, "view:tasks") == {"sort": {"key": "urgency"}}
        # On continue à travailler dessus, y compris annuler.
        created = a.tasks.create(TaskCreate(title="Après la mise à jour"))
        a.undo.undo()
        assert all(t.id != created.id for t in a.tasks.list())
        # Et par l'API (jeton créé après coup).
        token = state.auth.create_session(alice.id, kind="api")[0]
        client = TestClient(create_api_app(state), headers={"Authorization": f"Bearer {token}"})
        assert client.get("/api/v1/auth/me").json()["username"] == "alice"
    finally:
        state.engine.dispose()


def test_no_backup_copy_for_the_baseline(old_copy):
    engine = make_engine(old_copy)
    init_db(engine)
    engine.dispose()
    assert not list(old_copy.parent.glob("*avant-migration*"))  # l'étape 1 ne touche à rien


def _future_step(conn) -> None:
    add_column(conn, "task", "start_date", "DATE")


def test_future_step_adds_a_column_once_with_a_backup(old_copy):
    """Simule une évolution à venir (ex. date de début) : appliquée une fois, copie de sécurité avant."""
    steps = [*migrations.MIGRATIONS, Migration(SCHEMA_VERSION + 1, "Date de début des tâches", _future_step)]
    engine = make_engine(old_copy)
    assert migrations.migrate(engine, steps) == SCHEMA_VERSION + 1
    with engine.connect() as conn:
        columns = {row[1] for row in conn.exec_driver_sql('PRAGMA table_info("task")')}
        assert "start_date" in columns
        assert conn.execute(text("SELECT COUNT(*) FROM task")).scalar() == 4  # données gardées
    (backup,) = old_copy.parent.glob("organizer.db.avant-migration-v0-*")
    assert user_version(backup) == 0  # l'état d'avant, intact
    # Deuxième démarrage : rien à refaire, pas de nouvelle copie.
    assert migrations.migrate(engine, steps) == SCHEMA_VERSION + 1
    assert len(list(old_copy.parent.glob("*avant-migration*"))) == 1
    engine.dispose()


def test_failed_step_is_rolled_back(old_copy):
    def broken(conn) -> None:
        add_column(conn, "task", "start_date", "DATE")
        raise RuntimeError("étape défectueuse")

    steps = [*migrations.MIGRATIONS, Migration(SCHEMA_VERSION + 1, "Étape défectueuse", broken)]
    engine = make_engine(old_copy)
    with pytest.raises(RuntimeError, match="défectueuse"):
        migrations.migrate(engine, steps)
    with engine.connect() as conn:
        columns = {row[1] for row in conn.exec_driver_sql('PRAGMA table_info("task")')}
        assert "start_date" not in columns  # annulée, colonne comprise
        assert migrations.schema_version(conn) == SCHEMA_VERSION  # étapes précédentes, elles, appliquées
    engine.dispose()


def test_database_from_a_newer_version_is_refused(old_copy):
    con = sqlite3.connect(old_copy)
    con.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 5}")
    con.close()
    with pytest.raises(SchemaTooNew, match="mettez Organizer à jour"):
        create_state(Settings(data_dir=old_copy.parent))
    assert user_version(old_copy) == SCHEMA_VERSION + 5  # rien touché


def test_add_column_is_idempotent(tmp_path):
    engine = make_engine(tmp_path / "organizer.db")
    init_db(engine)
    with engine.begin() as conn:
        add_column(conn, "task", "start_date", "DATE")
        add_column(conn, "task", "start_date", "DATE")
        add_column(conn, "task", "position", "REAL")  # existe déjà : rien
    engine.dispose()


def test_backup_manifest_records_the_schema_version(tmp_path):
    import io
    import json
    import tarfile

    from organizer.server.backup import BackupArchive

    state = create_state(Settings(data_dir=tmp_path / "data"))
    try:
        state.users.create_user("alice", "motdepasse-12", "Alice")
        data = b"".join(BackupArchive(state.settings).chunks())
    finally:
        state.engine.dispose()
    manifest = json.loads(tarfile.open(fileobj=io.BytesIO(data)).extractfile("manifest.json").read())
    assert manifest["schema_version"] == SCHEMA_VERSION and "_schema" not in manifest["counts"]
