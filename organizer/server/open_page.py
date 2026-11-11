"""Page ``/open/<type>/<id>`` : cible des liens partagés (« 🔗 Copier le lien »).

Elle propose d'ouvrir l'élément dans le **client bureau** (``organizer://note/5``, protocole déclaré par les
installeurs) ou de **continuer dans le navigateur** (page de l'élément ; connexion demandée si besoin). Le
choix peut être retenu sur l'appareil (``localStorage``) ; un téléphone va directement au navigateur.
Page statique, sans session : elle ne révèle rien (ni titre ni existence de l'élément).
"""

from __future__ import annotations

import html
import json

from fastapi import APIRouter, Path
from fastapi.responses import HTMLResponse

from organizer import links

router = APIRouter()
STORAGE_KEY = "organizer-open-with"
NOUNS = {"task": "cette tâche", "event": "cet événement", "note": "cette note"}
EMOJI = {"task": "📋", "event": "📅", "note": "📝"}


@router.get("/open/{kind}/{item_id}", response_class=HTMLResponse, include_in_schema=False)
def open_page(kind: str = Path(pattern="^(task|event|note)$"), item_id: int = Path(ge=1)):
    return HTMLResponse(render(kind, item_id))


def render(kind: str, item_id: int) -> str:
    app_url = links.scheme_url(kind, item_id)
    web_url = links.page_path(kind, item_id)
    data = json.dumps({"app": app_url, "web": web_url, "key": STORAGE_KEY})
    noun = html.escape(NOUNS[kind])
    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Ouvrir dans Organizer</title>
<link rel="icon" href="/icons/organizer-64.png">
<style>
  :root {{ color-scheme: light dark; font-family: system-ui, sans-serif; }}
  body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f6f7fb; color: #1f2430; }}
  main {{ width: min(420px, calc(100vw - 32px)); background: #fff; border-radius: 16px; padding: 28px 24px;
         box-shadow: 0 8px 30px rgba(20, 30, 60, .12); text-align: center; }}
  h1 {{ font-size: 1.25rem; margin: 8px 0 4px; }}
  p {{ color: #5c6475; margin: 4px 0 18px; }}
  a.button {{ display: block; padding: 12px 16px; margin: 10px 0; border-radius: 10px; text-decoration: none;
             font-weight: 600; background: #eef1fb; color: #2b3a8c; }}
  a.button.primary {{ background: #5c7cfa; color: #fff; }}
  label {{ display: flex; gap: 8px; justify-content: center; align-items: center; font-size: .9rem;
          color: #5c6475; margin-top: 14px; }}
  #status {{ min-height: 1.2em; font-size: .9rem; color: #5c6475; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #161a23; color: #e9ecef; }} main {{ background: #1f2430; }}
    p, label, #status {{ color: #adb5bd; }} a.button {{ background: #2a3142; color: #bac8ff; }}
  }}
</style>
</head>
<body>
<main>
  <div style="font-size: 2.4rem">{EMOJI[kind]}</div>
  <h1>Ouvrir {noun}</h1>
  <p>Dans quelle application ?</p>
  <a class="button primary" id="app" href="{html.escape(app_url)}">🖥️ Client bureau Organizer</a>
  <a class="button" id="web" href="{html.escape(web_url)}">🌐 Continuer dans le navigateur</a>
  <label><input type="checkbox" id="remember"> Toujours faire ce choix sur cet appareil</label>
  <div id="status"></div>
</main>
<script>
(() => {{
  const cfg = {data};
  const status = document.getElementById("status");
  const remember = document.getElementById("remember");
  const store = (value) => {{ try {{ value ? localStorage.setItem(cfg.key, value) : localStorage.removeItem(cfg.key); }} catch (e) {{}} }};
  let saved = null;
  try {{ saved = localStorage.getItem(cfg.key); }} catch (e) {{}}
  const launched = () => {{
    status.innerHTML = "Organizer devrait s'ouvrir… Rien ne se passe ? Le client bureau n'est peut-être pas "
      + "installé sur ce poste : continuez dans le navigateur.";
  }};
  document.getElementById("app").addEventListener("click", () => {{ if (remember.checked) store("app"); launched(); }});
  document.getElementById("web").addEventListener("click", () => {{ if (remember.checked) store("web"); }});
  const mobile = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);
  if (mobile || saved === "web") {{
    location.replace(cfg.web);
  }} else if (saved === "app") {{
    remember.checked = true;
    remember.addEventListener("change", () => store(remember.checked ? "app" : null));
    location.href = cfg.app;
    launched();
  }}
}})();
</script>
</body>
</html>
"""
