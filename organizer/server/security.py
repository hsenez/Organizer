"""Authentification des requêtes HTTP : cookie (navigateur) ou en-tête ``Authorization: Bearer`` (client
bureau). Le middleware résout la session une fois par requête et la place dans ``request.state.auth``."""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from organizer.config import Settings
from organizer.core.services.auth import ResolvedSession

COOKIE_NAME = "organizer_session"
# Ressources internes de NiceGUI et fichiers statiques : pas besoin d'authentification.
_SKIPPED_PREFIXES = ("/_nicegui", "/static", "/favicon")


def set_session_cookie(response: Response, token: str, persistent: bool, settings: Settings) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.remember_me_days * 86400 if persistent else None,
        httponly=True,
        samesite="lax",
        secure=False,  # HTTP simple sur le réseau local (pas de HTTPS en v1)
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def extract_token(request: Request) -> tuple[str | None, str | None]:
    """(jeton, source) avec source = "bearer" | "cookie" | None."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None, "bearer"
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie:
        return cookie, "cookie"
    return None, None


def request_auth(request: Request) -> ResolvedSession | None:
    return getattr(request.state, "auth", None)


def describe_user_agent(user_agent: str) -> str:
    """« Firefox · Linux » à partir d'un User-Agent (pour la liste des appareils connectés)."""
    ua = user_agent.lower()
    browser = next(
        (
            name
            for key, name in (
                ("edg/", "Edge"),
                ("firefox", "Firefox"),
                ("chrome", "Chrome"),
                ("safari", "Safari"),
            )
            if key in ua
        ),
        "Navigateur",
    )
    system = next(
        (
            name
            for key, name in (
                ("android", "Android"),
                ("iphone", "iPhone"),
                ("ipad", "iPad"),
                ("windows", "Windows"),
                ("mac os", "macOS"),
                ("linux", "Linux"),
            )
            if key in ua
        ),
        "",
    )
    return f"{browser} · {system}" if system else browser


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request.state.auth = None
        request.state.auth_token = None
        token, source = (None, None)
        resolved: ResolvedSession | None = None
        if not request.url.path.startswith(_SKIPPED_PREFIXES):
            token, source = extract_token(request)
            if token:
                state = request.app.state.organizer
                resolved = await run_in_threadpool(state.auth.resolve, token)
                request.state.auth = resolved
                request.state.auth_token = token if resolved else None

        response = await call_next(request)

        sets_cookie = any(h.startswith(f"{COOKIE_NAME}=") for h in response.headers.getlist("set-cookie"))
        if source == "cookie" and not sets_cookie:
            if resolved is None:
                clear_session_cookie(response)  # cookie expiré ou révoqué : on le nettoie
            elif resolved.renewed and resolved.session.persistent:
                set_session_cookie(response, token, True, request.app.state.organizer.settings)
        return response
