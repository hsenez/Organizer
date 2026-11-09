"""Moteur SQLite et création du schéma."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, event
from sqlmodel import create_engine

from organizer.core import models  # noqa: F401  (enregistre les tables)


def make_engine(db_path: Path | str) -> Engine:
    """Crée le moteur SQLite (clés étrangères actives, journal WAL pour les accès concurrents)."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - trivial
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.close()

    return engine


def init_db(engine: Engine) -> int:
    """Base prête à l'emploi : créée au dernier schéma si elle est neuve, sinon mise à jour par les
    migrations (voir :mod:`organizer.core.migrations`). Renvoie le numéro de schéma."""
    from organizer.core.migrations import migrate

    return migrate(engine)
