"""Routes HTTP de connexion / déconnexion du navigateur (posent et retirent le cookie)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from organizer.server.security import clear_session_cookie, request_auth, set_session_cookie

router = APIRouter(prefix="/auth", include_in_schema=False)


def safe_next(target: str | None) -> str:
    """N'autorise que les redirections internes (« /… », pas « //site-externe »)."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return "/"
    return target


@router.get("/complete")
def complete(request: Request, ticket: str = "", next: str = "/"):
    """Échange un ticket de connexion (émis par la page /login ou /setup) contre le cookie de session."""
    state = request.app.state.organizer
    data = state.tickets.redeem(ticket)
    if data is None:
        return RedirectResponse("/login?expired=1", status_code=303)
    token, _ = state.auth.create_session(
        data.user_id, kind="web", persistent=data.persistent, label=data.label
    )
    response = RedirectResponse(safe_next(next), status_code=303)
    set_session_cookie(response, token, data.persistent, state.settings)
    return response


@router.get("/logout")
def logout(request: Request):
    state = request.app.state.organizer
    if request_auth(request) is not None and request.state.auth_token:
        state.auth.revoke_token(request.state.auth_token)
    response = RedirectResponse("/login", status_code=303)
    clear_session_cookie(response)
    return response
