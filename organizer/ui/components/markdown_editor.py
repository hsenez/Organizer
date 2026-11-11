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
        on_ref_request: Callable[[], None] | None = None,
        readonly: bool = False,
        sort_checks: bool = False,
    ) -> None:
        """Éditeur de notes.

        :param on_change: appelé quand le texte change (au plus toutes les 0,4 s pendant la frappe)
        :param on_open_link: appelé avec ``(cible, type)`` quand on clique sur un lien ; ``type`` vaut
            ``"url"`` (adresse web reconnue par le markdown), ``"link"`` (cible d'un ``[texte](cible)``),
            ``"path"`` (chemin de fichier écrit tel quel) ou ``"ref"`` (lien interne ``task:12``…)
        :param on_ref_request: appelé quand on tape « [[ » (rechercher un élément à citer, puis
            :meth:`insert_ref`)
        :param readonly: affichage seul (liens et pastilles cliquables, cases inactives)
        :param sort_checks: cocher une case trie la liste (non cochées en haut)
        """
        super().__init__(value=value, on_value_change=on_change)
        self._props["markdown-module"] = markdown_module()
        self._props["placeholder"] = placeholder
        self._props["readonly"] = readonly
        self._props["sort-checks"] = sort_checks
        self._props["ref-picker"] = on_ref_request is not None
        self._props["refs"] = {}
        if on_open_link is not None:
            self.on("open-link", lambda e: on_open_link(*_link_args(e.args)))
        if on_ref_request is not None:
            self.on("ref-request", lambda _: on_ref_request())

    def focus(self) -> None:
        self.run_method("focus")

    def set_refs(self, refs: dict[str, dict]) -> None:
        """Ce que désigne chaque lien interne (``{"task:12": {"title", "emoji", "available"}}``)."""
        if refs != self._props["refs"]:
            self._props["refs"] = refs
            self.update()

    def set_readonly(self, readonly: bool) -> None:
        if readonly != self._props["readonly"]:
            self._props["readonly"] = readonly
            self.update()

    def insert_ref(self, text: str) -> None:
        """Insère un lien interne au curseur (à la place du « [[ » qui a ouvert la recherche)."""
        self.run_method("insertRef", text)

    def js_format(self, kind: str) -> str:
        """Appel JavaScript qui applique un bouton de la barre (``bold``, ``task``…) sans passer par le
        serveur (pas d'aller-retour : instantané aussi sur le client bureau)."""
        return f"() => getElement({self.id})?.format({kind!r})"


# Barre de boutons : (clé du JS, libellé, infobulle).
TOOLBAR = (
    ("h1", "H1", "Titre"),
    ("h2", "H2", "Sous-titre"),
    ("bold", "format_bold", "Gras (**texte**)"),
    ("italic", "format_italic", "Italique (*texte*)"),
    ("strike", "strikethrough_s", "Barré (~~texte~~)"),
    ("bullet", "format_list_bulleted", "Liste à puces (- )"),
    ("ordered", "format_list_numbered", "Liste numérotée (1. )"),
    ("task", "check_box", "Cases à cocher (- [ ] )"),
    ("quote", "format_quote", "Citation (> )"),
    ("code", "code", "Code (`texte`)"),
    ("link", "language", "Lien web [texte](adresse)"),
    ("hr", "horizontal_rule", "Ligne de séparation (---)"),
)


def markdown_toolbar(editor: MarkdownEditor, on_ref: Callable[[], None] | None = None):
    """Barre de mise en forme au-dessus d'un :class:`MarkdownEditor`. Les boutons agissent dans le
    navigateur ; ``mousedown`` sans action par défaut : l'éditeur garde le focus et la sélection (au doigt,
    voir ``data-keep-focus`` dans ``viewport.js``)."""
    from nicegui import ui

    # ``data-keep-focus`` : au doigt, toucher un bouton garde le focus (et le clavier) dans le texte
    # (viewport.js).
    with ui.row().classes("md-toolbar w-full items-center gap-0 flex-wrap").props("data-keep-focus") as bar:
        for kind, icon, tooltip in TOOLBAR:
            button = ui.button(icon=None if icon.startswith("H") else icon).props("flat dense size=sm")
            if icon.startswith("H"):
                button.set_text(icon)
                button.props("no-caps")
            button.tooltip(tooltip).mark(f"md-tool-{kind}")
            button.on("mousedown", js_handler="(e) => e.preventDefault()")
            button.on("click", js_handler=editor.js_format(kind))
        if on_ref is not None:
            ref = ui.button("🔗 Lier à…", on_click=on_ref).props("flat dense size=sm no-caps")
            ref.tooltip("Lien vers une note, une tâche ou un événement (ou taper [[ dans le texte)")
            ref.on("mousedown", js_handler="(e) => e.preventDefault()")
            ref.mark("md-tool-ref")
    return bar


def _link_args(args) -> tuple[str, str]:
    if isinstance(args, dict):
        return str(args.get("target", "")), str(args.get("kind", "link"))
    return str(args), "link"
