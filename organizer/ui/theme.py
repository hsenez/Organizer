"""Thème : couleurs (dérivées de :mod:`organizer.core.enums`) et feuille de style globale."""

from __future__ import annotations

from enum import Enum

from nicegui import ui

from organizer.core.enums import Importance, Status, TaskKind, Urgency

PRIMARY = "#5c7cfa"

# Épaisseur du liseré gauche des cartes selon l'importance.
IMPORTANCE_BORDER_PX = {1: 3, 2: 4, 3: 6, 4: 8}

_PREFIX = {Importance: "imp", Urgency: "urg", Status: "st", TaskKind: "kd"}


def color_name(member: Enum) -> str:
    """Nom de couleur Quasar d'une valeur d'énumération (ex. ``imp3``), utilisable en ``color=`` ou
    dans les classes ``text-imp3`` / ``bg-imp3``."""
    enum_type = type(member)
    index = list(enum_type).index(member)
    return f"{_PREFIX[enum_type]}{index}"


def _custom_colors() -> dict[str, str]:
    colors: dict[str, str] = {}
    for enum_type in _PREFIX:
        for member in enum_type:
            colors[color_name(member)] = member.meta.color
    return colors


def hex_to_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alpha})"


def _status_css() -> str:
    rules = []
    for status in Status:
        tint = hex_to_rgba(status.meta.color, 0.10 if status is not Status.NOT_STARTED else 0.0)
        rules.append(f".task-card.st-{status.value} {{ background-image: linear-gradient({tint}, {tint}); }}")
    return "\n".join(rules)


