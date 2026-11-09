"""Évolutions du schéma de la base (« migrations »), appliquées automatiquement au démarrage du serveur.

Pourquoi : ``create_all`` crée les tables qui manquent, mais ne modifie jamais une table existante (ajouter
une colonne, par exemple). Pour faire évoluer une base qui contient déjà des données, chaque changement est
décrit ici, une fois pour toutes, et appliqué dans l'ordre aux bases qui ne l'ont pas encore.

- **Numéro de version du schéma** : dans l'en-tête de la base SQLite (``PRAGMA user_version``) ; il voyage
  donc avec la base (sauvegardes, restaurations). 0 = base antérieure à ce mécanisme.
- **Base neuve** : créée directement au dernier schéma (``create_all``), numéro = :data:`SCHEMA_VERSION`.
- **Base existante en retard** : copie de sécurité (si une étape touche aux données), puis chaque étape dans
  **sa propre transaction** avec la mise à jour du numéro : une étape qui échoue est annulée entièrement, le
  serveur ne démarre pas, la base reste dans l'état de l'étape précédente.
- **Base plus récente** que ce code (version d'Organizer plus ancienne que celle qui l'a modifiée) :
  refusée, pour ne pas l'abîmer.

Ajouter une étape (quand un modèle de ``models.py`` gagne une colonne, par exemple) :

1. modifier le modèle (les bases neuves l'auront directement) ;
2. ajouter à la fin de :data:`MIGRATIONS` une :class:`Migration` de numéro suivant, dont la fonction fait le
   même changement sur une base existante (ex. :func:`add_column`) ; ne jamais modifier une étape publiée.
   Une étape doit tolérer une table **déjà au dernier schéma** : les tables apparues entre-temps sont créées
   complètes par ``create_all`` avant les étapes ;
3. le test ``test_old_database_reaches_the_current_schema`` vérifie qu'une base de la version 0.9.0 (fichier
   ``tests/fixtures/organizer-0.9.0.db``) arrive exactement au schéma d'une base neuve.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import Connection, Engine, create_engine, event, inspect, text
from sqlmodel import SQLModel

log = logging.getLogger("organizer.db")


@dataclass(frozen=True)
class Migration:
    version: int  # numéro du schéma **après** cette étape
    description: str
    apply: Callable[[Connection], None]
    changes_data: bool = True  # copie de sécurité de la base avant de l'appliquer


class SchemaTooNew(RuntimeError):
    """La base a été modifiée par une version plus récente d'Organizer."""


def add_column(conn: Connection, table: str, column: str, definition: str) -> None:
    """Ajoute une colonne si elle n'existe pas déjà. ``definition`` : type et valeur par défaut SQL, ex.
    ``"DATE"`` ou ``"INTEGER NOT NULL DEFAULT 0"`` (SQLite exige une valeur par défaut pour NOT NULL)."""
    existing = {row[1] for row in conn.exec_driver_sql(f'PRAGMA table_info("{table}")')}
    if column not in existing:
        conn.exec_driver_sql(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}')


def _baseline(_conn: Connection) -> None:
    """Version 1 : le schéma de la version 1.0.0, point de départ ; rien à modifier dans une base existante
    (toutes les évolutions jusque-là ont pris la forme de nouvelles tables, créées par ``create_all``)."""


MIGRATIONS: list[Migration] = [
    Migration(1, "Schéma de la version 1.0.0 (point de départ)", _baseline, changes_data=False),
]
SCHEMA_VERSION = MIGRATIONS[-1].version


def schema_version(conn: Connection) -> int:
    return int(conn.exec_driver_sql("PRAGMA user_version").scalar() or 0)


def _set_version(conn: Connection, version: int) -> None:
    conn.exec_driver_sql(f"PRAGMA user_version = {int(version)}")


def _database_path(engine: Engine) -> Path | None:
    database = engine.url.database
    return Path(database) if database and database != ":memory:" else None


