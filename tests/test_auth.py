"""Sessions glissantes, anti force brute, tickets de connexion."""

from __future__ import annotations

from datetime import timedelta

from sqlmodel import Session, select

from organizer.config import Settings
from organizer.core.models import AuthSession, utcnow
from organizer.core.services.auth import AuthService, LoginBlock, LoginThrottle, hash_token
from organizer.server.state import TicketStore


def _age_session(
    engine, token: str, *, last_seen: timedelta | None = None, expires_in: timedelta | None = None
):
    with Session(engine) as s:
        row = s.exec(select(AuthSession).where(AuthSession.token_hash == hash_token(token))).one()
        if last_seen is not None:
            row.last_seen_at = utcnow() - last_seen
        if expires_in is not None:
            row.expires_at = utcnow() + expires_in
        s.add(row)
        s.commit()


def test_token_is_stored_hashed(engine, users, tmp_path):
    user = users.create_user("alice", "motdepasse-12")
    auth = AuthService(engine, Settings(data_dir=tmp_path))
    token, _ = auth.create_session(user.id)
    with Session(engine) as s:
        stored = s.exec(select(AuthSession.token_hash)).all()
    assert token not in stored and hash_token(token) in stored


def test_sliding_expiration(engine, users, tmp_path):
    user = users.create_user("alice", "motdepasse-12")
    auth = AuthService(engine, Settings(data_dir=tmp_path, remember_me_days=30))
    token, created = auth.create_session(user.id, persistent=True)
    first = auth.resolve(token)
    assert first is not None and not first.renewed  # utilisée à l'instant : pas de réécriture
    _age_session(engine, token, last_seen=timedelta(days=20), expires_in=timedelta(days=10))
    renewed = auth.resolve(token)
    assert renewed.renewed
    assert renewed.session.expires_at > created.expires_at - timedelta(minutes=1)


def test_expired_and_disabled(engine, users, tmp_path):
    user = users.create_user("alice", "motdepasse-12")
    auth = AuthService(engine, Settings(data_dir=tmp_path))
    token, _ = auth.create_session(user.id)
    _age_session(engine, token, expires_in=timedelta(seconds=-1))
    assert auth.resolve(token) is None
    assert auth.list_sessions(user.id) == []
    assert auth.resolve(None) is None and auth.resolve("") is None


def test_web_session_durations(engine, users, tmp_path):
    user = users.create_user("alice", "motdepasse-12")
    auth = AuthService(engine, Settings(data_dir=tmp_path, web_session_hours=24, api_token_days=90))
    _, web = auth.create_session(user.id, kind="web", persistent=False)
    _, api = auth.create_session(user.id, kind="api")
    assert timedelta(hours=23) < web.expires_at - web.created_at <= timedelta(hours=24)
    assert api.persistent and api.expires_at - api.created_at == timedelta(days=90)


def test_revoke_only_own_sessions(engine, users, tmp_path):
    alice = users.create_user("alice", "motdepasse-12")
    bob = users.create_user("bob", "motdepasse-12", by=users.actor_for(alice.id))
    auth = AuthService(engine, Settings(data_dir=tmp_path))
    _, bob_session = auth.create_session(bob.id)
    try:
        auth.revoke(alice.id, bob_session.id)
        raise AssertionError("Alice ne doit pas pouvoir révoquer la session de Bob")
    except Exception as exc:  # NotFound
        assert "introuvable" in str(exc)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_throttle_blocks_then_releases():
    clock = FakeClock()
    throttle = LoginThrottle(max_failures=3, window_seconds=600, clock=clock)
    for _ in range(3):
        assert throttle.retry_after("1.2.3.4", "alice") == 0
        throttle.failure("1.2.3.4", "Alice")
    assert throttle.retry_after("1.2.3.4", "alice") == 600
    assert throttle.retry_after("5.6.7.8", "alice") == 0  # autre adresse : non bloquée
    clock.now += 601
    assert throttle.retry_after("1.2.3.4", "alice") == 0


def test_throttle_success_resets():
    throttle = LoginThrottle(max_failures=2, window_seconds=600, clock=FakeClock())
    throttle.failure("ip", "alice")
    throttle.success("ip", "alice")
    throttle.failure("ip", "alice")
    assert throttle.retry_after("ip", "alice") == 0


def test_throttle_account_level_across_addresses():
    clock = FakeClock()
    throttle = LoginThrottle(
        max_failures=3, window_seconds=600, account_max_failures=5, account_window_seconds=3600, clock=clock
    )
    for i in range(5):
        assert throttle.block(f"10.0.0.{i}", "alice") is None
        throttle.failure(f"10.0.0.{i}", "alice")
        clock.now += 60
    # Toute nouvelle adresse est refusée pour ce compte, jusqu'à ce que le 1er échec sorte de la fenêtre.
    assert throttle.block("10.9.9.9", "ALICE ") == LoginBlock(3600 - 300, "account")
    assert throttle.block("10.9.9.9", "bob") is None  # les autres comptes ne sont pas touchés
    clock.now += 3600 - 300 + 1
    assert throttle.block("10.9.9.9", "alice") is None


def test_throttle_success_does_not_reset_account_level():
    throttle = LoginThrottle(2, 600, account_max_failures=3, account_window_seconds=3600, clock=FakeClock())
    throttle.failure("1.1.1.1", "alice")
    throttle.failure("2.2.2.2", "alice")
    throttle.success("3.3.3.3", "alice")  # le propriétaire se connecte depuis chez lui
    throttle.failure("4.4.4.4", "alice")
    assert throttle.block("5.5.5.5", "alice").scope == "account"


def test_throttle_reports_longest_block():
    clock = FakeClock()
    throttle = LoginThrottle(2, 600, account_max_failures=2, account_window_seconds=3600, clock=clock)
    throttle.failure("ip", "alice")
    throttle.failure("ip", "alice")
    assert throttle.block("ip", "alice") == LoginBlock(3600, "account")


def test_throttle_account_level_disabled_by_default():
    throttle = LoginThrottle(max_failures=2, window_seconds=600, clock=FakeClock())
    for i in range(50):
        throttle.failure(f"10.0.{i}.1", "alice")
    assert throttle.block("10.9.9.9", "alice") is None


def test_throttle_purges_expired_entries():
    clock = FakeClock()
    throttle = LoginThrottle(2, 600, account_max_failures=20, account_window_seconds=3600, clock=clock)
    throttle.MAX_KEYS = 10
    for i in range(10):
        throttle.failure("ip", f"inventé{i}")
    clock.now += 3601
    throttle.failure("ip", "alice")
    assert len(throttle._failures) == 2  # seules restent les entrées d'alice (adresse + compte)


def test_tickets_single_use_and_expire():
    clock = FakeClock()
    store = TicketStore(clock=clock)
    ticket = store.issue(1, persistent=True)
    assert store.redeem(ticket).user_id == 1
    assert store.redeem(ticket) is None
    late = store.issue(1, persistent=False)
    clock.now += TicketStore.TTL + 1
    assert store.redeem(late) is None
