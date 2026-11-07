# 📋 Organizer

Organiseur de tâches multi-utilisateurs, joli et simple, avec des emojis pour tout repérer d'un coup d'œil.

- 🏠 Accueil avec les points chauds · 📋 liste des tâches · 📊 kanbans · 🎯 matrice d'Eisenhower
- 🌳 Sous-tâches (même par Ctrl + glisser-déposer) · 📁 projets · 🏷️ tags (publics ou privés)
- ↩️ Ctrl+Z partout pour annuler
- 📝 Notes markdown façon Obsidian · 🔗 liens, fichiers et pièces jointes
- 🖥️ Client bureau Linux / Windows · 🌐 web · 📱 téléphone
- 👥 Plusieurs utilisateurs, 🍪 reconnexion rapide

Le serveur tourne sur un Raspberry Pi et écoute sur le **port 2603** du réseau local.

> 🚧 **Projet en cours de construction** — le cœur métier est prêt et testé (étape 1/8) ; serveur et interface
> arrivent.
> Détails fonctionnels : [`specifications.md`](specifications.md).

## Prérequis

- **Python ≥ 3.11**
- Client bureau sous **Linux** : `webkit2gtk-4.1` et `gtk3` installés côté système
  (Manjaro/Arch : `sudo pacman -S webkit2gtk-4.1` ; Debian/Ubuntu : `sudo apt install gir1.2-webkit2-4.1 libgirepository1.0-dev`).
- Client bureau sous **Windows** : Microsoft Edge WebView2 (présent par défaut sur Windows 10/11).

## Installation

```bash
git clone <dépôt> organizer && cd organizer
python3 -m venv .venv

# Serveur (Raspberry Pi)
.venv/bin/pip install -r requirements.txt

# Client bureau
.venv/bin/pip install -r requirements-client.txt
```

Sous Windows, remplacer `.venv/bin/` par `.venv\Scripts\`.

## Démo dans le terminal

En attendant l'interface, un scénario de démonstration affiche les vues (liste, kanban, matrice, échéances,
recherche, partage, Ctrl+Z) avec des données d'exemple, dans une base séparée (`data/demo.db`) :

```bash
.venv/bin/python scripts/demo.py      # déroule le scénario
.venv/bin/python -i scripts/demo.py   # puis console Python pour jouer soi-même
```

## Utilisation *(à venir)*

```bash
.venv/bin/python run_server.py   # serveur → http://<ip-du-pi>:2603
.venv/bin/python run_client.py   # client bureau
```

Au premier lancement du serveur, ouvrir `http://<ip-du-pi>:2603` pour créer le compte administrateur.

Depuis un téléphone : ouvrir la même adresse dans le navigateur, puis « Ajouter à l'écran d'accueil ».

## Développement

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest            # tests
.venv/bin/ruff format .     # mise en forme du code
.venv/bin/ruff check .      # lint + compatibilité Python 3.11
```

Structure : `organizer/core/` contient le cœur métier (modèles, règles, services, historique annuler /
rétablir), `tests/` les tests. Voir [`specifications.md`](specifications.md) §2.2 pour l'arborescence complète.

## Bibliothèques utilisées

| Bibliothèque | Rôle |
|---|---|
| NiceGUI | interface web/bureau et serveur HTTP (FastAPI + Uvicorn) |
| SQLModel / SQLAlchemy | base de données SQLite |
| argon2-cffi | hachage des mots de passe |
| itsdangerous | cookies et jetons signés |
| httpx | client bureau → API du serveur |
| pywebview (+ PyGObject sous Linux) | fenêtre native du client bureau |
| CodeMirror 6 (JS, embarqué) | éditeur markdown en direct |
| pytest, ruff | tests et lint |