def backup_before_migration(engine: Engine, current: int) -> Path | None:
    """Copie cohérente de la base à côté d'elle (``organizer.db.avant-migration-v<n>-<date>``)."""
    path = _database_path(engine)
    if path is None or not path.exists():
        return None
    target = path.with_name(f"{path.name}.avant-migration-v{current}-{datetime.now():%Y%m%d-%H%M%S}")
    source = sqlite3.connect(path)
    copy = sqlite3.connect(target)
    try:
        source.backup(copy)
    finally:
        copy.close()
        source.close()
    return target


def migrate(engine: Engine, migrations: list[Migration] | None = None) -> int:
    """Amène la base au dernier schéma ; renvoie le numéro de version atteint."""
    steps = MIGRATIONS if migrations is None else migrations
    latest = steps[-1].version if steps else 0
    with engine.connect() as conn:
        fresh = not inspect(conn).has_table("user")
        current = schema_version(conn)
    if fresh:
        SQLModel.metadata.create_all(engine)
        with engine.begin() as conn:
            _set_version(conn, latest)
        log.info("Base de données créée (schéma %d)", latest)
        return latest
    if current > latest:
        raise SchemaTooNew(
            f"La base de données est au schéma {current}, plus récent que celui de cette version d'Organizer "
            f"({latest}) : mettez Organizer à jour (deploy/update.sh) au lieu de revenir en arrière."
        )
    # Nouvelles tables d'abord (une étape peut s'en servir pour y recopier des données).
    SQLModel.metadata.create_all(engine)
    pending = [m for m in steps if m.version > current]
    if pending and any(m.changes_data for m in pending):
        saved = backup_before_migration(engine, current)
        if saved is not None:
            log.info("Copie de la base avant migration : %s", saved)
    if not pending:
        return current
    steps_engine = _transactional_engine(engine)
    try:
        for step in pending:
            with steps_engine.begin() as conn:  # une transaction par étape, structure (ALTER…) comprise
                step.apply(conn)
                _set_version(conn, step.version)
            log.info("Base de données : schéma %d → %d (%s)", current, step.version, step.description)
            current = step.version
    finally:
        steps_engine.dispose()
    return current


def _transactional_engine(engine: Engine) -> Engine:
    """Moteur réservé aux étapes de migration, dont les transactions englobent **aussi** les changements de
    structure. Le pilote ``sqlite3`` de Python n'ouvre de lui-même une transaction qu'avant une écriture de
    données : un ``ALTER TABLE`` était enregistré sur-le-champ et survivait à l'échec de l'étape (constaté
    par ``test_failed_step_is_rolled_back``). Recette de la documentation de SQLAlchemy : gestion
    automatique du pilote coupée, ``BEGIN`` émis par SQLAlchemy. Clés étrangères non vérifiées pendant
    les étapes (une reconstruction de table l'exige) : à l'étape de laisser des données cohérentes."""
    steps_engine = create_engine(engine.url, connect_args={"check_same_thread": False})

    @event.listens_for(steps_engine, "connect")
    def _no_driver_transactions(dbapi_connection, _record) -> None:  # pragma: no cover - trivial
        dbapi_connection.isolation_level = None

    @event.listens_for(steps_engine, "begin")
    def _begin(conn) -> None:  # pragma: no cover - trivial
        conn.exec_driver_sql("BEGIN")

    return steps_engine


def table_columns(engine: Engine) -> dict[str, list[tuple[str, str, bool]]]:
    """Description du schéma réel (table → colonnes : nom, type, NOT NULL) ; sert à comparer une base
    migrée à une base neuve."""
    with engine.connect() as conn:
        names = [
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
            )
        ]
        return {
            name: sorted(
                (row[1], str(row[2]).upper(), bool(row[3]))
                for row in conn.exec_driver_sql(f'PRAGMA table_info("{name}")')
            )
            for name in sorted(names)
        }
