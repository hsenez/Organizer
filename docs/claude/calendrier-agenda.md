# Notes pour Claude — Calendrier et événements (agenda)

Complément de `CLAUDE.md` (à la racine), à lire avant de modifier ce domaine.

## Calendrier (chantier « événements », en cours)

- Page `ui/pages/calendar.py` (`CalendarView`, `app_frame(..., wide=True)`) : grille CSS `.calendar`
  (7 colonnes, lignes `minmax(0, 1fr)` → la grille remplit la hauteur, `page-fill-grow`), styles dans
  `theme.py`. Grille calculée par `rules.month_grid(year, month)` (semaines complètes lundi → dimanche),
  navigation par `rules.shift_month`. Mois initial : `?month=AAAA-MM` (`parse_month`), sinon `ctx.today()`.
- Contenu des cases : `rules.calendar_days(tasks, today)` (jour d'affichage : échéance, ou **aujourd'hui**
  pour une tâche en retard — `rules.is_overdue` ; annulées exclues ; ordre retards / urgence / heure /
  titre). Pastilles `calendar-chip` (fond = `Urgency.meta.color`, texte `theme.readable_text`),
  `calendar-chip-overdue`, `calendar-chip-done` ; pourtour = importance (`_ring`,
  `theme.IMPORTANCE_CHIP_BORDER_PX`) + `box-shadow` inset clair (à garder dans l'animation d'alerte).
- Glisser-déposer : pastilles `draggable`, cases `drop_zone(cell, "day:<AAAA-MM-JJ>")`, colonne
  `drop_zone(panel, "undated")` ; `CalendarView._dropped` → `ds.tasks.update(TaskPatch(due_date=…))`
  (`self.tasks` = tâches de la dernière lecture, mis à jour après chaque dépôt). `_load()` lit une fois :
  jours + sans échéance.
- Colonne « Sans échéance » : `resizable(panel, "undated", side="left")` + `resize_handle(side="left")`
  (`resize.js` : `data-resize-side="left"` inverse le sens) ; `Resizer` de la page marqué `resizer` ;
  repliée = bande `calendar-undated-collapsed` (marqueur `calendar-undated-expand`), bouton
  `calendar-undated-collapse`. Préférences : `CalendarPrefs` / `read_prefs` (tolérant). Filtres : préférence `view:calendar`
  `{"tasks": bool, "scope": "all|mine|shared"}` lue par `read_prefs` (tolérante).
- Sélection : `select(day)` change les classes sans reconstruire la grille (`self.cells`). Case agrandie :
  `ui.dialog` `maximized` + transition `scale` ; `ZOOM_ORIGIN_JS` (js_handler du `dblclick`) pose
  `--calendar-zoom-x/y` sur `<html>` → `transform-origin` de `.q-dialog__inner` : l'agrandissement part de
  la case. Contenu `ui.refreshable`, relu par `ctx.on_refresh` s'il est ouvert.
