# Notes pour Claude — Interface

Complément de `CLAUDE.md` (à la racine), à lire avant de modifier ce domaine.

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
- **Même nom** : un privé d'un autre est invisible, donc un public peut porter le nom d'un privé d'un autre
  utilisateur. Dans toute liste de choix de tags / projets, passer par `rules.label_names(...)` (« x (privé) »
  / « x (public) ») — `color_tag_select` retrouve les couleurs **par le libellé** : un libellé en double
  donnerait la mauvaise couleur. `_LabelService._check_public_name` (création / passage en public /
  renommage d'un public) : refuse deux publics du même nom, crée la notification `conflict`
  (`item_type` `tag` / `project`, `item_id` = le privé) ; `NotificationService.conflict_target`.
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

## Téléphone : clavier virtuel, ➕, mode écriture

- Balise viewport `VIEWPORT` (`components/viewport.py`) : `interactive-widget=resizes-content` — passée à
  **toutes** les `ui.page` (`common`) et à `ui.run(viewport=)` (serveur et client). Chrome Android rapetisse
  alors la page avec le clavier ; sans elle, la page glissait sous la partie visible (« tout bouge »).
- `viewport.js` (injecté par `app_frame`) : variables `--vv-top` / `--vv-height`, classe `keyboard-open`
  (écran tactile + saisie + hauteur visible réduite de plus de 120 px par rapport à la hauteur sans saisie),
  mode écriture : un élément `[data-writing]` (`writing_zone(element)`) contenant le champ actif reçoit
  `writing-active` (CSS : `position: fixed` sur la partie visible, `.md-toolbar` en bas) et `<body>`
  `writing` ; événement `organizer-viewport` → `markdown_editor.js` ramène le curseur en vue. iOS ignore
  `interactive-widget` : tout ce qui doit suivre le clavier passe par ces variables.
- CSS `@media (pointer: coarse)` : champs en 16 px (Safari zoome sinon) — sauf ceux qui ont une classe
  `text-*` (titres). Boutons flottants : classe `app-sticky` (`z-index` au-dessus du contenu, cachés si
  `keyboard-open`). ⚠️ Un `ui.page_sticky` sans `z-index` passe **sous** les cartes venues après lui.
- ➕ : `layout.new_buttons` (`ui.fab` vers le haut, marqueurs `fab-add`, `fab-new-task`, `fab-new-event`,
  `fab-new-note`) ; `ctx.new_note` (page Notes) sinon `/notes?note=new`.
- Notes au téléphone : `note-details` repliés (`note-details-open`, bouton `note-details-toggle`), barre
  cachée hors mode écriture.
- Essais : Vivaldi `--headless=new` en CDP, `Emulation.setDeviceMetricsOverride` (`mobile`, 412 × 915,
  `deviceScaleFactor=1` et `--window-size` plus grand que l'écran émulé, sinon capture découpée en tuiles),
  `setTouchEmulationEnabled` ; naviguer d'abord vers `about:blank` (sinon `Runtime.enable` ne répond pas sur
  la page d'accueil de Vivaldi) ; `Input.dispatchTouchEvent` est **décalé** de l'interface de Vivaldi
  (calibrer avec un premier toucher) ; clavier simulé en rapetissant la hauteur (= `resizes-content`). Le
  comportement iOS (Safari) ne se simule pas ici.
