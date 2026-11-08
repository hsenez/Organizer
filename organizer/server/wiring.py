"""Assemblage du serveur : middleware, gestion des erreurs, routes. Utilisé par le vrai serveur (NiceGUI)
comme par les tests (application FastAPI nue)."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from organizer import __version__
from organizer.core.errors import OrganizerError
from organizer.server import pwa, web_auth
from organizer.server.api import api_router
from organizer.server.security import AuthMiddleware, SecurityHeadersMiddleware
from organizer.server.state import AppState


def install(app: FastAPI, state: AppState) -> None:
    app.state.organizer = state
    app.add_middleware(AuthMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)  # ajouté en dernier = le plus extérieur

    @app.exception_handler(OrganizerError)
    async def _organizer_error(_request: Request, exc: OrganizerError) -> JSONResponse:
        return JSONResponse({"detail": exc.message}, status_code=exc.status_code)

    app.include_router(api_router)
    app.include_router(web_auth.router)
    pwa.install(app)


def create_api_app(state: AppState) -> FastAPI:
    """Application FastAPI sans interface (tests de l'API)."""
    app = FastAPI(title="Organizer API", version=__version__)
    install(app, state)
    return app
