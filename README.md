# 📋 Organizer

Organiseur de tâches multi-utilisateurs, joli et simple, avec des emojis pour tout repérer d'un coup d'œil.

- 🏠 Accueil avec les points chauds · 📋 liste des tâches · 📊 kanbans · 🎯 matrice d'Eisenhower
- 🌳 Sous-tâches (même par Ctrl + glisser-déposer) · 📁 projets · 🏷️ tags (publics ou privés)
- ↩️ Ctrl+Z partout pour annuler
- 📝 Notes markdown façon Obsidian · 🔗 liens, fichiers et pièces jointes
- 🖥️ Client bureau Linux / Windows · 🌐 web · 📱 téléphone
- 👥 Plusieurs utilisateurs, 🍪 reconnexion rapide, ⚡ mises à jour en temps réel sur tous les écrans
- 📲 Installable sur le téléphone comme une application (PWA)

Le serveur tourne sur un Raspberry Pi et écoute sur le **port 2603** du réseau local.

> ✅ **Les 8 étapes de la feuille de route sont faites** : cœur métier, serveur, API, interface (accueil,
> liste filtrable, recherche, réglages, éditeur, notes markdown façon Obsidian), kanbans, matrice d'Eisenhower,
> glisser-déposer, client bureau, temps réel et PWA. Idées pour la suite : [`TODO.md`](TODO.md).
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
- **Mots de passe** : 12 caractères minimum. Un compte créé avant cette règle avec un mot de passe plus court
  fonctionne toujours, mais un bandeau orange invite à le changer (Réglages → Profil).
- **Documentation de l'API** (et essais en direct) : `http://<ip>:2603/docs` (une fois connecté).

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

## 🖥️ Installer le client bureau

**Linux** (sans droits root ; KDE Plasma et GNOME : raccourcis clavier configurés automatiquement) :

```bash
install/linux/install.sh                  # options : --no-autostart --no-shortcuts --uninstall
install/linux/install.sh --show-key Meta+O --new-key Meta+N   # autres raccourcis
```

**Windows** : double-cliquer sur `install\windows\install.bat` (Python ≥ 3.11 depuis python.org requis ;
désinstallation : `uninstall.bat`).

L'installeur crée l'environnement Python, le lanceur « Organizer » (menu des applications / menu Démarrer),
le démarrage en arrière-plan à l'ouverture de session et deux **raccourcis clavier globaux** :

| Raccourci | Effet |
|---|---|
| **Ctrl+Alt+O** | ouvrir Organizer (le ramener au premier plan) |
| **Ctrl+Alt+N** | créer une nouvelle tâche (éditeur ouvert sur la page affichée) |

Fermer la fenêtre la cache : Organizer continue en arrière-plan (rappels, raccourcis). Pour l'arrêter :
menu du compte → **⏻ Quitter Organizer**. En ligne de commande : `run_client.py --new-task`, `--quit`,
`--hidden` (une commande est transmise au client déjà lancé).

**🔄 Mettre à jour un poste** : `install/linux/update.sh` (Linux) ou `install\windows\update.bat`
(Windows). Le script arrête le client, récupère la nouvelle version (`git pull`), réinstalle avec les mêmes
options et relance le client. Le client affiche un bandeau quand le serveur a une version plus récente.

## Déploiement sur le Raspberry Pi

Sur le Pi (Raspberry Pi OS, Python 3.11), depuis **votre compte** (pas besoin d'un utilisateur `pi`) :

```bash
sudo apt install git python3-venv                   # si besoin
git clone <dépôt> ~/organizer && cd ~/organizer
deploy/install.sh                                    # (sudo deploy/install.sh revient au même)
```

Le script crée l'environnement Python, installe les dépendances, puis **génère et active un service
systemd** `organizer`, qui tourne sous le compte qui a lancé la commande (même avec `sudo` : jamais en
root). Il démarre avec le Pi, se relance s'il s'arrête, et le script vérifie que le serveur répond avant
d'afficher les adresses à ouvrir. Première visite : création du compte administrateur.

| Option | Effet |
|---|---|
| `--port 2603` | port d'écoute |
| `--host 0.0.0.0` | adresse d'écoute : `0.0.0.0` (par défaut) = réseau local et Pi ; `127.0.0.1` = le Pi seulement (accès extérieur par Cloudflare Tunnel) |
| `--data-dir <dossier>` | dossier des données (par défaut `data/` du projet) |
| `--ssl-cert <pem> --ssl-key <pem>` / `--no-https` | HTTPS (voir plus bas) / retour au HTTP |
| `--print-service` | affiche le service qui serait installé, sans rien changer |
| `--uninstall` | arrête et retire le service (code et données conservés) |

Les options sont retenues (`deploy/server.conf`). Suivi : `systemctl status organizer`,
`journalctl -u organizer -f`. Le journal contient aussi chaque tentative de connexion (identifiant, adresse
IP, échec / blocage / réussite) : `journalctl -u organizer | grep organizer.auth`.

Les données (base `organizer.db` et pièces jointes `uploads/`) sont dans le dossier des données : c'est lui
qu'il faut sauvegarder.

**Mise à jour du serveur** : `deploy/update.sh` (`git pull`, puis l'installeur avec les mêmes options :
dépendances, service régénéré s'il a changé, redémarrage, vérification de la version). Mettre à jour le
serveur **avant** les postes.

**Versions** : `MAJEUR.MINEUR.CORRECTIF` (actuellement **0.8.0** ; 1.0.0 une fois validé sur le Pi et les téléphones),
visible sur `http://<ip>:2603/api/v1/version` et dans Réglages → 🔌 Connexion du client bureau.

## 📲 Sur le téléphone

Ouvrir `http://<ip-du-pi>:2603` puis :

- **iPhone** : Safari → Partager → **« Sur l'écran d'accueil »** : Organizer s'ouvre en plein écran, comme
  une application (appui long sur l'icône : « Nouvelle tâche », « Kanbans »).
- **Android** : Chrome → ⋮ → « Ajouter à l'écran d'accueil ». En HTTP, c'est un raccourci qui s'ouvre dans
  Chrome ; pour le vrai mode application, il faut le HTTPS (ci-dessous).

### HTTPS (facultatif)

> 🌍 Pour un accès **depuis Internet**, la solution retenue est **Cloudflare Tunnel** (certificat reconnu
> partout, rien à installer sur les téléphones) : guide pas à pas à venir. Le serveur est déjà prêt à
> fonctionner derrière ce proxy (cookie `Secure`, en-têtes de sécurité, vraie IP des visiteurs).
> mkcert reste utile pour du HTTPS **sur le réseau local seulement**.

Avec [mkcert](https://github.com/FiloSottile/mkcert) (une autorité de certification locale) :

```bash
mkcert -install                                   # sur le PC : crée l'autorité locale
mkcert -cert-file organizer.pem -key-file organizer-key.pem raspberrypi.local 192.168.1.20
# copier les deux fichiers sur le Pi (ex. ~/organizer/certs/), puis sur le Pi :
#   deploy/install.sh --ssl-cert certs/organizer.pem --ssl-key certs/organizer-key.pem
mkcert -CAROOT                                    # dossier du certificat racine rootCA.pem
```

- Téléphones : installer `rootCA.pem` (Android : Paramètres → Sécurité → Installer un certificat ; iPhone :
  l'ouvrir puis l'activer dans Réglages → Général → Informations → Réglages des certificats).
- Client bureau : adresse `https://raspberrypi.local:2603` et variable `ORGANIZER_CA_FILE=<chemin de
  rootCA.pem>` (le client ne lit pas le magasin de certificats du système).

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
