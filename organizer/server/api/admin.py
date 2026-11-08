"""Routes d'administration : sauvegarde du serveur et jetons de sauvegarde.

``GET /admin/backup`` accepte deux façons de s'authentifier :

- une session d'administrateur (navigateur, client bureau) ;
- un **jeton de sauvegarde** (``Authorization: Bearer orgbk_…``), pour un script planifié : sans
  expiration, révocable, il ne donne accès qu'à cette route, et seulement depuis le réseau local (le Pi
  lui-même, une machine de la maison). Derrière Cloudflare Tunnel, un visiteur venu d'Internet garde son
  adresse publique (voir :mod:`organizer.server.security`) : un jeton qui aurait fuité y reste inutilisable.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from organizer.core.schemas import ApiKeyCreated, ApiKeyIn, ApiKeyOut
from organizer.core.services.account import AccountService
from organizer.core.services.auth import API_KEY_PREFIX
from organizer.server.api.deps import get_account, get_state
from organizer.server.backup import BackupArchive
from organizer.server.security import (
    NOT_AUTHENTICATED,
    client_ip,
    extract_token,
    is_local_address,
    request_auth,
)
from organizer.server.state import AppState

router = APIRouter(prefix="/admin", tags=["Administration"])
log = logging.getLogger("organizer.backup")

KEY_OUTSIDE_LAN = "Le jeton de sauvegarde ne fonctionne que depuis le réseau local."


def backup_access(request: Request) -> str:
    """Qui demande la sauvegarde (pour le journal) ; refuse sinon."""
    auth = request_auth(request)
    if auth is not None:
        if not auth.user.is_admin:
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs.")
        return f"{auth.user.username!r}"
    token, source = extract_token(request)
    ip = client_ip(request)
    if source == "bearer" and token and token.startswith(API_KEY_PREFIX["backup"]):
        if not is_local_address(ip):
            log.warning("Jeton de sauvegarde refusé : demande venue de %s (hors du réseau local)", ip)
            raise HTTPException(status_code=403, detail=KEY_OUTSIDE_LAN)
        key = get_state(request).auth.resolve_api_key(token, "backup", ip)
        if key is not None:
            return f"le jeton {key.label!r}"
        log.warning("Jeton de sauvegarde inconnu ou révoqué, depuis %s", ip)
    raise HTTPException(status_code=401, detail=NOT_AUTHENTICATED)


@router.get(
    "/backup",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/x-tar": {}}, "description": "Archive .tar non compressée"}},
)
def download_backup(
    request: Request,
    uploads: bool = True,
    who: str = Depends(backup_access),
    state: AppState = Depends(get_state),
):
    """Archive ``.tar`` (non compressée) : image cohérente de la base, pièces jointes (``uploads=false``
    pour s'en passer) et ``manifest.json`` (versions, empreintes SHA-256), en dernier."""
    archive = BackupArchive(state.settings, include_uploads=uploads)
    log.info(
        "Sauvegarde%s demandée par %s depuis %s",
        "" if uploads else " (base seule)",
        who,
        client_ip(request),
    )
    return StreamingResponse(
        archive.chunks(),
        media_type="application/x-tar",
        headers={
            "Content-Disposition": f'attachment; filename="{archive.filename}"',
            "Cache-Control": "no-store",
        },
        background=BackgroundTask(archive.cleanup),  # si l'envoi n'a jamais commencé
    )


@router.get("/backup-keys", response_model=list[ApiKeyOut])
def list_backup_keys(account: AccountService = Depends(get_account)):
    return account.backup_keys()


@router.post("/backup-keys", response_model=ApiKeyCreated, status_code=201)
def create_backup_key(data: ApiKeyIn, account: AccountService = Depends(get_account)):
    """Nouveau jeton de sauvegarde. Le secret (``token``) n'est renvoyé **qu'ici** : le noter."""
    return account.create_backup_key(data.label)


@router.delete("/backup-keys/{key_id}", status_code=204)
def revoke_backup_key(key_id: int, account: AccountService = Depends(get_account)):
    account.revoke_backup_key(key_id)
    return Response(status_code=204)
