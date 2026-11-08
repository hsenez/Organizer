"""Fixtures communes : base SQLite temporaire, deux utilisateurs (Alice admin, Bob), date du jour figée."""

from __future__ import annotations

from datetime import date

import pytest

from organizer.config import Settings
from organizer.core.db import init_db, make_engine
from organizer.core.services import Services, UserService

# Mercredi 4 novembre 2026 : laisse « demain » (jeudi) et « cette semaine » (vendredi → dimanche) distincts.
TODAY = date(2026, 11, 4)


class Clock:
    """Date du jour modifiable pendant un test."""

    def __init__(self, today: date):
        self.value = today

    def __call__(self) -> date:
        return self.value


@pytest.fixture
def clock() -> Clock:
    return Clock(TODAY)


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(tmp_path / "test.db")
    init_db(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def settings(tmp_path) -> Settings:
    # Fenêtre de fusion à 0 s par défaut : chaque action est une entrée distincte de l'historique.
    return Settings(data_dir=tmp_path, undo_merge_window_seconds=0.0)


@pytest.fixture
def users(engine) -> UserService:
    return UserService(engine)


@pytest.fixture
def alice(engine, users, settings, clock) -> Services:
    user = users.create_user("alice", "motdepasse-12", "Alice")
    return Services.for_user(engine, user.id, settings=settings, today=clock)


@pytest.fixture
def bob(engine, users, alice, settings, clock) -> Services:
    user = users.create_user("bob", "motdepasse-12", "Bob", by=alice.actor)
    return Services.for_user(engine, user.id, settings=settings, today=clock)
