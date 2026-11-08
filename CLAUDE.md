# CLAUDE.md — Consignes pour Claude sur le projet Organizer

## Le projet

Organiseur de tâches multi-utilisateurs : serveur NiceGUI/FastAPI sur Raspberry Pi (port 2603) + interface web
(responsive, téléphone) + client bureau (fenêtre native pywebview, Linux/Windows) qui passe par l'API REST.
Référence fonctionnelle complète : **`specifications.md`**.

## Règles de travail (demandées par l'utilisateur)

- **Langue** : échanges, commentaires et docstrings en français (avec accents). Identifiants de code en anglais.
- **Git** : commits réguliers, mais **jamais de commit sans confirmation explicite de l'utilisateur**.
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
- **Éditeur** (`components/task_editor.py`) : `open(id)` pour une tâche existante, `open_new()` pour une
  création (mode *brouillon* : `self.draft` contient les champs de `TaskCreate`, `self.task` un `TaskOut`
  fictif d'id 0 construit par `_draft_out()` ; `_save()` alimente le brouillon tant qu'il n'y a pas de titre,
  puis crée la tâche). Pas de création « à vide » en base.
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
  - `ui.upload` est masqué ; un bouton appelle `upload.run_method("pickFiles")`.
- **Tests d'UI** : le simulateur ne propage pas les clics aux parents et ne voit pas le contenu d'un menu
  fermé → poser des `.mark(...)` sur les éléments cliquables (cartes `task-card-<id>`, entrées de menu,
  options des curseurs `slider-importance-4`…) et ouvrir les menus avec `open_menu()` dans les tests.
- **Vérification visuelle** : Firefox headless piloté en WebDriver BiDi (aiohttp) avec un serveur de démo
  et un ticket de connexion (scripts de travail hors dépôt) ; à refaire après tout changement visuel notable.
- ⚠️ Tout script de débogage lancé avec la fixture `user` doit importer la fixture `data_dir` de
  `tests/test_pages.py`, sinon il écrit dans le vrai dossier `data/`.

## Étape 5 : liste, recherche, réglages

- **`AccountService`** (`core/services/account.py`) : profil, mot de passe, appareils, comptes (admin),
  préférences. Utilisé par l'API (`get_account`) **et** par l'interface (`ds.account`) : une seule logique.
- **Préférences d'affichage** : table `user_pref` (clé, valeur JSON) — ex. `view:tasks`, `view:search`
  (`{"filter", "sort", "group"}`). Lire avec tolérance (`_validate` dans `task_list.py`) : une préférence
  enregistrée par une ancienne version ne doit jamais casser la page.
- **Schéma de la base** : `create_all` crée les **nouvelles tables** dans une base existante, mais n'ajoute
  pas de **colonne** à une table existante → préférer une nouvelle table ; sinon prévoir une migration
  (aucun outil de migration en place pour l'instant).
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
- Pages ouvertes mémorisées (`DesktopClient._pages`) : « nouvelle tâche » ouvre l'éditeur dans la page
  affichée (`_in_page`), sinon charge `/?task=new`.
- Linux : `GLib.set_prgname("organizer")` dans le sous-processus = identifiant Wayland = nom du `.desktop`.
- Raccourcis globaux : impossibles à capter soi-même sous Wayland → déclarés au bureau par
  `organizer/client/install.py` (KDE : `doRegister` + `setForeignShortcutKeys` sur le composant
  `organizer.desktop`, actions `_launch` et `new-task` ; vérifiable avec `qdbus6 org.kde.kglobalaccel
  /component/organizer_desktop org.kde.kglobalaccel.Component.invokeShortcut _launch`). Fermer la fenêtre
  dans un test : script KWin filtré sur le **pid** du sous-processus (`workspace.windowList()`).
- Installeurs : `install/linux/install.sh`, `install/windows/install.ps1` (UTF-8 **avec BOM** et fins de
  ligne CRLF, sinon Windows PowerShell 5.1 abîme les accents ; jamais exécuté faute de Windows).
- Icône : `scripts/make_icons.sh <svg>` régénère `organizer/client/assets/` (rsvg-convert + ImageMagick,
  outils de développement seulement ; les fichiers produits sont versionnés).

## Versions et mises à jour

- `organizer/__init__.py` : `__version__` (`0.<étape>.<correctif>` jusqu'à 1.0.0) et `API_VERSION`.
  **À chaque version livrée** (commit confirmé par l'utilisateur) : augmenter `__version__`, l'indiquer dans
  l'historique de `specifications.md`, proposer l'étiquette git `v<version>`. Augmenter `API_VERSION`
  seulement si un client plus ancien ne peut plus fonctionner (route supprimée / modifiée de façon
  incompatible) — préférer des changements compatibles (champs ajoutés avec valeur par défaut).
- Comparaison et messages : `organizer/versioning.py` ; route publique `GET /api/v1/version` ; bandeau du
  client : `DesktopClient.version_check` → `UiContext.banner` → `app_frame`.
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
.venv/bin/python run_server.py                 # serveur sur http://0.0.0.0:2603 (doc API : /docs)
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
- 233 tests au total.
- ✅ Étape 3 : interface (`organizer/ui/`) — thème, layout, cartes, éditeur, accueil, liste.
- ✅ Étape 4 : éditeur markdown façon Obsidian (`components/markdown_editor.*`).
- ✅ Étape 5 : liste filtrable / triable / regroupable, recherche Ctrl+K, réglages, dupliquer, heure.
- ✅ Étape 6 : boards personnalisés, pages `/kanban` et `/matrix`, glisser-déposer souris / tactile,
  Ctrl+drop ; puis kanbans pleine page, colonnes repliables / redimensionnables, reclassement (urgence +
  rang).
- ✅ Étape 7 : client bureau (fenêtre native, `RemoteDataSource` via l'API, connexion par jeton, ouverture
  des fichiers locaux, notifications des rappels). Vérifié sous Linux (GTK) ; **Windows jamais essayé**.
  Puis : arrière-plan, instance unique, raccourcis globaux, installeurs, icône « Post-it en vrac »
  (source : `organizer/client/assets/organizer.svg`).
- ⏭️ Étape 8 : temps réel (WebSocket), PWA, finitions.
- ⚠️ Jamais exécuté sous Python 3.11 à ce jour (seulement la syntaxe vérifiée par ruff) : à valider sur le Pi.
- Feuille de route complète : `specifications.md` §11.
