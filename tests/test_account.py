"""Service de compte : profil, mot de passe, appareils, administration."""

from __future__ import annotations

import pytest

from organizer.config import Settings
from organizer.core.errors import Forbidden, InvalidOperation
from organizer.core.schemas import AdminUserPatch, PasswordChange, ProfilePatch, UserCreateIn
from organizer.core.services.account import AccountService
from organizer.core.services.auth import AuthService


@pytest.fixture
def auth(engine, tmp_path):
    return AuthService(engine, Settings(data_dir=tmp_path))


def account_for(users, auth, user_id):
    token, session = auth.create_session(user_id)
    return AccountService(users, auth, user_id, session.id), token


def test_profile_and_password(alice, users, auth):
    account, current = account_for(users, auth, alice.actor.id)
    other, _ = auth.create_session(alice.actor.id)
    updated = account.update_profile(ProfilePatch(display_name="Alice B.", theme="dark"))
    assert (updated.display_name, updated.theme) == ("Alice B.", "dark")
    account.change_password(PasswordChange(old_password="motdepasse", new_password="nouveau-mdp"))
    assert auth.resolve(current) is not None  # appareil courant conservé
    assert auth.resolve(other) is None  # les autres sont déconnectés
    with pytest.raises(InvalidOperation):
        account.change_password(PasswordChange(old_password="faux", new_password="encore-un"))


def test_sessions(alice, users, auth):
    account, _ = account_for(users, auth, alice.actor.id)
    auth.create_session(alice.actor.id, label="Téléphone")
    sessions = account.sessions()
    assert len(sessions) == 2 and sum(s.current for s in sessions) == 1
    assert account.revoke_other_sessions() == 1
    assert [s.current for s in account.sessions()] == [True]


def test_admin_operations(alice, bob, users, auth):
    admin, _ = account_for(users, auth, alice.actor.id)
    plain, _ = account_for(users, auth, bob.actor.id)
    with pytest.raises(Forbidden):
        plain.all_users()
    with pytest.raises(Forbidden):
        plain.create_user(UserCreateIn(username="carol", password="motdepasse"))
    carol = admin.create_user(UserCreateIn(username="carol", password="motdepasse", display_name="Carol"))
    assert {u.username for u in admin.all_users()} == {"alice", "bob", "carol"}
    carol_token, _ = auth.create_session(carol.id)
    admin.admin_update(carol.id, AdminUserPatch(is_active=False))
    assert auth.resolve(carol_token) is None
    with pytest.raises(InvalidOperation):
        admin.admin_update(alice.actor.id, AdminUserPatch(is_admin=False))
