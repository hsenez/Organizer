"""« 🔗 Copier le lien » d'une note, d'une tâche ou d'un événement : adresse ``…/open/<type>/<id>`` (voir
``organizer.links``), construite sur l'adresse publique du serveur si un admin l'a réglée, sinon sur celle
de la page. La copie se fait dans le navigateur au moment du clic (geste exigé), y compris hors HTTPS."""

from __future__ import annotations

import json

from nicegui import ui

from organizer import links
from organizer.ui.context import UiContext

# navigator.clipboard n'existe qu'en contexte sûr (HTTPS, localhost) : sinon, ancienne méthode.
COPY_JS = """
<script>
window.organizerCopy = (text) => {
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text).then(() => true, () => false);
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  let done = false;
  try { done = document.execCommand("copy"); } catch (e) { done = false; }
  area.remove();
  return Promise.resolve(done);
};
</script>
"""


def install_copy_script() -> None:
    """À appeler une fois par page (``app_frame``)."""
    ui.add_body_html(COPY_JS)


def share_url_js(ctx: UiContext, kind: str, item_id: int) -> str:
    """Expression JavaScript de l'adresse à partager."""
    path = links.open_path(kind, item_id)
    url = ctx.ds.web_url(path)
    return json.dumps(url) if url else f"location.origin + {json.dumps(path)}"


def copy_link_button(ctx: UiContext, kind: str, item_id: int, *, mark: str = "copy-link") -> ui.button:
    button = (
        ui.button(icon="link")
        .props("flat round dense")
        .tooltip("Copier le lien (à coller dans un message : s'ouvre dans le navigateur ou le client bureau)")
    )
    with button:
        anchor = ui.element("span")  # contexte stable pour le message (le bouton peut être reconstruit)

    def copied(ok: bool) -> None:
        with anchor:
            if ok:
                ui.notify("🔗 Lien copié", position="top", timeout=1500)
            else:
                ui.notify("Impossible de copier le lien ici", type="warning", position="top")

    button.on(
        "click",
        lambda e: copied(bool(e.args)),
        js_handler=f"() => organizerCopy({share_url_js(ctx, kind, item_id)}).then((ok) => emit(ok))",
    )
    return button.mark(mark)
