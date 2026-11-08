"""Comptes utilisateurs."""

from __future__ import annotations

import pytest

from organizer.core.errors import Forbidden, InvalidOperation
from organizer.core.schemas import AdminUserPatch, PasswordChange
from organizer.core.services import users as users_module
from organizer.core.services.users import WEAK_PASSWORD_PREF


def test_first_user_is_admin_and_others_need_admin(users):
    first = users.create_user("alice", "motdepasse-12")
    assert first.is_admin
    with pytest.raises(Forbidden):
        users.create_user("bob", "motdepasse-12")
    bob = users.create_user("bob", "motdepasse-12", by=users.actor_for(first.id))
    assert not bob.is_admin
    with pytest.raises(Forbidden):
        users.create_user("carol", "motdepasse-12", by=users.actor_for(bob.id))


def test_username_unique_case_insensitive(users):
    users.create_user("alice", "motdepasse-12")
    admin = users.actor_for(1)
    with pytest.raises(InvalidOperation):
        users.create_user("ALICE", "motdepasse-12", by=admin)


def test_password_rules_and_authentication(users):
    with pytest.raises(InvalidOperation):
        users.create_user("alice", "court")
    users.create_user("alice", "motdepasse-12")
    assert users.authenticate("Alice", "motdepasse-12") is not None
    assert users.authenticate("alice", "mauvais") is None
    assert users.authenticate("inconnu", "motdepasse-12") is None


def test_new_passwords_need_12_characters(users):
    with pytest.raises(InvalidOperation, match="12 caractères"):
        users.create_user("alice", "onze-caract")
    alice = users.create_user("alice", "douze-caract")
    with pytest.raises(InvalidOperation, match="12 caractères"):
        users.change_password(alice.id, PasswordChange(old_password="douze-caract", new_password="court"))
    with pytest.raises(InvalidOperation, match="12 caractères"):
        users.admin_update(users.actor_for(alice.id), alice.id, AdminUserPatch(new_password="court"))


def test_short_legacy_password_still_works_but_is_flagged_until_changed(users, monkeypatch):
    monkeypatch.setattr(users_module, "MIN_PASSWORD_LENGTH", 6)  # comptes créés avant le passage à 12
    alice = users.create_user("alice", "ancien")
    bob = users.create_user("bob", "ancien", by=users.actor_for(alice.id))
    monkeypatch.undo()

    assert users.authenticate("alice", "ancien") is not None
    assert users.get_pref(alice.id, WEAK_PASSWORD_PREF) is True
    users.change_password(alice.id, PasswordChange(old_password="ancien", new_password="nouveau-long-1"))
    assert users.get_pref(alice.id, WEAK_PASSWORD_PREF) is None

    users.authenticate("bob", "ancien")
    users.admin_update(users.actor_for(alice.id), bob.id, AdminUserPatch(new_password="reinitialise-1"))
    assert users.get_pref(bob.id, WEAK_PASSWORD_PREF) is None
    assert users.authenticate("bob", "reinitialise-1") is not None
    assert users.get_pref(bob.id, WEAK_PASSWORD_PREF) is None  # mot de passe assez long : pas de marque
