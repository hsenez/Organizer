# CLAUDE.md — Consignes pour Claude sur le projet Organizer

## Le projet

Organiseur de tâches multi-utilisateurs : serveur NiceGUI/FastAPI sur Raspberry Pi (port 2603) + interface web
(responsive, téléphone) + client bureau (fenêtre native pywebview, Linux/Windows) qui passe par l'API REST.
Référence fonctionnelle complète : **`specifications.md`**.

## Règles de travail (demandées par l'utilisateur)

- **Langue** : échanges, commentaires et docstrings en français (avec accents). Identifiants de code en anglais.
- **Git** (depuis le 9/11/2026) : travailler sur la branche **`cloclo`** ; y **commiter et pousser
  systématiquement** sur le NAS (`git push origin cloclo`, pas GitHub) après chaque changement terminé et vérifié (format, lint,
  tests verts), sans demander : c'est ce que l'utilisateur teste sur le Pi (`deploy/install_test.sh`).
  **Jamais rien sur `main` sans son approbation explicite** (fusion de `cloclo`, push, étiquette).
- **Documentation** : `specifications.md`, `CLAUDE.md` et `README.md` sont **mis à jour à chaque changement**
  (fonctionnalité, architecture, dépendance, commande). Ajouter une ligne dans l'historique de
  `specifications.md`.
- **`TODO.md`** : sujets ouverts hors feuille de route (demandes de l'utilisateur à approfondir, points
  relevés en cours de route). Y ajouter ce qui est reporté ; retirer ce qui est fait.
- **Dépendances** : toujours dans le venv `.venv/`. Annoncer à l'utilisateur toute nouvelle bibliothèque, puis
  l'ajouter avec sa version au bon fichier `requirements*.txt`.
- **Tout en Python**, sauf le strict nécessaire en JS/CSS pour l'interface (éditeur markdown, glisser-déposer),
  livré avec le projet (pas de CDN à l'exécution : le Pi peut être sans Internet). Réutiliser en priorité ce
  que NiceGUI embarque déjà (CodeMirror 6, Quasar…).

## Contraintes techniques

- **Python 3.11 sur le Pi** (le poste de dev est en 3.14) : pas de syntaxe ni d'API > 3.11
  (pas de `type X = …`, pas de génériques PEP 695 `def f[T]()`, pas de `itertools.batched`, pas de f-strings
  réutilisant le même guillemet à l'intérieur…). Vérifier avec `ruff check` (`target-version = "py311"`).
- **NiceGUI 4.0** : version récente, vérifier l'API réelle dans `.venv/lib/python3.14/site-packages/nicegui/`
  plutôt que de se fier à la mémoire.
- Le code UI ne parle **qu'à l'interface `DataSource`** (`LocalDataSource` côté serveur,
  `RemoteDataSource` côté client bureau). Aucune requête SQL ni appel httpx dans `organizer/ui/`.
- Libellés, emojis, couleurs et infobulles des niveaux / statuts / types : **une seule source**,
  `organizer/core/enums.py`.
- La logique métier vit dans `organizer/core/services/` (avec accès base) et `organizer/core/rules.py`
  (fonctions pures, réutilisables par l'UI pour réagir sans aller-retour serveur). Elle est **couverte par
  des tests**.
- Interface en français ; textes regroupés pour permettre une traduction future.

## Architecture du cœur (étape 1)

- **Services** : `Services(engine, actor)` regroupe `users`, `projects`, `tags`, `tasks`, `undo`. Chaque
  méthode publique = une transaction (`UnitOfWork`). Les services renvoient des schémas `*Out` (Pydantic),
  jamais des objets ORM.
- **Annuler / rétablir** : toute opération ouverte avec `self.uow(label=...)` est enregistrée
  automatiquement (événement SQLAlchemy `after_flush`, tables marquées `__undoable__ = True`). Règles :
  - toujours modifier les données **via l'ORM** dans une UoW avec libellé (sinon rien n'est annulable) ;
  - **pas de relation many-to-many ORM** : manipuler les tables de liaison (`TaskTag`, `TaskShare`) comme
    des objets, pour que l'historique les voie ;
  - une nouvelle table annulable : `__undoable__ = True` + l'ajouter à `UNDOABLE_TABLES` (`models.py`) ;
  - `group_key` : fusionne les modifications rapides successives (sauvegarde automatique).
- **Patch** : seuls les champs explicitement fournis s'appliquent (`model_fields_set`) ; `None` explicite
  efface un champ facultatif.
- **Dates-heures** : UTC **avec fuseau** (`models.utcnow()`), exigé par SQLModel 0.0.48 ; les échéances sont
  des `date` locales.
- **Date du jour injectable** (`today=`) pour les tests : ne jamais appeler `date.today()` dans un service,
  utiliser `self.today()`.
- Un projet / tag **privé** d'un autre utilisateur est invisible sur une tâche partagée et **préservé** quand
  quelqu'un d'autre modifie les tags de cette tâche.

## Architecture du serveur (étape 2)

- `organizer/server/app.py` : `build()` installe tout sur l'application NiceGUI (`install()` de `wiring.py`
  + `register_pages()`), puis `main()` appelle `ui.run()`. Les tests de l'API utilisent `create_api_app()`
  (FastAPI nue, même `install()`).
- **Authentification** : `AuthMiddleware` (`security.py`) résout le cookie ou le jeton Bearer une fois par
  requête → `request.state.auth` (`ResolvedSession` ou None). Dans l'API : dépendances `get_user`,
  `get_admin`, `get_services` (`api/deps.py`). Dans une page : `guard(request)` renvoie une redirection
  si besoin.
- Une page NiceGUI **ne peut pas poser de cookie** : connexion = ticket à usage unique (`TicketStore`) puis
  redirection vers `/auth/complete`, route HTTP qui pose le cookie.
- Les pages s'enregistrent via `register_pages()` (pas de `@ui.page` à l'import) : le simulateur de test
  NiceGUI réinitialise l'application entre deux tests et doit pouvoir les réenregistrer.
