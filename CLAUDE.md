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
- La logique métier (sous-tâches, rappels, règles de dépôt kanban/matrice, Ctrl+drop) vit dans
  `organizer/core/services/` et est **couverte par des tests**.
- Interface en français ; textes regroupés pour permettre une traduction future.

## Commandes

```bash
python3 -m venv .venv                          # création du venv (déjà fait)
.venv/bin/pip install -r requirements-dev.txt  # dépendances dev (serveur + client + outils)
.venv/bin/python run_server.py                 # serveur sur http://0.0.0.0:2603   (à venir)
.venv/bin/python run_client.py                 # client bureau                    (à venir)
.venv/bin/pytest                               # tests
.venv/bin/ruff check .                         # lint + compatibilité Python 3.11
```

## État actuel

- Étape 0 : venv créé, dépendances installées, documents de spécification rédigés. Pas encore de code.
- Feuille de route : voir `specifications.md` §11.
