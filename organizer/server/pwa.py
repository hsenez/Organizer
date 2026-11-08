"""📱 Application installable (PWA) : manifeste, icônes, service worker, en-têtes pour iOS / Android.

- ``/manifest.webmanifest`` : nom, icônes (dont une « maskable » pour Android), affichage plein écran
  (``standalone``), raccourcis « Nouvelle tâche » et « Kanbans » (appui long sur l'icône).
- ``/icons/…`` : fichiers de ``organizer/assets`` (publics : le navigateur les charge sans cookie).
- ``/sw.js`` : service worker minimal, enregistré seulement en HTTPS (contexte sécurisé obligatoire). Il ne
  met rien en cache (l'application a besoin du serveur) mais affiche une page « serveur injoignable » au
  lieu de l'erreur du navigateur.
- Installation : iPhone (Safari → Partager → « Sur l'écran d'accueil ») même en HTTP ; Android (Chrome →
  « Installer l'application ») en HTTPS, sinon simple raccourci qui ouvre Chrome.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from nicegui import ui

from organizer import ASSETS_DIR

THEME_LIGHT = "#ffffff"
THEME_DARK = "#161a23"
BACKGROUND = "#f6f7fb"


def manifest() -> dict:
    return {
        "name": "Organizer",
        "short_name": "Organizer",
        "description": "Tâches, kanbans et matrice d'Eisenhower",
        "lang": "fr",
        "dir": "ltr",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": BACKGROUND,
        "theme_color": THEME_LIGHT,
        "icons": [
            {"src": "/icons/organizer-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/icons/organizer-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {
                "src": "/icons/organizer-maskable-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
            {"src": "/icons/organizer.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"},
        ],
        "shortcuts": [
            {
                "name": "Nouvelle tâche",
                "url": "/?task=new",
                "icons": [{"src": "/icons/organizer-192.png", "sizes": "192x192"}],
            },
            {
                "name": "Kanbans",
                "url": "/kanban",
                "icons": [{"src": "/icons/organizer-192.png", "sizes": "192x192"}],
            },
        ],
    }


SERVICE_WORKER = """// Service worker d'Organizer : pas de cache (l'application a besoin du serveur),
// seulement une page d'attente lisible quand le serveur ne répond pas.
const OFFLINE = `<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Organizer</title>
<style>body{font-family:system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;
background:#f6f7fb;color:#1f2330;text-align:center;padding:24px}button{font:inherit;padding:10px 18px;
border-radius:10px;border:0;background:#5c7cfa;color:#fff}</style></head><body><div>
<img src="/icons/organizer-192.png" width="96" height="96" alt=""><h1>Serveur injoignable</h1>
<p>Organizer n'arrive pas à joindre le serveur. Vérifiez votre connexion Internet (ou au réseau local).</p>
<button onclick="location.reload()">Réessayer</button></div></body></html>`;

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return;
  event.respondWith(
    fetch(event.request).catch(
      () => new Response(OFFLINE, { headers: { "Content-Type": "text/html; charset=utf-8" } }),
    ),
  );
});
"""

HEAD = f"""
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="{THEME_LIGHT}" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="{THEME_DARK}" media="(prefers-color-scheme: dark)">
<link rel="apple-touch-icon" href="/icons/apple-touch-icon.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Organizer">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<script>
  if ("serviceWorker" in navigator && window.isSecureContext) {{
    navigator.serviceWorker.register("/sw.js").catch(() => {{}});
  }}
</script>
"""


def install(app: FastAPI) -> None:
    """Routes de la PWA ; l'en-tête HTML est ajouté par :func:`add_head` (pages NiceGUI)."""
    app.add_api_route(
        "/manifest.webmanifest",
        lambda: JSONResponse(manifest(), media_type="application/manifest+json"),
        include_in_schema=False,
    )
    app.add_api_route(
        "/sw.js",
        lambda: Response(SERVICE_WORKER, media_type="text/javascript", headers={"Cache-Control": "no-cache"}),
        include_in_schema=False,
    )


def add_head() -> None:
    ui.add_head_html(HEAD, shared=True)


def add_static(app) -> None:
    app.add_static_files("/icons", ASSETS_DIR)
