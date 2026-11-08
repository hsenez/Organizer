# 📋 Organizer

Organiseur de tâches multi-utilisateurs, joli et simple, avec des emojis pour tout repérer d'un coup d'œil.

- 🏠 Accueil avec les points chauds · 📋 liste des tâches · 📊 kanbans · 🎯 matrice d'Eisenhower
- 🌳 Sous-tâches (même par Ctrl + glisser-déposer) · 📁 projets · 🏷️ tags (publics ou privés)
- ↩️ Ctrl+Z partout pour annuler
- 📝 Notes markdown façon Obsidian · 🔗 liens, fichiers et pièces jointes
- 🖥️ Client bureau Linux / Windows · 🌐 web · 📱 téléphone
- 👥 Plusieurs utilisateurs, 🍪 reconnexion rapide

Le serveur tourne sur un Raspberry Pi et écoute sur le **port 2603** du réseau local.

> 🚧 **Projet en cours de construction** — étapes 1 à 7 sur 8 : cœur métier, serveur, API, interface (accueil,
> liste filtrable, recherche, réglages, éditeur, notes markdown façon Obsidian), kanbans, matrice d'Eisenhower,
> glisser-déposer et client bureau. À venir : temps réel et finitions (étape 8).
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

## Utilisation

```bash
.venv/bin/python run_server.py   # serveur → http://<ip-du-pi>:2603
.venv/bin/python run_client.py   # client bureau (fenêtre native)
.venv/bin/python run_client.py --browser   # client bureau dans le navigateur
```

- **Premier lancement** : ouvrir `http://<ip>:2603` → page de création du compte administrateur.
- Ensuite : page de connexion, avec « 🍪 Se souvenir de moi » (30 jours).
- **Documentation de l'API** (et essais en direct) : `http://<ip>:2603/docs`.

**🖥️ Client bureau** : au premier lancement, indiquer l'adresse du Pi (`raspberrypi.local` ou son IP : le
port 2603 est ajouté tout seul), l'identifiant et le mot de passe. Seul un **jeton** est conservé
(`~/.config/organizer/client.json`, ou `%APPDATA%\Organizer\` sous Windows) : les lancements suivants
ouvrent directement l'application. Par rapport au site :

- les **chemins de fichiers** s'ouvrent avec l'application par défaut du poste (au lieu d'être copiés), les
  liens web dans le navigateur, les pièces jointes sont téléchargées puis ouvertes ;
- 🔔 **notifications système** quand la date de rappel d'un suivi est atteinte (une fois par jour ;
  désactivables dans Réglages → 🔔 Rappels ; bouton de test dans Réglages → 🔌 Connexion) ;
- Réglages → 🔌 **Connexion** : se déconnecter ou changer de serveur.
- Depuis un téléphone : même adresse dans le navigateur (interface adaptée, menu ☰).
- Raccourcis : **N** nouvelle tâche, **Ctrl+K** rechercher, **Ctrl+Z** annuler, **Ctrl+Maj+Z** / **Ctrl+Y**
  rétablir.
- Réglages (projets, tags, thème, appareils connectés, comptes des utilisateurs…) : menu du compte →
  ⚙️ Réglages, ou `http://<ip>:2603/settings`.
- Lien direct vers une tâche : `http://<ip>:2603/tasks?task=<numéro>` (`?task=new` : nouvelle tâche).

**Glisser-déposer** (kanbans, matrice, et partout où il y a des cartes) :

- dans un kanban prédéfini, **reclasser** une carte dans sa colonne (un trait bleu montre où elle va) : sa
  position règle finement son **urgence** (elle prend au besoin l'urgence de ses voisines) ;
- colonnes : ⇤ pour les **replier**, tirer leur bord droit pour les **élargir** (double-clic : largeur par
  défaut) — mémorisé par board ;
- souris : glisser une carte vers une colonne / un quadrant ; **Ctrl** (⌘ sur Mac) en la lâchant sur une
  autre carte → elle devient sa **sous-tâche** (vert = possible, rouge = impossible) ; Échap annule ;
- téléphone : **appui long** pour saisir la carte, puis glisser ; rester ~1 s sur une autre carte → sous-tâche.

Sujets en cours de réflexion (liens vers les fichiers…) : voir [`TODO.md`](TODO.md).

Réglages par variables d'environnement : `ORGANIZER_DATA_DIR` (dossier des données, `./data` par défaut),
`ORGANIZER_PORT` (2603), `ORGANIZER_HOST` (0.0.0.0).

## Déploiement sur le Raspberry Pi

```bash
# Sur le Pi (Raspberry Pi OS, Python 3.11)
git clone <dépôt> /home/pi/organizer && cd /home/pi/organizer
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Service systemd (démarrage automatique) — adapter User / chemins dans le fichier si besoin
sudo cp deploy/organizer.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now organizer
systemctl status organizer          # état
journalctl -u organizer -f          # journaux
```

Les données (base `organizer.db` et pièces jointes `uploads/`) sont dans `data/` : c'est ce dossier à
sauvegarder.

## Développement

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest            # tests
.venv/bin/ruff format .     # mise en forme du code
.venv/bin/ruff check .      # lint + compatibilité Python 3.11
```

Structure : `organizer/core/` contient le cœur métier (modèles, règles, services, historique annuler /
rétablir), `organizer/server/` le serveur (API, authentification, pages), `tests/` les tests. Voir [`specifications.md`](specifications.md) §2.2 pour l'arborescence complète.

## Bibliothèques utilisées

| Bibliothèque | Rôle |
|---|---|
| NiceGUI | interface web/bureau et serveur HTTP (FastAPI + Uvicorn) |
| SQLModel / SQLAlchemy | base de données SQLite |
| argon2-cffi | hachage des mots de passe |
| httpx | client bureau → API du serveur |
| pywebview (+ PyGObject sous Linux) | fenêtre native du client bureau |
| CodeMirror 6 (fourni par NiceGUI) | éditeur de notes markdown en direct, façon Obsidian |
| pytest, pytest-asyncio, ruff | tests (dont pages web simulées) et lint |
