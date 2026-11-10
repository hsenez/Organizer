"""Thème : couleurs (dérivées de :mod:`organizer.core.enums`) et feuille de style globale."""

from __future__ import annotations

from enum import Enum

from nicegui import ui

from organizer.core.enums import Importance, Status, TaskKind, Urgency

PRIMARY = "#5c7cfa"

# Épaisseur du liseré gauche des cartes selon l'importance.
IMPORTANCE_BORDER_PX = {1: 3, 2: 4, 3: 6, 4: 8}
IMPORTANCE_CHIP_BORDER_PX = {1: 1, 2: 2, 3: 2, 4: 3}  # pourtour des pastilles du calendrier

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


def readable_text(hex_color: str) -> str:
    """Couleur du texte posé sur un fond ``#rrggbb`` : presque noir sur un fond clair, blanc sur un fond
    foncé (luminance relative WCAG)."""
    h = hex_color.lstrip("#")

    def linear(channel: str) -> float:
        c = int(channel, 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(h[i : i + 2]) for i in (0, 2, 4))
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    # Contraste avec le noir (L + 0.05) / 0.05 contre le blanc 1.05 / (L + 0.05) : égaux vers L ≈ 0,18.
    return "#1f2328" if luminance > 0.18 else "#ffffff"


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
/* Indicateur réseau local / Internet (connection_badge.py) : discret, net au survol. */
.connection-badge { opacity: .6; font-size: 1.15rem; width: 36px; height: 36px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, .18); }
.connection-badge:hover { opacity: 1; }
.connection-local { background: #e6fcf5 !important; }
.connection-internet { background: #e7f5ff !important; }
.body--dark .connection-local { background: #0b3b30 !important; }
.body--dark .connection-internet { background: #102a43 !important; }
/* Fichiers du système survolant une zone de dépôt (file_drop.js) : cadre et invitation. */
.file-drop-over { position: relative; outline: 3px dashed #5c7cfa !important; outline-offset: -6px; }
.file-drop-over::after { content: attr(data-file-drop-label); position: absolute; inset: 0; z-index: 3000;
  display: flex; align-items: center; justify-content: center; pointer-events: none; font-size: 1.25rem;
  font-weight: 600; color: #364fc7; background: rgba(237, 242, 255, .82); }
.body--dark .file-drop-over::after { color: #dbe4ff; background: rgba(25, 32, 60, .82); }
.file-drop-card { outline: 3px dashed #5c7cfa !important; outline-offset: 2px;
  background: rgba(92, 124, 250, .10) !important; }

/* --- Kanbans ------------------------------------------------------------------------------------- */
.dnd-insert { position: fixed; z-index: 10000; pointer-events: none; height: 4px; border-radius: 2px;
    background: #5c7cfa; box-shadow: 0 0 0 3px rgba(92, 124, 250, .25); display: none; }

/* --- Pages pleine largeur / pleine hauteur (kanbans) --------------------------------------------- */
.q-page:has(> .page-fill) { display: flex; flex-direction: column; }
.page-fill { flex: 1 1 auto; padding: 0 !important; }
.page-fill-column { flex: 1 1 auto; }
.page-fill-grow { flex: 1 1 auto; min-height: 320px; }

/* --- Calendrier --------------------------------------------------------------------------------- */
.calendar { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 1px; overflow: hidden;
    border: 1px solid rgba(120, 130, 150, .25); border-radius: 12px; background: rgba(120, 130, 150, .25); }
.calendar-head { padding: 4px 6px; text-align: center; font-size: .8rem; font-weight: 600;
    text-transform: capitalize; color: #64748b; background: #f8fafc; }
.calendar-cell { min-height: 64px; padding: 4px; background: #fff; overflow: hidden; }
.calendar-cell.calendar-weekend, .calendar-head.calendar-weekend { background: #f4f6fb; }
.calendar-outside { color: #adb5bd; }
.calendar-outside.calendar-cell { background: #fafbfc; }
.calendar-day-number { align-self: flex-start; display: inline-flex; align-items: center; justify-content: center; min-width: 1.6rem;
    height: 1.6rem; padding: 0 4px; border-radius: 999px; font-size: .85rem; font-weight: 600; }
.calendar-today .calendar-day-number { background: #5c7cfa; color: #fff; }
.calendar-today { box-shadow: inset 0 0 0 2px rgba(92, 124, 250, .55); }
.body--dark .calendar { border-color: rgba(255, 255, 255, .10); background: rgba(255, 255, 255, .10); }
.body--dark .calendar-head { color: #94a3b8; background: #161a23; }
.body--dark .calendar-cell { background: #1a1e28; }
.body--dark .calendar-cell.calendar-weekend, .body--dark .calendar-head.calendar-weekend { background: #1f2330; }
.body--dark .calendar-outside { color: #4b5563; }
.body--dark .calendar-outside.calendar-cell { background: #15181f; }
.calendar-cell { display: flex; flex-direction: column; gap: 2px; cursor: default; user-select: none; }
.calendar-selected { box-shadow: inset 0 0 0 2px #5c7cfa !important; background: rgba(92, 124, 250, .07) !important; }
.calendar-alarm { box-shadow: inset 0 0 0 2px #e03131; background: #fff5f5 !important; }
.calendar-alarm.calendar-selected { box-shadow: inset 0 0 0 2px #e03131, inset 0 0 0 4px #5c7cfa !important; }
.body--dark .calendar-alarm { background: #2c1517 !important; }
.calendar-chips { display: flex; flex-direction: column; gap: 2px; min-height: 0; overflow-y: auto;
    scrollbar-width: thin; }
/* Pastille d'échéance : ellipse de la couleur de l'urgence, titre coupé par « … ». */
.calendar-layout { display: flex; gap: 12px; min-height: 0; }
.calendar-layout > .calendar { flex: 1 1 auto; min-width: 0; }
.calendar-undated { position: relative; flex: none; width: 236px; display: flex; flex-direction: column;
    gap: 6px; min-height: 0;
    padding: 10px; border: 1px solid rgba(120, 130, 150, .25); border-radius: 12px; background: #fff; }
.body--dark .calendar-undated { border-color: rgba(255, 255, 255, .10); background: #1a1e28; }
.calendar-undated .calendar-chips { flex: 1 1 auto; gap: 4px; }
.calendar-undated-collapsed { width: 46px !important; align-items: center; padding: 8px 4px; cursor: pointer; }
.calendar-undated-collapsed:hover { background: rgba(92, 124, 250, .10); }
.resize-handle-left { right: auto; left: -7px; }
@media (max-width: 1023px) {
    .calendar-layout { flex-direction: column; }
    .calendar-layout > .calendar { min-height: 70vh; }
    .calendar-undated { width: auto !important; max-height: 60vh; }
    .calendar-undated .resize-handle { display: none; }
    /* Repliée sous la grille : une barre horizontale. */
    .calendar-undated-collapsed { flex-direction: row; justify-content: flex-start; gap: 8px; padding: 6px 10px; }
    .calendar-undated-collapsed .kanban-vtitle { writing-mode: horizontal-tb; }
    .calendar-undated .q-btn .q-icon { transform: rotate(-90deg); }
}
/* Fond = urgence ; pourtour = importance (style en ligne), séparé du fond par un liseré clair pour rester
   visible quand les deux couleurs se ressemblent (orange sur orange, rouge sur rouge). */
.calendar-chip { display: block; flex: none; max-width: 100%; padding: 0 7px; border-radius: 999px;
    box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .85); box-sizing: border-box;
    font-size: .75rem; line-height: 1.15rem; font-weight: 500; white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis; cursor: pointer; }
.calendar-chip:hover { filter: brightness(.94); }
.calendar-chip-done { text-decoration: line-through; opacity: .7; color: inherit; }
@keyframes calendar-alarm {
    0%, 100% { box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .85), 0 0 0 0 rgba(224, 49, 49, .55); }
    50% { box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .85), 0 0 0 4px rgba(224, 49, 49, 0); } }
.calendar-chip-overdue { color: #fff; font-weight: 700; text-shadow: 0 1px 1px rgba(0, 0, 0, .35);
    background: repeating-linear-gradient(-45deg, #a61e1e 0 6px, #c92a2a 6px 12px);
    animation: calendar-alarm 1.4s ease-in-out infinite; }
.calendar-legend-ring { background: transparent; box-sizing: border-box; }
.calendar-legend { display: inline-flex; align-items: center; justify-content: center; width: 1.5rem;
    height: 1.1rem; border-radius: 999px; font-size: .7rem; }
/* Case agrandie : la vue « grandit » depuis la case double-cliquée (centre mémorisé par le navigateur). */
.calendar-zoom .q-dialog__inner { transform-origin: var(--calendar-zoom-x, 50%) var(--calendar-zoom-y, 50%); }
.calendar-zoom-card { display: flex; flex-direction: column; border-radius: 0 !important; }
.calendar-zoom-head { border-bottom: 1px solid rgba(120, 130, 150, .25); }
.calendar-zoom-number { font-size: 1.1rem; min-width: 2.2rem; height: 2.2rem; }
.calendar-today-number { background: #5c7cfa; color: #fff; }
/* Événements dans la grille. Les bandes (plusieurs jours / toute la journée) sont des éléments de la grille
   posés par-dessus les cases (grid-row / grid-column), décalés selon leur ligne (--lane) ; les pastilles
   d'une case commencent sous les bandes qui la traversent (--lanes). */
.calendar { --lane-h: 20px; --day-head: calc(1.6rem + 6px); }
.calendar-cell .calendar-chips { margin-top: calc(var(--lanes, 0) * var(--lane-h)); }
.calendar-band { align-self: start; z-index: 2; height: calc(var(--lane-h) - 3px); min-width: 0;
    margin: calc(var(--day-head) + var(--lane) * var(--lane-h)) 3px 0; padding: 0 6px; border-radius: 5px;
    font-size: .75rem; line-height: calc(var(--lane-h) - 3px); font-weight: 600; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; cursor: pointer; box-shadow: 0 1px 2px rgba(0, 0, 0, .15); }
.calendar-band:hover { filter: brightness(.94); }
.calendar-band-before { margin-left: 0; border-top-left-radius: 0; border-bottom-left-radius: 0; }
.calendar-band-after { margin-right: 0; border-top-right-radius: 0; border-bottom-right-radius: 0; }
body.dnd-active .calendar-band { pointer-events: none; }  /* la case sous le pointeur reçoit le dépôt */
.calendar-event { display: block; flex: none; max-width: 100%; padding: 0 5px; border-radius: 4px;
    border-left: 3px solid; font-size: .75rem; line-height: 1.15rem; white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis; cursor: pointer; }
.calendar-event:hover { filter: brightness(.94); }
.calendar-single-week .calendar-cell { min-height: 260px; }
@media (max-width: 599px) {
    .calendar { --lane-h: 16px; --day-head: calc(1.6rem + 4px); }
    .calendar-band { font-size: .62rem; padding: 0 3px; }
    .calendar-event { font-size: .62rem; line-height: 1rem; padding: 0 2px; }
}

/* Vue d'un jour : zone tâches + agenda sur deux colonnes (0-12 h, 12-24 h). */
.zoom-layout { flex: 1 1 auto; align-self: stretch; width: 100%; min-height: 0; display: flex; gap: 16px; padding: 12px 16px 16px; overflow: auto; }
.zoom-tasks { flex: 0 0 290px; min-height: 0; overflow-y: auto; }
.zoom-agenda { flex: 1 1 auto; min-width: 0; min-height: 0; display: flex; flex-direction: column; }
.zoom-whole-day { margin: 0 !important; height: 24px; line-height: 24px; padding: 0 10px; flex: 1 1 200px;
    max-width: 100%; }
.agenda { flex: 1 1 auto; min-height: 520px; display: flex; }
.agenda-columns { flex: 1 1 auto; display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.agenda-col { display: flex; min-height: 0; }
.agenda-hours { width: 40px; flex: none; display: flex; flex-direction: column; }
.agenda-hour { flex: 1 1 0; font-size: .68rem; color: #868e96; line-height: 1; padding-top: 1px; }
.agenda-track { position: relative; flex: 1 1 auto; border-radius: 8px; border: 1px solid rgba(120, 130, 150, .3);
    background-color: #fff;
    background-image: repeating-linear-gradient(to bottom, transparent 0, transparent calc(100% / 12 - 1px),
        rgba(120, 130, 150, .28) calc(100% / 12 - 1px), rgba(120, 130, 150, .28) calc(100% / 12)),
      repeating-linear-gradient(to bottom, transparent 0, transparent calc(100% / 24 - 1px),
        rgba(120, 130, 150, .10) calc(100% / 24 - 1px), rgba(120, 130, 150, .10) calc(100% / 24)); }
.body--dark .agenda-track { background-color: #1a1e28; border-color: rgba(255, 255, 255, .12); }
.agenda-block { position: absolute; box-sizing: border-box; min-height: 18px; padding: 1px 6px 2px; z-index: 1;
    border-left: 4px solid; border-radius: 6px; overflow: hidden; font-size: .75rem; line-height: 1.15;
    cursor: grab; user-select: none; box-shadow: 0 1px 2px rgba(0, 0, 0, .12); }
.agenda-block[data-editable="0"] { cursor: pointer; }
.agenda-block:hover { filter: brightness(.96); z-index: 2; }
.agenda-cont-top { border-top-left-radius: 0; border-top-right-radius: 0; }
.agenda-cont-bottom { border-bottom-left-radius: 0; border-bottom-right-radius: 0; }
.agenda-title { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.agenda-time { font-size: .7rem; opacity: .8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.agenda-handle { position: absolute; left: 0; right: 0; height: 7px; cursor: ns-resize; z-index: 2; }
.agenda-handle-start { top: -1px; }
.agenda-handle-end { bottom: -1px; }
.agenda-handle:hover { background: rgba(92, 124, 250, .35); }
.agenda-preview { position: absolute; left: 2px; right: 2px; z-index: 3; pointer-events: none; box-sizing: border-box;
    border: 2px dashed #5c7cfa; border-radius: 6px; background: rgba(92, 124, 250, .16); padding: 1px 6px;
    font-size: .75rem; font-weight: 700; color: #364fc7; }
.body--dark .agenda-preview { color: #dbe4ff; }
.agenda-source { opacity: .35; }
body.agenda-dragging, body.agenda-dragging * { cursor: grabbing !important; user-select: none !important; }
.agenda-now { position: absolute; left: -4px; right: 0; height: 2px; background: #fa5252; z-index: 2;
    pointer-events: none; }
.agenda-now::before { content: ""; position: absolute; left: -2px; top: -3px; width: 8px; height: 8px;
    border-radius: 999px; background: #fa5252; }
@media (max-width: 799px) {
    .zoom-layout { flex-direction: column; }
    .zoom-tasks { flex: none; max-height: 32vh; }
    .agenda { min-height: 640px; }
    .agenda-columns { gap: 6px; }
    .agenda-hours { width: 32px; }
}

/* Éditeur d'événement : pastilles de couleur. */
.calendar-swatch { width: 22px; height: 22px; border-radius: 999px; cursor: pointer;
    box-shadow: inset 0 0 0 1px rgba(0, 0, 0, .15); }
.calendar-swatch:hover { transform: scale(1.12); }
.calendar-swatch-on { outline: 3px solid #5c7cfa; outline-offset: 2px; }
/* Infobulles sur plusieurs lignes (texte avec retours à la ligne). */
.q-tooltip { white-space: pre-line; }
@media (max-width: 599px) {
    .calendar-cell { min-height: 52px; padding: 2px; }
    .calendar-chip { padding: 0 4px; font-size: .65rem; line-height: 1rem; }
}

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