- Routes API en `def` synchrones (FastAPI les exécute dans un thread : SQLite synchrone sans bloquer la boucle).
- Erreurs métier (`OrganizerError`) → JSON `{"detail": …}` avec le code HTTP de l'exception.

## Architecture de l'interface (étape 3)

- Pages de l'application dans `organizer/ui/pages/`, enregistrées par `register_app_pages(make_context)` :
  la fabrique reçoit la requête et renvoie un `UiContext` (ou une redirection). Le serveur fournit
  `server_context` (`server/pages.py`) ; le client bureau fournira la sienne.
- **Éditeur** : `ctx.editor` = `Editor` (`components/item_editor.py` : le panneau, l'envoi de fichiers et
  l'aiguillage) ; `open(id)` / `open_new(**draft)` (tâche), `open_event(id)` / `open_new_event(**draft)`.
  Base `ItemEditor` (titre, projet, tags, liens, pièces jointes, notes, brouillon, `_save`) et sous-classes
  `TaskEditor` (`task_editor.py`) et `EventEditor` (`event_editor.py`), qui partagent le **même** dialogue
  (`self.dialog`, `self.body`, `self.upload` viennent de l'`Editor`). Brouillon : `self.draft` = champs du
  schéma de création, `self.item` = objet fictif d'id 0 (`_draft_out()`) ; création au premier titre. Pas
  de création « à vide » en base.
  - Bascule (`Editor.switch`, marqueur `editor-kind`) : brouillon → `common_draft()` + `stash` des champs
    propres ; existant → `convert_from` (`ds.agenda.from_task` / `to_task` avec `extra` : champs gardés,
    même transaction donc **un** Ctrl+Z). Après un `_build()` déclenché par un élément de l'éditeur, cet
    élément est supprimé : un `ui.notify` doit alors se faire `with self.dialog:`.
  - `?event=<id|new>` : `app_frame(..., open_event=…)`.
- **Éditeur markdown** (`components/markdown_editor.py` + `.js`) : composant Vue maison autour de
  CodeMirror 6 **tel que fourni par NiceGUI** (`import * as CM from "nicegui-codemirror"`, importer
  `nicegui.elements.codemirror` côté Python enregistre ce paquet). Le module `lang-markdown` (GFM, keymap des
  listes) est un fichier haché du paquet : `markdown_module()` le retrouve **par son contenu**. Si NiceGUI
  change de version, vérifier qu'il est toujours trouvé (le serveur lève une erreur explicite sinon).
  - Rendu en direct = `ViewPlugin` qui recalcule des décorations (marques, remplacements, widgets case à
    cocher / puce) à partir de `syntaxTree` à chaque changement de texte, de sélection ou de focus.
  - Synchronisation : le JS émet `update:value` (texte complet, 0,4 s après la dernière frappe, et au
    `blur`) ; `LOOPBACK = False`. L'éditeur de tâche enregistre (throttle 1,5 s, `blur`, fermeture).
  - Le JS arrête la propagation des touches (sauf Échap) : sinon `ui.keyboard`, qui ne reconnaît que
    `input` / `textarea`, intercepterait Ctrl+Z dans une zone `contenteditable`.
  - Liens : `mousedown` ouvre (émet `open-link`) sauf si la sélection touche déjà le lien (édition) ;
    Ctrl/⌘+clic ouvre toujours ; `openTarget()` dédoublonne (double-clic = 2 clics + dblclick).
  - Le simulateur de test ne peut pas taper dans ce composant : fixer `.value` puis `trigger("blur")`.
  - Tests manuels dans Firefox headless : ajouter `user_pref("focusmanager.testmode", true);` au profil,
    sinon `view.hasFocus` reste faux (fenêtre jamais active) et la syntaxe ne se révèle jamais ; ouvrir un
    onglet fait aussi perdre le focus à la page.
- **`UiContext`** (`ui/context.py`) : `ds` (DataSource), `refresh()` (tous les blocs `ui.refreshable` abonnés
  via `on_refresh`), `call()` / `attempt()` (erreur métier → toast rouge), `undo()` / `redo()`, `editor`.
- Appels à la DataSource **synchrones** dans les gestionnaires d'événements (SQLite local rapide ; client
  bureau mono-utilisateur).
- Couleurs : `theme.color_name(member)` → nom Quasar (`imp3`, `urg0`, `st2`, `kd1`), déclarés via
  `ui.colors(**custom)` dans `apply_theme()`. Toute nouvelle couleur de statut / niveau vient de `enums.py`.
- Pièges NiceGUI rencontrés :
  - `element.tooltip(...)` **ajoute** une infobulle à chaque appel : pour un texte qui change, créer
    `ui.tooltip()` une fois et faire `set_text` ;
  - les classes Tailwind `dark:` ne s'appliquent pas aux fonds Quasar (`q-drawer`…) : passer par le CSS
    `.body--dark …` dans `theme.py` ;
  - dans un `ui.dialog` en `position=right`, Quasar ajoute un padding : neutralisé en CSS ;
  - `ui.upload` est masqué ; le bouton ouvre son sélecteur par `open_file_picker` (`components/file_drop.py`,
    **`js_handler`**). ⚠️ Jamais `upload.run_method("pickFiles")` depuis un gestionnaire Python : l'aller-retour
    par le serveur perd le geste de l'utilisateur, et WebKitGTK (fenêtre du client bureau), Safari, Chrome
    refusent alors d'ouvrir le sélecteur, en silence (seul Firefox laisse passer : bug rencontré).
  - Dépôt de fichiers du système : `FileDrop(ctx)` (`file_drop.js`, un par page, créé par `app_frame`, marqué
    `file-drop` ; gabarit avec `<slot>` : il contient son propre `ui.upload`, marqué `card-upload`).
    Cibles : `file_drop_zone(element, upload)` (`data-file-drop` = id du `ui.upload`, qui reçoit les fichiers
    par `addFiles`) ; sinon une carte `data-dnd-task` → événement `card-files` (tâche visée), le serveur
    répond `flush` et les fichiers partent par `card-upload`. Fichiers connus seulement par `file://`
    (`text/uri-list` sans `files`) → événement `paths`, lus sur le poste si `ds.is_desktop`. Hors cible,
    `dropEffect = "none"` (Chromium n'émet alors pas `drop` ; rien ne s'ouvre). `reusable_upload` : `reset` à
    l'événement `finish`, sinon QUploader refuse en silence un fichier déjà envoyé. Éditeur : `self.upload`
    permanent (hors de `self.body`), zone = la carte de l'éditeur.
  - Fenêtre du client bureau (WebKitGTK) : un fichier glissé depuis Dolphin arrive à la page avec les types
    `text/uri-list`, `text/html`, **0 fichier** et une adresse vide (WebKit masque les `file://`). Les
    adresses sont captées dans le sous-processus de la fenêtre (`client/window.py`, signal GTK
    `drag-data-received` de `BrowserView.instances[uid].webview`) et relayées par
    `window.organizerNativeDrop(uris)` ; `file_drop.js` les attend 0,8 s au plus au moment du dépôt (prop
    `web` : pas d'attente dans un navigateur).
  - Vrai glisser de fichier dans Chromium (Vivaldi installé) : `vivaldi --headless=new
    --remote-debugging-port=…`, CDP `Input.dispatchDragEvent` (`dragEnter` / `dragOver` / `drop`, `data.files`
    = chemins). Un glisser natif depuis Dolphin vers la fenêtre GTK ne se simule pas ici.
  - ⚠️ Arrêter ses serveurs de test **par PID** : la fenêtre du client bureau de l'utilisateur est un
    sous-processus dont la ligne de commande contient aussi `run_client.py` ; la tuer ferme son client.
  - Vérifier un changement de ce genre dans **WebKitGTK** hors écran : `Gtk.OffscreenWindow` + `WebKit2.WebView`
    (variables `WEBKIT_DISABLE_COMPOSITING_MODE=1 WEBKIT_DISABLE_DMABUF_RENDERER=1`), signal
    `run-file-chooser` → `request.select_files([...])` ; dépôt simulé par `DragEvent` + `DataTransfer`. Le client
    en `--browser` sur un port fixe (`ORGANIZER_CLIENT_LAUNCH`, `ORGANIZER_CLIENT_PORT`, `client.json` avec
    jeton) se charge alors à `http://127.0.0.1:<port>/?launch=<secret>`.
- **Tests d'UI** : le simulateur ne propage pas les clics aux parents et ne voit pas le contenu d'un menu
  fermé → poser des `.mark(...)` sur les éléments cliquables (cartes `task-card-<id>`, entrées de menu,
  options des curseurs `slider-importance-4`…) et ouvrir les menus avec `open_menu()` dans les tests.
- **Vérification visuelle** : Firefox headless piloté en WebDriver BiDi (aiohttp) avec un serveur de démo
  et un ticket de connexion (scripts de travail hors dépôt) ; à refaire après tout changement visuel notable.
  Capture simple : cookie de session inséré dans `cookies.sqlite` d'un profil (⚠️ Firefox 159 : colonne
  `expiry` en **millisecondes**), puis `firefox --headless --profile … --screenshot f.png <url>`.
- ⚠️ Tout script de débogage lancé avec la fixture `user` doit importer la fixture `data_dir` de
  `tests/test_pages.py`, sinon il écrit dans le vrai dossier `data/`.

## Étape 5 : liste, recherche, réglages

- **`AccountService`** (`core/services/account.py`) : profil, mot de passe, appareils, comptes (admin),
  préférences. Utilisé par l'API (`get_account`) **et** par l'interface (`ds.account`) : une seule logique.
- **Préférences d'affichage** : table `user_pref` (clé, valeur JSON) — ex. `view:tasks`, `view:search`
  (`{"filter", "sort", "group"}`). Lire avec tolérance (`_validate` dans `task_list.py`) : une préférence
  enregistrée par une ancienne version ne doit jamais casser la page.
- **Schéma de la base** : `create_all` crée les **nouvelles tables** ; une **colonne** ajoutée à une table
  existante passe par une **migration** (`core/migrations.py`, voir « Migrations » plus bas).
- `FilterBar` (`components/filter_bar.py`) et `TaskListView` (`components/task_list.py`) sont réutilisables
  (kanbans / matrice à l'étape 6).
- Ctrl+K : `preventDefault` posé par un petit script (`app_frame`) car Firefox l'utilise pour sa barre de
  recherche ; `ui.keyboard` ne peut pas empêcher l'action du navigateur.
- Thème : `ctx.dark` (`ui.dark_mode`) créé par `app_frame` d'après `user.theme` ; les réglages le changent
  à chaud. Après une mise à jour du profil, remplacer `ctx.ds.user`.
- Couleur d'un nouveau tag : `TagIn.color = None` → `TagService.suggest_color(avoid)` /
  `rules.pick_distinct_color` (palette de 24 teintes, distance CIELAB, couleurs de la tâche éditée en
  priorité via `TagIn.avoid_colors`, qui n'est pas enregistré).
- Affichage des tags : `components/tag_chips.py` (`tag_chip` pour les cartes, `color_tag_select` pour un
  `ui.select` : slots Quasar `selected-item` et `option`, couleurs retrouvées par le **libellé** de
  l'option, car NiceGUI envoie `{value: index, label}` au navigateur).
- Tests d'UI : un panneau replié (filtres) rend ses éléments invisibles pour le simulateur → le déplier ;
  pour un `ui.select`, `set_value` dans `with user.client:` (helper `select_value`).

## Étape 6 : boards et glisser-déposer

- **Boards** : `BoardService` (`core/services/boards.py`). Le propriétaire gère (nom, colonnes, partage) ;
  les membres déplacent / ajoutent / retirent des cartes. La visibilité des tâches posées sur un board
  partagé est dans `TaskService._visible_clause` (et leurs sous-tâches via le parent). Supprimer une tâche
  supprime ses `BoardCard` (`_delete_row`).
- **Glisser-déposer** : `components/dnd.js` (un composant `DragDrop` par page, créé par `app_frame`, marqué
  `dnd`). Les éléments se déclarent par attributs : `draggable(element, task)` (`data-dnd-task`,
  `-parent`, `-has-subtasks`, `-title`) et `drop_zone(element, clé, accept=…, denied=…)`. Une page
  enregistre `ctx.drop_handler(task_id, zone, index)` ; le rattachement (événement `attach`) est géré par
  `UiContext.attach` partout.
  - Clés de zone : `status:<valeur>`, `due:<tranche>`, `kind:<valeur>`, `project:<id|0>`, `col:<id>`,
    `q:<quadrant>`, `cell:<importance>:<urgence>`.
  - Doigt : événements `touch` (qui permettent de bloquer le défilement) ; à défaut, `pointer`. ⚠️
    `'ontouchstart' in window` peut être faux alors que les événements `touch` arrivent (Firefox de bureau) :
    les deux chemins doivent rester idempotents.
  - Après un glisser, le clic qui suit est absorbé (sinon la carte lâchée ouvrirait l'éditeur).
  - Les règles de rattachement sont dupliquées en JS (`refusal`) pour la surbrillance : les garder alignées
    avec `rules.attach_refusal_reason`.
- **Kanbans (v1.4)** : `app_frame(..., wide=True)` → contenu pleine largeur / pleine hauteur (CSS
  `page-fill*` ; le dernier enfant porte `page-fill-grow`). Colonnes repliables (`collapsed`) et
  redimensionnables (`components/resizer.py` + `resize.js` : `data-resize-key` / `data-resize-handle`,
  événement `resize {key, width}`), mémorisées dans `board:<clé>` avec `filter` et `hide_done`.
- **Reclassement** : boards prédéfinis triés par `TaskSort(key="urgency")` = urgence, puis `TaskOut.rank`
  (table `task_rank`, annulable, absente = 0). `drop_zone(..., ordered=True)` affiche un repère
  d'insertion ; `KanbanView._dropped` envoie l'ordre de la colonne (`self.order`) à `ds.tasks.move(id, patch,
  order)` qui applique le patch puis `rules.rank_drop` (urgence bornée par les voisines, rang au milieu, ou
  renumérotation du groupe si rangs égaux), en **une** entrée d'historique. Dans sa propre colonne : pas de
  patch, juste le reclassement (même dans une colonne qui refuse les dépôts venus d'ailleurs).
- `refreshable.refresh()` (NiceGUI 4) s'exécute **en tâche de fond** : dans un test, attendre (`settle()`,
  `should_see`) avant une action qui dépend de la page reconstruite.
- Tests : le simulateur ne sait pas glisser → `user.find(marker="dnd").trigger("drop", {...})` ou
  `trigger("attach", {...})`. Le geste réel se vérifie dans Firefox (BiDi, `input.performActions` souris et
  `pointerType: "touch"`) ; ne pas faire défiler la page entre la mesure des positions et le geste.

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
  `calendar-scope`, `calendar-show-tasks`, `calendar-zoom`, `calendar-zoom-close`, `calendar-undated`. La pastille écoute
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
- Droits : `_get` (voir : propriétaire, partage, public), `_get_editable` (propriétaire ou
  `EventShare.can_edit`), `_get_owned` (supprimer, partager, rendre public, transformer).
- Pièces jointes : `AttachmentService.upload_event` ; `_can_read` parcourt les liens des tâches **et** des
  événements. Suppression / fusion de tags et de projets : traiter `TaskTag` **et** `EventTag`, `Task`
  **et** `Event`.
- Tests : `tests/test_agenda.py` (services), `test_client.py::test_agenda_through_api_matches_local`.
- Calendrier : sélection `self.selection = (premier, dernier)` ; `day_select.js` (`DaySelect`, marqueur
  `day-select`, événement `range`) surligne pendant le clic-glisser et absorbe le clic final ; cases
  `data-cal-day`. Clic droit : `contextmenu` sur la case (`_context`) + `ui.context_menu` de la grille
  (marqueurs `calendar-menu`, `calendar-new-event`, `calendar-new-task`).

## Étape 7 : client bureau

- `organizer/client/` : **aucune** dépendance au serveur (`organizer.server`) hors tests. `app.py`
  (`DesktopClient` : `/connect`, `context()` = fabrique des pages sur `RemoteDataSource`, onglet de
  réglages via `UiContext.extra_settings`, `LaunchGuard`, notifier, `main()`), `api.py` (`ApiClient`,
  `error_from` : code HTTP → erreur métier ; `ServerUnreachable` / `NotAuthenticated` dans `core/errors.py`),
  `remote.py`, `config.py`, `system.py`, `notifications.py`.
- **Contrat** : chaque méthode de service utilisée par l'UI doit exister dans `remote.py` avec la même
  signature. Ajouter une méthode de service utilisée par l'UI = ajouter sa route API **et** sa version
  distante **et** un test dans `tests/test_client.py` (comparaison avec le service local quand c'est possible).
  Liste des appels de l'UI : `grep -rhoE "ds\.[a-z_]+\.[a-z_]+" organizer/ui | sort -u`.
- `ConfigStore.save` : fichier temporaire unique (`mkstemp`, 600) + verrou — plusieurs fils enregistrent
  `client.json` (bascule réseau local en arrière-plan).
- Envoi : `_sent()` = `exclude_unset` (patchs partiels, héritage des sous-tâches) ; `ApiClient.call(...,
  json=None)` envoie `null` (``NO_BODY`` = pas de corps).
- Liens côté bureau : `open_link` (task_editor) délègue à `ds.open_url / open_path / open_attachment` quand
  `ds.is_desktop` ; erreurs (fichier absent) → toast via `ctx.call`.
- Fenêtre native : NiceGUI lance pywebview dans un **sous-processus qui réimporte** `run_client.py`
  (garde `__main__` / `__mp_main__`) ; secret et port passent par l'environnement (`ORGANIZER_CLIENT_LAUNCH`,
  `ORGANIZER_CLIENT_PORT`) pour être identiques ; `app.native.window_args["url"]` = URL de départ avec le
  secret ; GTK forcé sous Linux (`start_args["gui"]`), sinon pywebview tente Qt.
- Tests des pages du client : `tests/test_client_pages.py` (marqueur `nicegui_main_file("tests/client_main.py")`,
  serveur de test en mémoire passé par `tests/client_harness.HTTP`, `ORGANIZER_CLIENT_DIR` fixé par une
  fixture autouse **avant** le simulateur).
- Essais manuels sans rien ouvrir sur le bureau : `PATH=<faux xdg-open>:$PATH BROWSER="<script> %s"`
  `DBUS_SESSION_BUS_ADDRESS=unix:path=/nonexistent ORGANIZER_CLIENT_DIR=<dossier> run_client.py --browser`.
- **Arrière-plan / instance unique** : `launcher.py` (ligne de commande, **sans importer NiceGUI** avant de
  savoir s'il faut démarrer : la transmission doit rester ≈ 0,07 s) → `instance.forward` → route
  `/_organizer/control/<action>` (secret dans l'en-tête, exemptée du `LaunchGuard`) → `DesktopClient.control`.
  `window.py` tourne **dans le sous-processus de la fenêtre** (`start_args["func"]`) : fermer = cacher
  (`events.closing` renvoie False), méthodes `organizer_present` / `organizer_quit` ajoutées à la fenêtre et
  appelées par `nicegui.native.native.method_queue` (elles doivent renvoyer None). `app.shutdown()` passerait
  par la fermeture annulée : pour quitter, toujours `organizer_quit`.
- **Latence** : chaque appel de l'UI est une requête bloquante (≈ 20 ms en local, ≈ 300 ms par Cloudflare).
  `client/cache.py` (`RemoteCache`, attaché à `ApiClient.cache`, partagé par les copies `with_headers`) garde
  projets, tags, boards (oubliés si leurs tables changent : `DesktopClient._dispatch_change` →
  `cache.on_change`), utilisateurs, `me`, préférences (délai court, pas d'événement), état d'annulation
  (`UNDO_KEY`, rempli par l'en-tête `X-Organizer-Undo` que `security.add_undo_status` joint aux écritures
  en Bearer). `cache.on_write(path)` à chaque écriture du poste (table `WRITES` ; annuler / rétablir oublie
  projets, tags, boards). Les valeurs rendues sont des copies (préférences : copie profonde). Une méthode de
  `remote.py` qui lit une donnée gardée en mémoire doit déclarer ses tables. L'éditeur appelle
  `_page_changed()` (rafraîchissement **léger** : `ctx.refresh(light=True)` = boutons annuler / rétablir) ;
  la page est relue à la fermeture (`_on_hide`). Mesure : client lancé par un script qui enveloppe
  `ApiClient.request` (durée, chemin) + clics rejoués dans Firefox.
- **Réseau local automatique** : `server/local_access.py` (`instance_key` dans `<données>/instance.key`,
  `user_key`, `proof`, `local_urls`) + routes `api/local.py` (`/local-access` avec session ;
  `/local-access/proof` seulement si `security.is_local_address(client_ip)`). Client : `client/lan.py`
  (`LanSwitch` : `refresh_info`, `verify` **sans jeton**, `check`, `before_request` installé comme
  `Route.checker`, fil `tick` toutes les 60 s ; partage l'objet `DesktopClient.config` via
  `get_config` / `save_config`). `ApiClient.route` (`Route` : `server_url` / `base_url`, `http`, `local`,
  `use_local` / `use_server`), partagée par les copies `with_headers` ; `ApiClient.request` revient à
  l'adresse configurée et retente une fois si le réseau local échoue ; `live.py` revient aussi à l'adresse
  configurée sur coupure du flux. `DesktopClient.api` compare `route.server_url` (pas `base_url`, qui
  change). Tests : `tests/test_lan.py` (classe `Net` : deux `TestClient` vus depuis une IP publique / privée,
  serveur imposteur, réseau local coupé par `httpx.MockTransport`). Les tests de pages du client passent
  `install(lan=False)`.
- Indicateur de connexion : `UiContext.connection` (fonction → `Connection(local, tooltip, target)`) et
  `connection_live` ; `components/connection_badge.py` (`page_sticky` bas gauche, `ui.button(color=None)`
  sinon le fond reste « primary », `ui.tooltip` créé une fois + `set_text`, `ui.timer` si `connection_live`).
  Fourni par `server_context` (`web_connection` : `is_local_address(client_ip)`) et
  `DesktopClient.connection_info` (`desktop_connection`, `lan.is_lan_url`).
- Pages ouvertes mémorisées (`DesktopClient._pages`) : « nouvelle tâche » ouvre l'éditeur dans la page
  affichée (`_in_page`), sinon charge `/?task=new`.
- Linux : `GLib.set_prgname("organizer")` dans le sous-processus = identifiant Wayland = nom du `.desktop`.
- Raccourcis globaux : impossibles à capter soi-même sous Wayland → déclarés au bureau par
  `organizer/client/install.py`. KDE : composant `organizer.desktop`, actions `_launch` (ouvrir) et
  `new-task`, par `doRegister` + **`setShortcutKeys(..., SetPresent | NoAutoloading)`**. ⚠️ Avec
  `setForeignShortcutKeys`, le raccourci est enregistré et répond à `invokeShortcut` (D-Bus) mais Plasma 6
  l'ignore sur un vrai appui clavier (bug rencontré : Ctrl+Alt+O inopérant). `invokeShortcut` ne prouve donc
  rien : tester avec un **vrai appui**, par un clavier virtuel `uinput` (`/dev/uinput` accessible à
  l'utilisateur ; script Python stdlib : `UI_DEV_SETUP` / `UI_DEV_CREATE`, événements `EV_KEY` ; codes
  Ctrl 29, Alt 56, O 24, N 49). Le journal de KWin (`journalctl --user`) signale les actions inconnues
  (« failed to find an action matching… »). Fermer la fenêtre dans un test : script KWin filtré sur le
  **pid** du sous-processus (`workspace.windowList()`).
- **Windows** : `client/winshell.py` (`ctypes` seulement), lancé par `window._start_windows_shell` dans le
  sous-processus de la fenêtre : fil avec fenêtre cachée + boucle de messages ; raccourcis globaux par
  `RegisterHotKey` (le processus qui reçoit `WM_HOTKEY` a le droit de passer au premier plan), icône de zone
  de notification (`Shell_NotifyIconW`, menu Ouvrir / Nouvelle tâche / Quitter, remise sur `TaskbarCreated`),
  `bring_to_front` (`SetForegroundWindow`, repli `AttachThreadInput` ; jamais `Form.Activate` : hors du fil
  de l'interface). ⚠️ Les raccourcis ne sont **plus** posés sur les `.lnk` (`install.ps1` les efface) :
  l'Explorateur les garderait (`RegisterHotKey` → erreur 1409) et la chaîne lnk → nouveau `pythonw` →
  transmission → premier plan refusé échouait une fois sur deux. `instance.forward` appelle
  `AllowSetForegroundWindow(ASFW_ANY)`. Notifications : `Icon(path=organizer-256.png)`, sinon Windows
  affiche l'icône de Python (clé `HKCU\Software\Classes\AppUserModelId\Organizer`, écrite par
  desktop-notifier). Test réel : `keybd_event` simule l'appui (`tests/test_client_desktop.py`).
- Installeurs : `install/linux/install.sh`, `install/windows/install.ps1` (UTF-8 **avec BOM** et fins de
  ligne CRLF, sinon Windows PowerShell 5.1 abîme les accents). Python 3.11 à 3.13 sous Windows (pythonnet).
- Icône : `scripts/make_icons.sh <svg> <svg plein>` régénère `organizer/assets/` (rsvg-convert + ImageMagick,
  outils de développement seulement ; les fichiers produits sont versionnés).

## Étape 8 : temps réel, PWA

- **Temps réel** : `core/events.py` (`EventBus`, `ChangeEvent` = tables + auteur + origine). Publié par
  `UnitOfWork` après commit (`on_commit`, seulement si l'historique a capté des changements : opérations
  avec libellé) et par `UndoService`. `Services(..., events=, origin=)` ; `AppState.events`,
  `services_for(user, origin)`. Pages web : `server_context` crée une `LiveRefresh` (`ui/live.py`) abonnée
  au bus (désabonnement `client.on_delete`). API : `GET /api/v1/events` (SSE, `api/events.py`, `HEARTBEAT`) ;
  client bureau : `client/live.py` (`EventListener` dans un fil, `parse_sse`), origine envoyée par
  `RemoteDataSource(origin=)` (en-tête `X-Organizer-Origin`, `ApiClient.with_headers`).
- `LiveRefresh` : rafraîchit après 0,4 s, ignore les événements de sa propre origine, attend la fin d'un
  glisser (`dnd.js` émet `dragstate`, `UiContext.set_dragging`). L'éditeur de tâche n'est **pas** abonné à
  `refresh()` (il ne doit pas changer sous les doigts).
- **PWA** : `server/pwa.py` (routes manifeste + `sw.js` dans `wiring.install` ; `add_static` `/icons` et
  `add_head` en-têtes partagés dans `app.build`). Icônes : `organizer/assets/` (`ASSETS_DIR`, `FAVICON` dans
  `organizer/__init__.py`), régénérées par `scripts/make_icons.sh icone.svg icone-pleine.svg`.
- HTTPS : `Settings.ssl_cert` / `ssl_key` (`ORGANIZER_SSL_*`) → `ui.run(ssl_*)`, cookie `Secure` ; client :
  `ORGANIZER_CA_FILE`.
- `dnd.js` : défilement automatique près des bords (`autoScroll`, rAF) ; l'aimantation (`snap-x`) est
  coupée pendant un glisser (CSS `body.dnd-active *`), sinon chaque petit pas est annulé.
- Tests du temps réel : `tests/test_live.py` (vrai serveur uvicorn dans un fil pour le flux SSE) ; dans les
  tests de pages, `asyncio.sleep(0.6)` laisse passer le délai de `LiveRefresh`.

## Mise en ligne (Cloudflare Tunnel)

- Guide utilisateur : README, section « Accès depuis Internet » (tableau de bord vérifié en novembre 2026 ;
  à revérifier si Cloudflare change ses menus). Route du tunnel vers `http://127.0.0.1:2603`, jamais
  `localhost` (peut être `::1`, où le serveur n'écoute pas). Bot fight mode bloquerait le client bureau.

- `cloudflared` sur le Pi → `http://localhost:2603`. Uvicorn (`ProxyHeadersMiddleware`, actif par défaut,
  confiance à 127.0.0.1 / ::1) réécrit `request.client.host` et `request.url.scheme` d'après
  `X-Forwarded-For` / `-Proto` : **toujours** les utiliser pour l'IP et le protocole du visiteur, jamais
  `settings.https` (qui dit seulement si uvicorn a lui-même un certificat). `security.is_https(request)`.
- `SecurityHeadersMiddleware` (ASGI pur, pour laisser passer le SSE) : en-têtes ajoutés seulement s'ils sont
  absents de la réponse. Tests : `tests/test_proxy.py` passe par `uvicorn.Config(...).load()` pour avoir la
  même pile qu'en vrai (`TestClient(..., client=("127.0.0.1", port))` simule le proxy).
- Documentation de l'API refusée aux non connectés dans `AuthMiddleware` (`is_api_docs` lit `docs_url`,
  `redoc_url`, `openapi_url` sur l'application : NiceGUI les fixe dans `ui.run(fastapi_docs=True)`).
- Anti force brute (`LoginThrottle`) : niveau (IP, identifiant) remis à zéro par une réussite, niveau
  identifiant seul (toutes IP) **jamais** remis à zéro par une réussite. `check_credentials`
  (`server/api/auth.py`, partagé par l'API et la page /login) écrit chaque tentative dans le journal.
- Arrêt du serveur : `ui.run(timeout_graceful_shutdown=SHUTDOWN_GRACE_SECONDS)` (3 s) — sinon uvicorn attend
  la fin des flux SSE des clients bureau, qui ne finissent jamais, et `systemctl restart` durait 90 s (arrêt
  forcé par systemd). Mesure : serveur + `curl -N …/api/v1/events`, puis SIGTERM.
- Journal du serveur : `configure_logging()` (dans `main()` seulement, pas dans `build()` : les tests
  utilisent `caplog`) ; loggers `organizer.*`.
- Mots de passe : `MIN_PASSWORD_LENGTH = 12` (`core/services/users.py`). `authenticate` pose / retire la
  préférence `WEAK_PASSWORD_PREF` ; changement ou réinitialisation la retire. Bandeaux : `ctx.banners`
  (`Banner(text, tone, action, target, mark)`) + ceux calculés par `layout.page_banners` (mot de passe court,
  lu par `ds.account.get_pref` : marche aussi sur le client bureau) ; `ctx.banner_rows` pour en retirer un.
- Avec `nosniff`, un script servi sous un mauvais type est bloqué : après une mise à jour de NiceGUI ou un
  nouveau fichier statique, vérifier les `Content-Type` des ressources d'une page.

## Sauvegarde

- `organizer/server/backup.py` : `BackupArchive(settings, include_uploads)` prend l'image de la base **à la
  création** (`sqlite3` `backup()` → fichier temporaire `.backup-*.db` du dossier des données, journal
  `DELETE`, `integrity_check`) ; `chunks()` produit le `.tar` à la main (en-têtes `TarInfo.tobuf`, blocs de
  512 o, fin à un multiple de `RECORDSIZE`) sans copie complète, et supprime l'image (`finally` + tâche de
  fond de la réponse). `manifest.json` **en dernier** (une archive tronquée n'en a pas).
- Route `server/api/admin.py` : `backup_access` = session admin **ou** jeton `orgbk_…`
  (`AuthService.resolve_api_key`, table `api_key`, jamais accepté par `resolve` comme session), jeton
  limité aux adresses privées / de bouclage (`is_local_address`). Attention : `ipaddress` classe aussi les
  plages de documentation (`203.0.113.0/24`…) comme privées → adresse publique de test : `86.245.12.7`.
- Interface : `ds.backup_url(uploads)` (web : `ui.download.from_url`, avec le cookie) ;
  `ds.save_backup(uploads, folder)` (client bureau seulement : `ApiClient.save` en flux vers
  `system.downloads_dir()`, appelé par `run.io_bound`). Jetons : `ds.account.backup_keys / create_backup_key
  / revoke_backup_key`.
- Restauration : `organizer/server/restore.py` (`prepare` en un passage `tarfile` mode `r|*` → dossier
  `.restauration-<date>` vérifié ; `swap` = renommages, anciennes données dans `avant-restauration-<date>/`)
  piloté par `deploy/restore.sh` (arrêt / redémarrage du service entre les deux). Pas de
  `tarfile` `filter=` (absent de Python 3.11.2 du Pi) : les noms admis sont vérifiés un par un et chaque
  fichier est écrit à la main.
- Tests : `tests/test_backup.py`, `tests/test_restore.py` (script de bout en bout avec faux `systemctl` /
  `sudo` en tête du `PATH`, `ORG_WAIT_TRIES=1`) ; simulateur : `await user.download.next()` récupère le
  téléchargement.
- ⚠️ Faux service pour un essai manuel : enregistrer le PID **du programme python** (`nohup … &` sur sa
  propre ligne, pas `cd … && nohup … &`, dont `$!` est un sous-shell) ; sinon « stop » ne l'arrête pas et
  l'ancien serveur continue de servir les fichiers déplacés (faux échec de restauration constaté).

## Migrations de la base (1.0.0)

- `organizer/core/migrations.py` : `init_db(engine)` → `migrate(engine)`. Numéro de schéma = `PRAGMA
  user_version` (0 = avant 1.0.0, 1 = 1.0.0, point de départ `_baseline`). Base neuve : `create_all` +
  dernier numéro. Base existante : `create_all` (tables nouvelles), copie de sécurité si une étape a
  `changes_data`, puis chaque étape dans **sa** transaction avec le numéro. `SchemaTooNew` si la base est
  plus récente que le code.
- ⚠️ Le pilote `sqlite3` n'ouvre pas de transaction avant un `ALTER TABLE` : un `engine.begin()` ordinaire
  ne l'annule **pas** (constaté par `test_failed_step_is_rolled_back`). Les étapes passent donc par
  `_transactional_engine` (`isolation_level = None` + `BEGIN` émis sur l'événement `begin`, recette de la
  documentation de SQLAlchemy), réservé aux migrations.
- Ajouter une colonne : modèle + `Migration(n + 1, "…", lambda conn: add_column(conn, "task", "x", "DATE"))`
  à la fin de `MIGRATIONS` ; `NOT NULL` exige un `DEFAULT` en SQL. Ne jamais modifier une étape publiée ;
  une étape doit tolérer une table déjà au dernier schéma.
- Garde-fou : `tests/fixtures/organizer-0.9.0.db`, créée par le **vrai code de la v0.9.0** (`git worktree`
  sur l'étiquette, script hors dépôt) ; `test_old_database_reaches_the_current_schema` compare son schéma
  migré (`table_columns`) à celui d'une base neuve. Ne jamais modifier ce fichier.

## Versions et mises à jour

- `organizer/__init__.py` : `__version__` (**1.0.0** depuis le 9/11/2026 ; ensuite MINEUR = nouveauté,
  CORRECTIF = correction, MAJEUR = incompatibilité) et `API_VERSION`.
  **À chaque version livrée** (passage sur `main` approuvé par l'utilisateur) : augmenter `__version__`, l'indiquer dans
  l'historique de `specifications.md`, proposer l'étiquette git `v<version>`. Augmenter `API_VERSION`
  seulement si un client plus ancien ne peut plus fonctionner (route supprimée / modifiée de façon
  incompatible) — préférer des changements compatibles (champs ajoutés avec valeur par défaut).
- Comparaison et messages : `organizer/versioning.py` ; route publique `GET /api/v1/version` ; bandeau du
  client : `DesktopClient.version_check` (cache 10 min) → `UiContext.banners` → `app_frame`. Le client
  compare aussi la version **sur le disque** (`installed_version()`, lue dans `organizer/__init__.py`) à
  celle **en mémoire** : un client qui tourne depuis avant un `git pull` affiche « quittez puis relancez »
  (cas rencontré : bandeau trompeur après la mise à jour du Pi).
- **Serveur** : `deploy/install.sh` (+ `deploy/common.sh` : `org_target_user` = `SUDO_USER` sous sudo, sinon
  `id -un`, refus en root direct ; `org_as_user` / `org_as_root`). Le service systemd est **généré**
  (`--print-service` pour le voir), plus de fichier statique. Tests : `tests/test_deploy.py`
  (`ORG_EUID=0` simule sudo, `ORG_UNIT_PATH` déplace le fichier de service). Essai complet sans droits
  administrateur : faux `sudo` / `systemctl` en tête du `PATH` (le faux `systemctl restart` lance le serveur
  d'après le fichier généré). ⚠️ Pour arrêter un serveur de test, viser le **programme** python
  (`ps -eo pid,args | awk '$2 ~ /python/ && /motif/'`), jamais `pkill -f motif` (tue son propre shell).
- **Version de test** : `deploy/install_test.sh` (Pi) bascule la même installation (même service, mêmes
  données) sur `cloclo` (ou `--branch x`), `--main` y revient ; copie de la base `avant-<branche>-<date>.db`
  en quittant main ; refuse de revenir sur main si la base a un schéma plus récent que celui de main
  (`SCHEMA_VERSION`), et reste alors sur la branche de test. Ensuite `deploy/update.sh` suit la branche
  active. Tests : `tests/test_deploy.py` (dépôt distant + clone temporaires, faux paquet `migrations`).
- Scripts : `install/linux/update.sh`, `install/windows/update.ps1` (+ `.bat`), `deploy/update.sh` (Pi). Les
  scripts bash sont enveloppés dans une fonction `main` (git pull peut les modifier pendant leur exécution).
  L'installeur retient ses options (`install.json`, `--reuse`).
- `install.sh` fait `cd "$ROOT"` : `python -m organizer…` doit trouver le paquet d'où qu'on le lance.

## Tests

- `tests/test_*.py` : services (base SQLite temporaire, date du jour figée au mercredi 4/11/2026).
- `tests/test_api.py` : API via `fastapi.testclient.TestClient`.
- `tests/test_pages.py` : pages via la fixture `user` de NiceGUI (`-p nicegui.testing.user_plugin`,
  `main_file = run_server.py`, pytest-asyncio en mode auto). Les variables `ORGANIZER_DATA_DIR` /
  `ORGANIZER_PORT` sont fixées par une fixture autouse.

## Commandes

```bash
python3 -m venv .venv                          # création du venv (déjà fait)
.venv/bin/pip install -r requirements-dev.txt  # dépendances dev (serveur + client + outils)
.venv/bin/python run_server.py                 # serveur sur http://0.0.0.0:2603 (doc API : /docs, connecté)
.venv/bin/python run_client.py                 # client bureau (fenêtre native ; --browser : navigateur)
.venv/bin/pytest                               # tests
.venv/bin/ruff format .                        # mise en forme (110 colonnes)
.venv/bin/python scripts/demo.py               # démo terminal (base data/demo.db, recréée)
.venv/bin/ruff check .                         # lint + compatibilité Python 3.11
```

Avant de proposer un commit : `ruff format .`, `ruff check .` et `pytest` doivent passer.

## État actuel

- ✅ Étape 0 : venv, dépendances, spécification.
- ✅ Étape 1 : cœur métier (`organizer/core/`).
- ✅ Étape 2 : serveur (`organizer/server/`) — sessions, API REST, pièces jointes, pages provisoires
  /login, /setup, service systemd.
- 397 tests au total (+1 réservé à Windows).
- ✅ Étape 3 : interface (`organizer/ui/`) — thème, layout, cartes, éditeur, accueil, liste.
- ✅ Étape 4 : éditeur markdown façon Obsidian (`components/markdown_editor.*`).
- ✅ Étape 5 : liste filtrable / triable / regroupable, recherche Ctrl+K, réglages, dupliquer, heure.
- ✅ Étape 6 : boards personnalisés, pages `/kanban` et `/matrix`, glisser-déposer souris / tactile,
  Ctrl+drop ; puis kanbans pleine page, colonnes repliables / redimensionnables, reclassement (urgence +
  rang).
- ✅ Étape 7 : client bureau (fenêtre native, `RemoteDataSource` via l'API, connexion par jeton, ouverture
  des fichiers locaux, notifications des rappels). Vérifié sous Linux (GTK) ; **Windows** : installé et lancé (Python 3.13 ; 3.14+ refusé par l'installeur, faute de pythonnet), suite de tests verte ; usage réel encore peu essayé.
  Puis : arrière-plan, instance unique, raccourcis globaux, installeurs, icône « Post-it en vrac »
  (source : `organizer/assets/organizer.svg`).
- ✅ Étape 8 : temps réel (SSE), PWA, HTTPS facultatif, finitions. Feuille de route terminée.
- ✅ Mise en ligne (version 0.9.0) : derrière Cloudflare Tunnel (cookie `Secure`, en-têtes, vraie IP),
  durcissement (docs, anti force brute par identifiant, journal, `--host`, mots de passe de 12), sauvegarde
  / restauration (borg), guide dans le README. Pièces jointes : sélecteur réparé, dépôt de fichiers.
- Tests lancés sur le Pi (**Python 3.11.2**) : 345 / 350 au premier passage ; deux causes corrigées :
  `tarfile` `extract(filter=…)` absent avant 3.11.4 (ne jamais l'utiliser, même dans un test) ; **langue du
  Pi en Latin-1** → sortie de Python en Latin-1, plantage sur le premier emoji (`deploy/restore.sh`). D'où
  `PYTHONUTF8=1` dans le service généré et dans `restore.sh` (+ `PYTHONIOENCODING=utf-8`),
  `restore._utf8_output()`, et les tests du script lancés avec `PYTHONIOENCODING=latin-1`. Tout nouveau
  programme Python lancé en ligne de commande sur le Pi doit en faire autant.
- ✅ **Version 1.0.0** (9/11/2026) : migrations de la base en place ; client bureau validé sous Linux et
  Windows. Reste à faire par l'utilisateur : essai réel de la sauvegarde borg et d'une restauration (TODO).
- Feuille de route complète : `specifications.md` §11.
