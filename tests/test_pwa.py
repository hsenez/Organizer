"""📱 PWA : manifeste, service worker, icônes, HTTPS facultatif."""

from __future__ import annotations

from fastapi.testclient import TestClient

from organizer import ASSETS_DIR, FAVICON
from organizer.config import Settings
from organizer.server import pwa
from organizer.server.state import create_state
from organizer.server.wiring import create_api_app


def test_manifest_and_service_worker(tmp_path):
    http = TestClient(create_api_app(create_state(Settings(data_dir=tmp_path))))
    response = http.get("/manifest.webmanifest")
    assert response.headers["content-type"].startswith("application/manifest+json")
    manifest = response.json()
    assert manifest["display"] == "standalone" and manifest["start_url"] == "/"
    assert {"192x192", "512x512"} <= {i["sizes"] for i in manifest["icons"]}
    assert any(i.get("purpose") == "maskable" for i in manifest["icons"])
    assert manifest["shortcuts"][0]["url"] == "/?task=new"
    sw = http.get("/sw.js")
    assert sw.headers["content-type"].startswith("text/javascript") and "Serveur injoignable" in sw.text


def test_icon_files_exist():
    for icon in pwa.manifest()["icons"]:
        assert (ASSETS_DIR / icon["src"].removeprefix("/icons/")).is_file(), icon["src"]
    assert (ASSETS_DIR / "apple-touch-icon.png").is_file() and FAVICON.is_file()
    assert (ASSETS_DIR / "organizer.ico").is_file()


def test_https_settings(monkeypatch, tmp_path):
    assert not Settings(data_dir=tmp_path).https
    monkeypatch.setenv("ORGANIZER_SSL_CERT", "/etc/organizer/cert.pem")
    monkeypatch.setenv("ORGANIZER_SSL_KEY", "/etc/organizer/key.pem")
    assert Settings(data_dir=tmp_path).https