- Marqueurs de test : `calendar-prev`, `calendar-next`, `calendar-today`, `calendar-title`,
  `calendar-day-<AAAA-MM-JJ>` (une case par jour affiché), `calendar-task-<id>` (pastille),
  `calendar-scope`, `calendar-show-tasks`, `calendar-show-events`, `calendar-view`, `calendar-zoom`,
  `calendar-zoom-close`, `calendar-undated`, `calendar-event-<id>` (bande ou étiquette). Les tâches sont
  masquées par défaut : `show_calendar_tasks(sv)` dans les tests. La pastille écoute
  `dblclick.stop` : dans le simulateur, `trigger("dblclick.stop")` (nom exact de l'écouteur).
- Noms des jours / mois : `ui/format.py` (`DAYS`, `MONTHS` abrégés ; `DAY_NAMES`, `MONTH_NAMES` complets).

## Événements (agenda)

- **Héritage** : `models.ItemBase` / `LinkBase` (SQLModel sans table : champs communs) → `Task`, `Event`,
  `TaskLink`, `EventLink` ; `schemas.ItemOut` → `TaskOut`, `EventOut` ; `services/items.py`
  `ItemService` (projet, tags avec préservation des tags privés, liens, copie de tags / liens d'un type à
  l'autre, lecture groupée) → `TaskService`, `AgendaService`. Une sous-classe déclare `model`,
  `tag_model`, `share_model`, `link_model`, `fk` (`task_id` / `event_id`), `_get` (visible) et
  `_get_editable`. `LinkOut` porte `task_id` **ou** `event_id`.
- Nommage : service `sv.agenda` / `ds.agenda` (`AgendaService`, `RemoteAgenda`), routes `/api/v1/agenda`
  — `events` désigne déjà le bus temps réel (`core/events.py`, `ServiceContext.events`) et
  `/api/v1/events` le flux SSE. La table reste `event`.
- Dates **locales** `start_date` / `start_time` / `end_date` / `end_time` (pas de `datetime` : pas de
  fuseau à gérer) ; `start_time is None` ⇔ toute la journée (`EventOut.all_day`). Toujours passer par
  `rules.event_span` pour normaliser. Jours touchés : `rules.event_days`.
- Compte désactivé : `ItemService._inactive_owners` / `_shared_visible_clause` (événements et notes : public
  et lecture seule ignorés si le propriétaire est désactivé) ; tâches : `TaskService._can_delete` et
  `can_delete` acceptent un propriétaire désactivé ; `NotificationService._visible` suit la même règle.
  Tests : `tests/test_deactivated.py`.
- Droits : `_get` (voir : propriétaire, partage, public), `_get_editable` (modifier **et supprimer** :
  propriétaire ou `EventShare.can_edit`), `_get_owned` (partager, rendre public, transformer).
- Pièces jointes : `AttachmentService.upload_event` ; `_can_read` parcourt les liens des tâches **et** des
  événements. Suppression / fusion de tags et de projets : traiter `TaskTag` **et** `EventTag`, `Task`
  **et** `Event`.
- Tests : `tests/test_agenda.py` (services), `test_client.py::test_agenda_through_api_matches_local`.
- Calendrier, grille : **placement explicite** de chaque case (`grid-row` / `grid-column`) — sinon le
  placement automatique de la grille contournerait les bandes. Bandes = éléments de la grille par-dessus
  les cases (`--lane`), pastilles décalées sous les bandes (`--lanes` par case) ; `body.dnd-active` coupe
  les clics sur les bandes pendant un glisser (la case dessous reçoit le dépôt). Vues : `prefs.view`
  (`month` : `year` / `month` ; `week` / `six` : `anchor` = lundi). `view:calendar` =
  `{tasks, events, view, undated}` (`CalendarPrefs`) ; « De qui ? » (`CalendarView.scope`) **n'est pas
  mémorisé** (toujours « Tous » à l'ouverture : demandé par l'utilisateur).
- Vue d'un jour (`_zoom_content`) : `components/agenda.py` (`Agenda`, `agenda_columns`) + `agenda.js` :
  colonnes `[data-agenda-track]` (`data-agenda-offset` 0 / 720), blocs `[data-agenda-event]`
  (`data-start` / `data-end` en minutes depuis minuit, `data-editable`), poignées
  `[data-agenda-handle=start|end]` ; le JS fait tout le geste (aperçu `.agenda-preview`) et n'envoie que
  `change {id, start, end}` ; `create` / `slot {minute}` pour le double-clic / clic droit. Disposition :
  `rules.agenda_layout` (`AgendaBlock`), pas `rules.AGENDA_STEP`. Marqueurs : `agenda`, `agenda-col-0|1`,
  `agenda-event-<id>`, `zoom-event-<id>` (journée entière), `zoom-tasks`, `zoom-prev`, `zoom-next`,
  `agenda-menu`, `agenda-new-event`. ⚠️ `ui.menu_item` n'a pas de `set_text` : mettre un `ui.label` dedans.
- Sélection d'un élément (`CalendarView.selected_item`, `_selectable` : `click.stop`, classe
  `calendar-item-selected`) ; `ui.keyboard` de la page (marqueur `calendar-keys`) : Suppr / ⌫ →
  `delete_selected`. Tests : helper `press(user, "calendar-keys", "Delete")`.
- Pictogrammes de partage : `components/ownership.py` (`ownership_emoji`, `ownership_text`,
  `ownership_chip`) d'après `rules.ownership` / `Ownership` (enums) ; noms via `ctx.user_names()` (gardés
  30 s). À utiliser pour tout nouvel affichage de tâche / d'événement.
- Glisser un événement : `draggable_event` (`data-dnd-kind="event"`) ; `dnd.js` émet `drop` avec `kind`,
  `UiContext.handle_drop` aiguille vers `ctx.event_drop_handler`. `refusal()` (JS) refuse tout rattachement
  avec un événement (règle propre au JS : le serveur ne rattache que des tâches).
- Calendrier : sélection `self.selection = (premier, dernier)` ; `day_select.js` (`DaySelect`, marqueur
  `day-select`, événement `range`) surligne pendant le clic-glisser et absorbe le clic final ; cases
  `data-cal-day`. Clic droit : `contextmenu` sur la case (`_context`) + `ui.context_menu` de la grille
  (marqueurs `calendar-menu`, `calendar-new-event`, `calendar-new-task`).
