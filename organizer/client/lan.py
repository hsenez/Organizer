"""Passage automatique par le réseau local (client bureau).

Le client est configuré sur l'adresse publique du serveur (ex. ``https://organizer.blou.top``, à travers
Cloudflare : ≈ 300 ms par requête). À la maison, le Pi se joint directement (≈ 20 ms). Ce module :

1. demande au serveur (route ``GET /local-access``, avec le jeton) ses adresses sur le réseau local et la clé
   du compte ; elles sont gardées dans ``client.json`` (marche aussi quand Internet est coupé) ;
2. essaie ces adresses : un serveur qui y répond doit **prouver** qu'il connaît la clé
   (``/local-access/proof`` d'un nombre tiré au hasard) **avant** de recevoir la moindre requête portant le
   jeton. Ailleurs (autre réseau, même adresse par hasard), la preuve échoue et le client reste sur
   l'adresse publique ;
3. bascule toutes les pages sur l'adresse locale (``ApiClient.route``) ; revérifie le serveur local avant une
   requête si la dernière preuve date de plus de ``RECHECK_AFTER`` secondes ; revient à l'adresse publique
   dès que le réseau local ne répond plus (``ApiClient.request``) ; réessaie le réseau local toutes les
   ``SCAN_EVERY`` secondes.

Le serveur côté réseau local se joint en HTTP simple (comme avant la mise en ligne) : le jeton y circule en
clair sur le réseau de la maison.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import threading
import time
from collections.abc import Callable

import httpx

from organizer.client.api import API_PREFIX, ApiClient, make_http
from organizer.client.config import ClientConfig
from organizer.core.errors import NotFound, OrganizerError
from organizer.core.schemas import LocalAccessOut

log = logging.getLogger("organizer.client")

PROBE_TIMEOUT = 0.8  # s : un serveur sur le réseau local répond en quelques millisecondes
RECHECK_AFTER = 15.0  # s : preuve redemandée avant une requête par le réseau local si plus ancienne
SCAN_EVERY = 60.0  # s : essai du réseau local quand on passe par l'adresse publique
INFO_EVERY = 600.0  # s : adresses et clé redemandées au serveur (l'adresse du Pi peut changer)


def expected_proof(key: str, nonce: str) -> str:
    return hmac.new(bytes.fromhex(key), nonce.encode(), hashlib.sha256).hexdigest()


class LanSwitch:
    def __init__(
        self,
        get_config: Callable[[], ClientConfig],
        save_config: Callable[[], None],
        get_api: Callable[[], ApiClient | None],
        *,
        http_factory: Callable[[str], httpx.Client] | None = None,
        probe_factory: Callable[[str], httpx.Client] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """``get_config`` / ``save_config`` : la configuration **du client** (même objet, pour que l'un
        n'écrase pas les changements de l'autre)."""
        self.get_config = get_config
        self.save_config = save_config
        self.get_api = get_api
        # Requêtes normales par le réseau local (connexion vite abandonnée si le Pi n'y est plus), et
        # vérifications (réponse attendue en quelques millisecondes).
        self.http_factory = http_factory or (lambda url: make_http(url, connect=1.0))
        self.probe_factory = (
            probe_factory
            or http_factory
            or (lambda url: make_http(url, timeout=PROBE_TIMEOUT, connect=PROBE_TIMEOUT))
        )
        self._probes: dict[str, httpx.Client] = {}
        self.clock = clock
        self.verified_at = 0.0
        self.info_at: float | None = None
        self.unsupported = False  # serveur trop ancien (pas de route /local-access)
        self._clients: dict[str, httpx.Client] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- informations du serveur ---

    def refresh_info(self, api: ApiClient) -> None:
        """Redemande adresses et clé au serveur (et les garde dans ``client.json``)."""
        try:
            info = api.call("GET", "/local-access", LocalAccessOut)
        except NotFound:
            self.unsupported = True  # serveur antérieur à cette fonction
            return
        except OrganizerError as exc:
            log.info("Réseau local : informations non obtenues (%s)", exc.message)
            return
        self.info_at = self.clock()
        self.unsupported = False
        config = self.get_config()
        if (info.urls, info.key, info.user_id) != (config.lan_urls, config.lan_key, config.lan_user):
            config.lan_urls, config.lan_key, config.lan_user = info.urls, info.key, info.user_id
            self.save_config()

    # --- vérification ---

    def _client(self, url: str) -> httpx.Client:
        with self._lock:
            if url not in self._clients:
                self._clients[url] = self.http_factory(url)
            return self._clients[url]

    def _probe(self, url: str) -> httpx.Client:
        with self._lock:
            if url not in self._probes:
                self._probes[url] = self.probe_factory(url)
            return self._probes[url]

    def verify(self, url: str, key: str, user_id: int) -> bool:
        """Le serveur à ``url`` répond-il, et connaît-il la clé du compte ? (aucun jeton envoyé)"""
        nonce = secrets.token_hex(16)
        try:
            response = self._probe(url).get(
                f"{API_PREFIX}/local-access/proof", params={"user": user_id, "nonce": nonce}
            )
            proof = response.json().get("proof", "") if response.status_code == 200 else ""
        except (httpx.HTTPError, ValueError, AttributeError):
            return False
        return isinstance(proof, str) and hmac.compare_digest(proof, expected_proof(key, nonce))

    def check(self, api: ApiClient | None = None) -> bool:
        """Choisit la route : réseau local si un serveur vérifié y répond, sinon adresse configurée.
        Renvoie True si l'on passe par le réseau local."""
        api = api or self.get_api()
        if api is None:
            return False
        config = self.get_config()
        api.route.checker = self.before_request
        if not config.lan_enabled or not config.lan_key or config.lan_user is None:
            api.route.use_server()
            return False
        for url in config.lan_urls:
            if url.rstrip("/") == api.server_url:
                continue  # déjà l'adresse configurée
            if self.verify(url, config.lan_key, config.lan_user):
                self.verified_at = self.clock()
                api.route.use_local(url, self._client(url))
                return True
        api.route.use_server()
        return False

    def before_request(self) -> None:
        """Avant une requête par le réseau local : preuve renouvelée si elle est trop ancienne."""
        api = self.get_api()
        if api is None or not api.route.local or self.clock() - self.verified_at < RECHECK_AFTER:
            return
        config = self.get_config()
        if config.lan_enabled and config.lan_key and config.lan_user is not None:
            if self.verify(api.base_url, config.lan_key, config.lan_user):
                self.verified_at = self.clock()
                return
        api.route.use_server()

    # --- boucle de fond ---

    def tick(self) -> None:
        """Une passe : informations à jour (si besoin), puis choix de la route."""
        api = self.get_api()
        if api is None:
            return
        if (
            not self.unsupported
            and self.get_config().lan_enabled
            and (self.info_at is None or self.clock() - self.info_at > INFO_EVERY)
        ):
            self.refresh_info(api)
        if not api.route.local:
            self.check(api)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="organizer-lan", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("Réseau local : erreur inattendue")
            self._stop.wait(SCAN_EVERY)
