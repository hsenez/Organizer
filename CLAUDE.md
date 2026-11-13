# CLAUDE.md — Consignes pour Claude sur le projet Organizer

## Le projet

Organiseur de tâches multi-utilisateurs : serveur NiceGUI/FastAPI sur Raspberry Pi (port 2603) + interface web
(responsive, téléphone) + client bureau (fenêtre native pywebview, Linux/Windows/macOS) qui passe par l'API REST.
Référence fonctionnelle complète : **`specifications.md`**.

## Règles de travail (demandées par l'utilisateur)

- **Langue** : échanges, commentaires et docstrings en français (avec accents). Identifiants de code en anglais.
- **Git** (depuis le 9/11/2026) : travailler sur la branche **`cloclo`** ; y **commiter et pousser
  systématiquement** sur le NAS (`git push origin cloclo`, pas GitHub) après chaque changement terminé et vérifié (format, lint,
  tests verts), sans demander : c'est ce que l'utilisateur teste sur le Pi (`deploy/install_test.sh`).
  **Jamais rien sur `main` sans son approbation explicite** (fusion de `cloclo`, push, étiquette).
- **Documentation** : `specifications.md`, `CLAUDE.md`, `docs/claude/*.md` et `README.md` sont **mis à jour
  à chaque changement** (fonctionnalité, architecture, dépendance, commande). Ajouter une ligne dans
  l'historique de `specifications.md`. Les détails d'un module vont dans son fichier de `docs/claude/`,
  pas ici.
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

## Pièges transverses (détails dans docs/claude/)

- Méthode de service utilisée par l'UI = route API + version dans `client/remote.py` + test dans
  `tests/test_client.py` (contrat du client bureau).
- Colonne ajoutée à une table existante = migration (`core/migrations.py`) ; ne jamais modifier une étape
  publiée ni `tests/fixtures/organizer-0.9.0.db`.
- Nouvelle table liée à une tâche / un événement / une note : `UNDOABLE_TABLES`, `_ITEM_OF`
  (notifications), suppression / fusion de tags et projets (`labels.py`).
- Pages enregistrées par `register_pages()` / `register_app_pages()`, jamais `@ui.page` à l'import.
- Tests d'UI : marqueurs `.mark(...)` ; `refreshable.refresh()` s'exécute en tâche de fond (attendre) ;
  un script de débogage avec la fixture `user` importe `data_dir` de `tests/test_pages.py`.
- Arrêter ses serveurs de test **par PID** du programme python (jamais `pkill -f`).
- Programme Python lancé en ligne de commande sur le Pi : `PYTHONUTF8=1` (Pi en Latin-1) ; jamais
  `tarfile` `filter=`.

## Où trouver le reste

| Sujet | Fichier |
|---|---|
| Interface : éditeur, markdown, thème, pièges NiceGUI, listes, boards, glisser-déposer, téléphone | `docs/claude/interface.md` |
| Calendrier, événements (agenda) | `docs/claude/calendrier-agenda.md` |
| Notes, liens internes, notifications | `docs/claude/notes.md` |
| Client bureau, temps réel, PWA | `docs/claude/client-bureau.md` |
| Serveur, sécurité, Cloudflare, sauvegarde, migrations, versions, déploiement, historique | `docs/claude/serveur-deploiement.md` |

Lire le fichier du domaine touché **avant** de modifier ce domaine.

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

- Feuille de route terminée (étapes 0 à 8) ; **version 1.2.0** (11/11/2026). 514 tests (+1 Windows).
- Historique détaillé : `docs/claude/serveur-deploiement.md` et `specifications.md` §12.
