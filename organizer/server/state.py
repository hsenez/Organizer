"""État global du serveur (une seule instance par processus)."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field

from sqlalchemy import Engine

from organizer.config import Settings
from organizer.core.db import init_db, make_engine
from organizer.core.events import EventBus
from organizer.core.schemas import UserOut
from organizer.core.services import AuthService, Services, UserService
from organizer.core.services.auth import LoginThrottle


@dataclass(frozen=True)
class LoginTicket:
    user_id: int
    persistent: bool
    label: str
    expires: float


class TicketStore:
    """Tickets de connexion à usage unique (60 s).

    La page de connexion vérifie le mot de passe côté serveur, puis redirige le navigateur vers
    ``/auth/complete?ticket=…`` : c'est cette réponse HTTP qui pose le cookie (HttpOnly, invisible du JS).
    """

    TTL = 60.0

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._tickets: dict[str, LoginTicket] = {}
        self._lock = threading.Lock()

    def issue(self, user_id: int, persistent: bool, label: str = "") -> str:
        ticket = secrets.token_urlsafe(24)
        with self._lock:
            now = self.clock()
            self._tickets = {k: v for k, v in self._tickets.items() if v.expires > now}
            self._tickets[ticket] = LoginTicket(user_id, persistent, label, now + self.TTL)
        return ticket

    def redeem(self, ticket: str) -> LoginTicket | None:
        with self._lock:
            data = self._tickets.pop(ticket, None)
        if data is None or data.expires <= self.clock():
            return None
        return data


@dataclass
class AppState:
    settings: Settings
    engine: Engine
    auth: AuthService
    users: UserService
    throttle: LoginThrottle
    tickets: TicketStore = field(default_factory=TicketStore)
    events: EventBus = field(default_factory=EventBus)

    def services_for(self, user: UserOut, origin: str | None = None) -> Services:
        """Services de ``user`` ; ``origin`` : page / appareil à l'origine des modifications."""
        return Services.for_user(
            self.engine, user.id, settings=self.settings, events=self.events, origin=origin
        )


def create_state(settings: Settings | None = None) -> AppState:
    settings = settings or Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    engine = make_engine(settings.db_path)
    init_db(engine)
    return AppState(
        settings=settings,
        engine=engine,
        auth=AuthService(engine, settings),
        users=UserService(engine),
        throttle=LoginThrottle(
            settings.login_max_failures,
            settings.login_failure_window_minutes * 60,
            settings.login_account_max_failures,
            settings.login_account_window_minutes * 60,
        ),
    )
