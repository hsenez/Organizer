"""⚡ Flux des modifications en temps réel (Server-Sent Events), pour le client bureau.

``GET /api/v1/events`` (jeton requis) garde la connexion ouverte et envoie :

- ``event: hello`` à la connexion (le client se rafraîchit s'il s'agit d'une reconnexion : il a pu manquer
  des modifications) ;
- ``event: changed`` + ``data: {"tables": [...], "user_id": …, "origin": …}`` à chaque modification ;
- un commentaire ``: ping`` toutes les ``HEARTBEAT`` secondes (connexion gardée vivante).

Pas de contenu, seulement le signal : le client relit ce qu'il a le droit de voir.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from organizer.core.events import ChangeEvent
from organizer.core.schemas import UserOut
from organizer.server.api.deps import get_state, get_user
from organizer.server.state import AppState

router = APIRouter(tags=["Temps réel"])

HEARTBEAT = 20.0  # secondes
QUEUE_SIZE = 200


def format_event(name: str, data: dict | None = None) -> str:
    lines = [f"event: {name}"]
    if data is not None:
        lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"


@router.get("/events")
async def events(request: Request, _user: UserOut = Depends(get_user), state: AppState = Depends(get_state)):
    """Flux SSE des modifications (voir la description du module)."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[ChangeEvent] = asyncio.Queue(maxsize=QUEUE_SIZE)

    def push(event: ChangeEvent) -> None:
        if not queue.full():  # client trop lent : il se rafraîchira de toute façon au prochain événement
            queue.put_nowait(event)

    def on_event(event: ChangeEvent) -> None:  # appelé dans le fil de la transaction
        loop.call_soon_threadsafe(push, event)

    unsubscribe = state.events.subscribe(on_event)

    async def stream() -> AsyncIterator[str]:
        try:
            yield "retry: 3000\n" + format_event("hello", {})
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield format_event("changed", event.to_json())
        finally:
            unsubscribe()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
