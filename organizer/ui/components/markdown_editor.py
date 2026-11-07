"""Éditeur markdown « façon Obsidian » pour les notes (voir ``markdown_editor.js``).

S'appuie sur CodeMirror 6 tel que fourni par NiceGUI (paquet ESM ``nicegui-codemirror``) : aucune dépendance
JavaScript supplémentaire, rien à télécharger à l'exécution (le Pi peut être hors ligne).
"""

from __future__ import annotations

from collections.abc import Callable
from functools import cache
from pathlib import Path

import nicegui.elements.codemirror as nicegui_codemirror
from nicegui.elements.codemirror import CodeMirror  # noqa: F401  (enregistre l'ESM « nicegui-codemirror »)
from nicegui.elements.mixins.value_element import ValueElement
from nicegui.events import Handler, ValueChangeEventArguments


@cache
def markdown_module() -> str:
    """Chemin d'import du module ``@codemirror/lang-markdown`` dans le paquet de NiceGUI.

    Le nom du fichier contient un hachage qui change d'une version de NiceGUI à l'autre : on le retrouve
    par son contenu (ses exports nommés) plutôt que de le coder en dur.
    """
    dist = Path(nicegui_codemirror.__file__).parent / "dist"
    for path in sorted(dist.glob("*.js")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "as insertNewlineContinueMarkup" in text and "as markdownLanguage" in text:
            return f"nicegui-codemirror/{path.name}"
    raise RuntimeError("Module markdown de CodeMirror introuvable dans NiceGUI : version incompatible ?")


class MarkdownEditor(ValueElement[str], component="markdown_editor.js"):
    VALUE_PROP = "value"
    LOOPBACK = False  # la valeur vient de l'éditeur : inutile de la lui renvoyer (le curseur ne saute pas)

    def __init__(
        self,
        value: str = "",
        *,
        placeholder: str = "",
        on_change: Handler[ValueChangeEventArguments[str]] | None = None,
        on_open_link: Callable[[str, str], None] | None = None,
    ) -> None:
        """Éditeur de notes.

        :param on_change: appelé quand le texte change (au plus toutes les 0,4 s pendant la frappe)
        :param on_open_link: appelé avec ``(cible, type)`` quand on clique sur un lien ; ``type`` vaut
            ``"url"`` (adresse web reconnue par le markdown), ``"link"`` (cible d'un ``[texte](cible)``) ou
            ``"path"`` (chemin de fichier écrit tel quel)
        """
        super().__init__(value=value, on_value_change=on_change)
        self._props["markdown-module"] = markdown_module()
        self._props["placeholder"] = placeholder
        if on_open_link is not None:
            self.on("open-link", lambda e: on_open_link(*_link_args(e.args)))

    def focus(self) -> None:
        self.run_method("focus")


def _link_args(args) -> tuple[str, str]:
    if isinstance(args, dict):
        return str(args.get("target", "")), str(args.get("kind", "link"))
    return str(args), "link"
