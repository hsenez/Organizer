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
.venv/bin/python run_client.py                 # client bureau                    (à venir)
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
- 130 tests au total.
- ✅ Étape 3 : interface (`organizer/ui/`) — thème, layout, cartes, éditeur, accueil, liste.
- ✅ Étape 4 : éditeur markdown façon Obsidian (`components/markdown_editor.*`).
- ⏭️ Étape 5 : accueil, liste avec filtres et tris, recherche (Ctrl+K), réglages (projets, tags, appareils…).
- ⚠️ Jamais exécuté sous Python 3.11 à ce jour (seulement la syntaxe vérifiée par ruff) : à valider sur le Pi.
- Feuille de route complète : `specifications.md` §11.
