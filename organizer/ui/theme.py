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
.progress-track { width: 54px; height: 6px; border-radius: 3px; background: rgba(120, 130, 150, .25);
    overflow: hidden; display: inline-block; }
.progress-fill { height: 100%; background: #40c057; display: block; }

@keyframes organizer-pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.22); } }
.pulse { display: inline-block; animation: organizer-pulse 1.6s ease-in-out infinite; }

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
