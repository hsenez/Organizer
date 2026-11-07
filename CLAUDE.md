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
- **Dépendances** : toujours dans le venv `.venv/`. Annoncer à l'utilisateur toute nouvelle bibliothèque, puis
  l'ajouter avec sa version au bon fichier `requirements*.txt`.
- **Tout en Python**, sauf le strict nécessaire en JS/CSS pour l'interface (éditeur CodeMirror, glisser-déposer),
  vendorisé dans `organizer/static/` (pas de CDN à l'exécution : le Pi peut être sans Internet).

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

## Commandes

```bash
python3 -m venv .venv                          # création du venv (déjà fait)
.venv/bin/pip install -r requirements-dev.txt  # dépendances dev (serveur + client + outils)
.venv/bin/python run_server.py                 # serveur sur http://0.0.0.0:2603   (à venir)
.venv/bin/python run_client.py                 # client bureau                    (à venir)
.venv/bin/pytest                               # tests
.venv/bin/ruff format .                        # mise en forme (110 colonnes)
.venv/bin/python scripts/demo.py               # démo terminal (base data/demo.db, recréée)
.venv/bin/ruff check .                         # lint + compatibilité Python 3.11
```

Avant de proposer un commit : `ruff format .`, `ruff check .` et `pytest` doivent passer.

## État actuel

- ✅ Étape 0 : venv, dépendances, spécification.
- ✅ Étape 1 : cœur métier (`organizer/core/`) + 83 tests (`tests/`).
- ⏭️ Étape 2 : serveur — authentification (cookies, jetons), API REST, premier compte admin.
- Feuille de route complète : `specifications.md` §11.
