"""Comptes utilisateurs."""

from __future__ import annotations

import pytest

from organizer.core.errors import Forbidden, InvalidOperation


def test_first_user_is_admin_and_others_need_admin(users):
    first = users.create_user("alice", "motdepasse")
    assert first.is_admin
    with pytest.raises(Forbidden):
        users.create_user("bob", "motdepasse")
    bob = users.create_user("bob", "motdepasse", by=users.actor_for(first.id))
    assert not bob.is_admin
    with pytest.raises(Forbidden):
        users.create_user("carol", "motdepasse", by=users.actor_for(bob.id))


def test_username_unique_case_insensitive(users):
    users.create_user("alice", "motdepasse")
    admin = users.actor_for(1)
    with pytest.raises(InvalidOperation):
        users.create_user("ALICE", "motdepasse", by=admin)


def test_password_rules_and_authentication(users):
    with pytest.raises(InvalidOperation):
        users.create_user("alice", "court")
    users.create_user("alice", "motdepasse")
    assert users.authenticate("Alice", "motdepasse") is not None
    assert users.authenticate("alice", "mauvais") is None
    assert users.authenticate("inconnu", "motdepasse") is None