CSS = """
body { background: #f5f7fb; }
body.body--dark { background: #12141a; }

/* --- Cartes de tâches ------------------------------------------------------------------------------- */
.task-card {
    border-left: var(--imp-w) solid var(--imp-c);
    border-radius: 12px;
    cursor: pointer;
    transition: transform .12s ease, box-shadow .12s ease;
    box-shadow: 0 1px 3px rgba(20, 30, 60, .08);
}
.task-card:hover { transform: translateY(-2px); box-shadow: 0 6px 16px rgba(20, 30, 60, .14); }
.task-card .task-title { font-weight: 600; line-height: 1.25; word-break: break-word; }
.task-card.st-done { opacity: .62; }
.task-card.st-done .task-title { text-decoration: line-through; }
.task-card.st-cancelled { opacity: .5; border-top: 1px dashed #868e96; border-right: 1px dashed #868e96;
    border-bottom: 1px dashed #868e96; border-left-style: dashed; }
.task-card.st-cancelled .task-title { text-decoration: line-through; color: #868e96; }

.chip { display: inline-flex; align-items: center; gap: 3px; font-size: 12px; line-height: 1;
    padding: 3px 7px; border-radius: 999px; background: rgba(120, 130, 150, .12); white-space: nowrap; }
.chip-overdue { background: #ffe3e3; color: #c92a2a; font-weight: 600; }
.chip-today { background: #fff0db; color: #d9480f; font-weight: 600; }
.chip-soon { background: #fff9db; color: #946200; }
.body--dark .chip-overdue { background: #5c1a1a; color: #ffc9c9; }
.body--dark .chip-today { background: #5a3311; color: #ffd8a8; }
.body--dark .chip-soon { background: #4d3d00; color: #ffec99; }
.tag-dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
.tag-select .q-field__native { padding-top: 6px; }
.progress-track { width: 54px; height: 6px; border-radius: 3px; background: rgba(120, 130, 150, .25);
    overflow: hidden; display: inline-block; }
.progress-fill { height: 100%; background: #40c057; display: block; }

@keyframes organizer-pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.22); } }
.pulse { display: inline-block; animation: organizer-pulse 1.6s ease-in-out infinite; }

.task-row:hover { background: rgba(120, 130, 150, .12); }
.search-selected { background: rgba(92, 124, 250, .16); }

/* --- Glisser-déposer ------------------------------------------------------------------------------- */
.task-card, .task-row { -webkit-touch-callout: none; user-select: none; }
body.dnd-active, body.dnd-active * { cursor: grabbing !important; user-select: none !important; }
/* Défilement automatique pendant un glisser : l'aimantation des colonnes annulerait chaque petit pas. */
body.dnd-active * { scroll-snap-type: none !important; }
.dnd-ghost { position: fixed !important; z-index: 9999; pointer-events: none; opacity: .92; margin: 0 !important;
    transform: rotate(2deg) scale(1.02); box-shadow: 0 14px 30px rgba(20, 30, 60, .30) !important; }
.dnd-source { opacity: .35; }
.dnd-badge { position: fixed; z-index: 10001; pointer-events: none; padding: 4px 10px; border-radius: 8px;
    background: rgba(30, 34, 45, .92); color: white; font-size: 13px; white-space: nowrap; display: none; }
.dnd-attach-ok { outline: 3px solid #40c057 !important; box-shadow: 0 0 0 6px rgba(64, 192, 87, .25) !important; }
.dnd-attach-no { outline: 3px solid #fa5252 !important; box-shadow: 0 0 0 6px rgba(250, 82, 82, .22) !important; }
.dnd-zone-over { background: rgba(92, 124, 250, .10) !important; outline: 2px dashed #5c7cfa; outline-offset: -2px; }
.dnd-zone-denied { background: rgba(250, 82, 82, .08) !important; outline: 2px dashed #fa5252; outline-offset: -2px; }

/* --- Kanbans ------------------------------------------------------------------------------------- */
.dnd-insert { position: fixed; z-index: 10000; pointer-events: none; height: 4px; border-radius: 2px;
    background: #5c7cfa; box-shadow: 0 0 0 3px rgba(92, 124, 250, .25); display: none; }

/* --- Pages pleine largeur / pleine hauteur (kanbans) --------------------------------------------- */
.q-page:has(> .page-fill) { display: flex; flex-direction: column; }
.page-fill { flex: 1 1 auto; padding: 0 !important; }
.page-fill-column { flex: 1 1 auto; }
.page-fill-grow { flex: 1 1 auto; min-height: 320px; }

/* --- Kanbans ------------------------------------------------------------------------------------- */
.kanban { scroll-padding-left: 4px; align-items: stretch !important; }
.kanban-col { position: relative; width: 264px; max-width: 86vw; min-height: 140px;
    background: rgba(120, 130, 150, .08); }
.body--dark .kanban-col { background: rgba(255, 255, 255, .04); }
.kanban-col-collapsed { width: 46px !important; min-width: 46px; align-items: center !important; cursor: pointer;
    padding: 6px 2px !important; }
.kanban-col-collapsed:hover { background: rgba(92, 124, 250, .10); }
.kanban-vtitle { writing-mode: vertical-rl; white-space: nowrap; font-weight: 600; font-size: 14px; }
.kanban-col .task-card { width: 100%; }
.resize-handle { position: absolute; top: 0; right: -7px; width: 12px; height: 100%; cursor: col-resize;
    touch-action: none; z-index: 2; }
.resize-handle::after { content: ""; position: absolute; top: 10px; bottom: 10px; left: 5px; width: 2px;
    border-radius: 1px; background: transparent; transition: background .12s; }
.resize-handle:hover::after, body.resizing .resize-handle::after { background: #5c7cfa; }
body.resizing, body.resizing * { cursor: col-resize !important; user-select: none !important; }

/* --- Matrice ------------------------------------------------------------------------------------- */
.matrix-2x2 { display: grid; grid-template-columns: 28px 1fr 1fr; gap: 12px; align-items: stretch; }
.matrix-4x4 { display: grid; grid-template-columns: 28px repeat(4, minmax(150px, 1fr)); gap: 6px; }
.matrix-cell { min-height: 180px; min-width: 0; }
.matrix-cell-small { min-height: 96px; }
.matrix-axis { font-size: 13px; font-weight: 600; color: #868e96; align-self: center; }
.matrix-axis-v { writing-mode: vertical-rl; transform: rotate(180deg); text-align: center; justify-self: center; }
@media (max-width: 767px) {
    .matrix-2x2 { grid-template-columns: 1fr; }
    .matrix-2x2 > .matrix-axis, .matrix-2x2 > div:first-child { display: none; }
}

/* --- Accueil : compteurs cliquables ------------------------------------------------------------- */
.stat-tile { transition: transform .12s ease, box-shadow .12s ease; }
.stat-tile:hover { transform: translateY(-2px); box-shadow: 0 6px 16px rgba(20, 30, 60, .14); }
.stat-tile-active { outline: 2px solid #5c7cfa; background: rgba(92, 124, 250, .08); }
.stat-panel { border-top: 3px solid #5c7cfa; }

/* --- Navigation ----------------------------------------------------------------------------------- */
.q-drawer, .app-drawer { background: #ffffff; }
.body--dark .q-drawer, .body--dark .app-drawer { background: #161a23; color: #e9ecef; }
.nav-item { border-radius: 10px; margin: 2px 8px; }
.nav-item.nav-active { background: rgba(92, 124, 250, .14); color: #3b5bdb; font-weight: 600; }
.body--dark .nav-item.nav-active { color: #91a7ff; }

/* --- Éditeur (panneau à droite, collé au bord) ---------------------------------------------------- */
.q-dialog__inner--right { padding: 0 !important; }
.q-dialog__inner--right > div { max-height: 100vh !important; }

/* --- Éditeur markdown (notes) ----------------------------------------------------------------------- */
.md-editor .cm-editor { font-size: 15px; line-height: 1.6; border: 1px solid rgba(120, 130, 150, .35);
    border-radius: 10px; padding: 6px 12px; min-height: 160px; background: transparent; }
.md-editor .cm-editor.cm-focused { outline: none; border-color: #5c7cfa; box-shadow: 0 0 0 3px rgba(92, 124, 250, .18); }
.md-editor .cm-scroller { font-family: inherit; }
.md-editor .cm-content { caret-color: currentColor; padding: 4px 0; }
.md-editor .cm-placeholder { color: #adb5bd; font-style: italic; }
.md-editor .cm-line.cm-md-h { font-weight: 700; line-height: 1.35; padding-top: 4px; }
.md-editor .cm-md-h1 { font-size: 1.6em; }
.md-editor .cm-md-h2 { font-size: 1.35em; }
.md-editor .cm-md-h3 { font-size: 1.15em; }
.md-editor .cm-md-h4, .md-editor .cm-md-h5, .md-editor .cm-md-h6 { font-size: 1.05em; }
.md-editor .cm-md-strong { font-weight: 700; }
.md-editor .cm-md-em { font-style: italic; }
.md-editor .cm-md-strike { text-decoration: line-through; opacity: .7; }
.md-editor .cm-md-code { font-family: ui-monospace, monospace; font-size: .9em; background: rgba(120, 130, 150, .16);
    border-radius: 4px; padding: 1px 4px; }
.md-editor .cm-line.cm-md-codeblock { font-family: ui-monospace, monospace; font-size: .9em;
    background: rgba(120, 130, 150, .10); }
.md-editor .cm-md-link { color: #3b5bdb; text-decoration: underline; text-underline-offset: 2px; cursor: pointer; }
.md-editor .cm-md-path { color: #d9480f; }
.body--dark .md-editor .cm-md-link { color: #91a7ff; }
.body--dark .md-editor .cm-md-path { color: #ffa94d; }
.md-editor .cm-line.cm-md-quote { border-left: 3px solid #adb5bd; padding-left: 12px; color: #868e96; }
.md-editor .cm-line.cm-md-hr { border-bottom: 2px solid rgba(120, 130, 150, .35); }
.md-editor .cm-md-bullet { display: inline-block; width: 1.1em; color: #5c7cfa; font-weight: 700; font-size: 1.3em; line-height: 1; vertical-align: -1px; }
.md-editor .cm-md-olmark { color: #5c7cfa; font-weight: 600; }
.md-editor .cm-md-checkbox { width: 16px; height: 16px; margin: 0 7px 0 1px; vertical-align: -2px;
    cursor: pointer; accent-color: #40c057; }
.md-editor .cm-md-task-done { color: #868e96; text-decoration: line-through; }
.body--dark .md-editor .cm-selectionBackground, .body--dark .md-editor .cm-focused .cm-selectionBackground
    { background: rgba(92, 124, 250, .35) !important; }
.body--dark .md-editor .cm-cursor { border-left-color: #e9ecef; }

/* --- Curseurs de niveaux ---------------------------------------------------------------------------- */
.level-option { cursor: pointer; user-select: none; border-radius: 8px; padding: 2px 4px;
    transition: background .1s; text-align: center; }
.level-option:hover { background: rgba(120, 130, 150, .14); }
.level-option.level-selected { font-weight: 700; }
"""


def apply_theme() -> None:
    """À appeler en début de page : couleurs Quasar + CSS global."""
    ui.colors(primary=PRIMARY, **_custom_colors())
    ui.add_css(CSS + _status_css())
