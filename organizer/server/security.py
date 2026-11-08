"""Sécurité des requêtes HTTP.

- Authentification : cookie (navigateur) ou en-tête ``Authorization: Bearer`` (client bureau). Le middleware
  résout la session une fois par requête et la place dans ``request.state.auth``.
- En-têtes de sécurité ajoutés à chaque réponse (``SecurityHeadersMiddleware``).

Derrière un proxy (Cloudflare Tunnel, Caddy, nginx…) installé **sur la même machine**, uvicorn remplace
l'adresse et le protocole de la connexion par ceux du visiteur d'après les en-têtes ``X-Forwarded-For`` /
``X-Forwarded-Proto`` (``ProxyHeadersMiddleware`` d'uvicorn, actif par défaut, qui ne croit que les
connexions venant de 127.0.0.1 / ::1). ``request.client.host`` et ``request.url.scheme`` sont donc ceux du
visiteur : c'est sur eux que s'appuient l'anti force brute et le cookie ``Secure``.
"""

from __future__ import annotations

import json
from urllib.parse import quote

from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from organizer.core.events import UNDO_HEADER
from organizer.core.services.auth import ResolvedSession

COOKIE_NAME = "organizer_session"
NOT_AUTHENTICATED = "Non connecté (ou session expirée)."
# Ressources internes de NiceGUI et fichiers statiques : pas besoin d'authentification.
_SKIPPED_PREFIXES = ("/_nicegui", "/static", "/favicon", "/icons", "/manifest.webmanifest", "/sw.js")


# HSTS : durée (secondes) pendant laquelle le navigateur refusera de contacter le site autrement qu'en HTTPS.
HSTS_MAX_AGE = 365 * 86400
# Ajoutés à toute réponse qui ne les fixe pas déjà elle-même (les pièces jointes ont leur propre politique).
SECURITY_HEADERS: tuple[tuple[str, str], ...] = (
    ("X-Content-Type-Options", "nosniff"),  # le navigateur respecte le type annoncé, sans deviner
    ("X-Frame-Options", "SAMEORIGIN"),  # interdit l'affichage dans un cadre d'un autre site
    ("Referrer-Policy", "same-origin"),  # nos adresses ne sont pas transmises aux sites externes
)


def is_https(request: Request) -> bool:
    """Vrai si le **visiteur** parle en HTTPS (au serveur lui-même ou au proxy placé devant)."""
    return request.url.scheme == "https"


def set_session_cookie(response: Response, request: Request, token: str, persistent: bool) -> None:
    settings = request.app.state.organizer.settings
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.remember_me_days * 86400 if persistent else None,
        httponly=True,
        samesite="lax",
        secure=is_https(request),  # en HTTPS, le navigateur ne renverra jamais ce cookie en clair
        path="/",
    )


def clear_session_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax", secure=is_https(request))


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


def is_api_docs(request: Request) -> bool:
    """Documentation de l'API publiée par FastAPI (``/docs``, ``/docs/oauth2-redirect``, ``/redoc``,
    ``/openapi.json``) : adresses lues sur l'application, qui les fixe (``ui.run(fastapi_docs=True)``)."""
    path = request.url.path
    app = request.app
    return any(
        url and (path == url or path.startswith(url + "/"))
        for url in (getattr(app, "docs_url", None), getattr(app, "redoc_url", None))
    ) or path == getattr(app, "openapi_url", None)


def docs_refusal(request: Request) -> Response:
    """Visiteur non connecté sur la documentation : page de connexion (puis retour), 401 pour le JSON."""
    if request.url.path == getattr(request.app, "openapi_url", None):
        return JSONResponse({"detail": NOT_AUTHENTICATED}, status_code=401)
    return RedirectResponse(f"/login?next={quote(request.url.path)}", status_code=303)


def is_api_write(request: Request) -> bool:
    return request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/")


async def add_undo_status(request: Request, response: Response, auth: ResolvedSession) -> None:
    """Écriture du client bureau : joint l'état « annuler / rétablir » à la réponse (il change à chaque
    écriture ; le client s'épargne ainsi une requête, soit ≈ 300 ms par clic à travers Internet)."""
    if response.status_code >= 500:
        return
    state = request.app.state.organizer
    status = await run_in_threadpool(lambda: state.services_for(auth.user).undo.status())
    response.headers[UNDO_HEADER] = json.dumps(status.model_dump(), ensure_ascii=True)


class AuthMiddleware(BaseHTTPMiddleware):
    """Résout la session ; refuse aussi la documentation de l'API aux visiteurs non connectés (elle décrit
    toutes les routes : inutile de la montrer à Internet)."""

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

        if resolved is None and is_api_docs(request):
            response = docs_refusal(request)
        else:
            response = await call_next(request)
            if source == "bearer" and resolved is not None and is_api_write(request):
                await add_undo_status(request, response, resolved)

        sets_cookie = any(h.startswith(f"{COOKIE_NAME}=") for h in response.headers.getlist("set-cookie"))
        if source == "cookie" and not sets_cookie:
            if resolved is None:
                clear_session_cookie(response, request)  # cookie expiré ou révoqué : on le nettoie
            elif resolved.renewed and resolved.session.persistent:
                set_session_cookie(response, request, token, True)
        return response


class SecurityHeadersMiddleware:
    """Ajoute :data:`SECURITY_HEADERS` à chaque réponse HTTP, et HSTS quand le visiteur est en HTTPS.

    Middleware ASGI « pur » (et non ``BaseHTTPMiddleware``) : il ne touche qu'au début de la réponse, sans
    la mettre en mémoire, ce qui laisse passer le flux SSE tel quel.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":  # WebSocket de NiceGUI, événements de cycle de vie
            await self.app(scope, receive, send)
            return
        extra = list(SECURITY_HEADERS)
        if scope.get("scheme") == "https":
            extra.append(("Strict-Transport-Security", f"max-age={HSTS_MAX_AGE}"))

        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                headers += [
                    (name.lower().encode(), value.encode())
                    for name, value in extra
                    if name.lower().encode() not in present
                ]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
