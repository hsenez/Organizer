# 📋 Organizer

Organiseur de tâches multi-utilisateurs, joli et simple, avec des emojis pour tout repérer d'un coup d'œil.

- 🏠 Accueil avec les points chauds · 📋 liste des tâches · 📊 kanbans · 🎯 matrice d'Eisenhower
- 🌳 Sous-tâches (même par Ctrl + glisser-déposer) · 📁 projets · 🏷️ tags (publics ou privés)
- ↩️ Ctrl+Z partout pour annuler
- 📝 Notes markdown façon Obsidian · 🔗 liens, fichiers et pièces jointes
- 🖥️ Client bureau Linux / Windows / macOS · 🌐 web · 📱 téléphone
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
- Client bureau sous **macOS** : git (`xcode-select --install`) et Python ≥ 3.11 (`brew install python@3.13`
  ou l'installeur de python.org : le `python3` livré avec macOS est trop ancien). La fenêtre utilise WebKit,
  déjà présent.

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
- **Modules** (colonne de gauche) : 🏠 Accueil, 📋 Toutes les tâches, 📊 Kanbans, 🎯 Matrice, 📅 Calendrier
  (vues mois, semaine, 6 semaines ; événements en bandes ou à l'heure ; échéances des tâches : fond = urgence, pourtour = importance, retards ramenés à
  aujourd'hui ; glisser une pastille pour changer son échéance ; colonne des tâches sans échéance, réglable et repliable ;
  double-clic sur une case : vue du jour avec ses tâches et l'agenda sur deux colonnes, où l'on glisse
  les événements et leurs bords ; clic droit ou clic-glisser sur des jours pour créer un
  événement ou une tâche ; un même éditeur pour les deux, avec une bascule 📋 / 📅), 📝 Notes (markdown façon
  Obsidian avec barre de boutons, cases à cocher qui se rangent toutes seules, liens vers des notes / tâches /
  événements en tapant `[[`, « Cité dans », partage modifiable ou en lecture seule, publique, épingles,
  « copier le lien »), 🔍 Recherche (Ctrl+K), 🔔 Notifications (ce que les autres ont
  partagé ou modifié qui vous concerne, bulle avec le nombre de non lues), ⚙️ Réglages.
- **Documentation de l'API** (et essais en direct) : `http://<ip>:2603/docs` (une fois connecté).

**🖥️ Client bureau** : au premier lancement, indiquer l'adresse du Pi (`raspberrypi.local` ou son IP : le
port 2603 est ajouté tout seul ; un nom de domaine public comme `organizer.blou.top` passe en `https://`),
l'identifiant et le mot de passe. Seul un **jeton** est conservé
(`~/.config/organizer/client.json`, `%APPDATA%\Organizer\` sous Windows,
`~/Library/Application Support/Organizer/` sous macOS) : les lancements suivants
ouvrent directement l'application. Par rapport au site :

- les **chemins de fichiers** s'ouvrent avec l'application par défaut du poste (au lieu d'être copiés), les
  liens web dans le navigateur, les pièces jointes sont téléchargées puis ouvertes ;
- 🔔 **notifications système** quand la date de rappel d'un suivi est atteinte (une fois par jour ;
  désactivables dans Réglages → 🔔 Rappels ; bouton de test dans Réglages → 🔌 Connexion) ;
- Réglages → 🔌 **Connexion** : se déconnecter ou changer de serveur.
- 🏠 **Réseau local automatique** : connecté à l'adresse publique (`https://organizer.blou.top`), le client
  passe tout seul par le réseau local quand il est à la maison (≈ 20 ms par requête au lieu de ≈ 300 ms à
  travers Internet), et revient à l'adresse publique ailleurs. Rien à régler : le serveur lui donne ses
  adresses locales et une clé, et doit prouver qu'il la connaît avant que le client ne lui envoie son jeton.
  Conditions : serveur et client à jour, serveur écoutant sur le réseau local (`--host 0.0.0.0`, la valeur
  par défaut). État et réglage : Réglages → 🔌 Connexion (« 🏠 En ce moment : réseau local… »). Si le Pi a
  plusieurs adresses ou que la détection se trompe : variable `ORGANIZER_LOCAL_URLS=http://192.168.1.13:2603`
  dans le service du serveur.
- Depuis un téléphone : même adresse dans le navigateur (interface adaptée, menu ☰).
- Raccourcis : **N** nouvelle tâche, **Ctrl+K** rechercher, **Ctrl+Z** annuler, **Ctrl+Maj+Z** / **Ctrl+Y**
  rétablir.
- Réglages (projets, tags, thème, appareils connectés, comptes des utilisateurs…) : menu du compte →
  ⚙️ Réglages, ou `http://<ip>:2603/settings`.
- Lien direct vers une tâche : `http://<ip>:2603/tasks?task=<numéro>` (`?task=new` : nouvelle tâche).
- **Indicateur de connexion** (rond en bas à gauche) : 🏠 réseau local (rapide) ou 🌍 par Internet
  (Cloudflare, un peu plus lent) ; l'infobulle explique. Dans le client bureau, il suit les bascules
  automatiques et ouvre les réglages de connexion d'un clic. Dans un navigateur, la page reste sur
  l'adresse ouverte : à la maison, préférer `http://<ip-du-pi>:2603` (un favori) à l'adresse publique.
- **Pièces jointes** : dans l'éditeur d'une tâche, « 📎 Joindre un fichier » (plusieurs à la fois possible),
  ou **déposez les fichiers** depuis le gestionnaire de fichiers sur l'éditeur ouvert ou directement sur la
  **carte** d'une tâche (liste, kanbans, accueil… ; navigateur et client bureau). Le fichier est **copié**
  sur le serveur (50 Mo max chacun).

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

**Windows** : double-cliquer sur `install\windows\install.bat` (Python **3.11 à 3.13** requis — pas plus récent : pythonnet, utilisé par la fenêtre, ne le gère pas encore ;
`py install 3.13` avec le gestionnaire d'installation Python ;
désinstallation : `uninstall.bat`).

**macOS** (sans droits administrateur ; ⚠️ pas encore essayé sur un vrai Mac) :

```bash
git clone <dépôt> organizer && cd organizer
install/macos/install.sh                  # options : --no-autostart --no-shortcuts --uninstall
install/macos/install.sh --show-key Cmd+Alt+O --new-key Cmd+Alt+N   # autres raccourcis
```

Il crée `~/Applications/Organizer.app` (Launchpad, Spotlight ; à glisser dans le Dock pour l'y garder),
qui reçoit aussi les liens `organizer://`. Les raccourcis sont captés par Organizer lui-même, sans
autorisation à donner ; ils désignent la **position** des touches d'un clavier QWERTY (sur un AZERTY, A/Q,
Z/W et M sont décalés ; O et N, choisis par défaut, ne bougent pas). ⌘Q quitte, un clic sur l'icône du
Dock rouvre la fenêtre cachée. Les rappels passent par AppleScript : autoriser les notifications de
« Éditeur de script » (Réglages Système → Notifications).

L'installeur crée l'environnement Python, le lanceur « Organizer » (menu des applications / menu Démarrer),
le démarrage en arrière-plan à l'ouverture de session et deux **raccourcis clavier globaux** :

| Raccourci | Effet |
|---|---|
| **Ctrl+Alt+O** | ouvrir Organizer (le ramener au premier plan) |
| **Ctrl+Alt+N** | créer une nouvelle tâche (éditeur ouvert sur la page affichée) |

Sous Windows, ces raccourcis sont captés par Organizer lui-même : ils marchent quand il tourne (en
arrière-plan, il démarre avec la session), et une **icône dans la zone de notification** (près de
l'horloge) le rouvre d'un clic ; clic droit : nouvelle tâche, quitter. Après une mise à jour depuis une
version ≤ 0.9.4, relancer `install.bat` (il libère les touches prises par les anciens raccourcis du menu
Démarrer), puis quitter et relancer Organizer.

Fermer la fenêtre la cache : Organizer continue en arrière-plan (rappels, raccourcis). Pour l'arrêter :
menu du compte → **⏻ Quitter Organizer**. En ligne de commande : `run_client.py --new-task`, `--quit`,
`--hidden` (une commande est transmise au client déjà lancé).

**🔄 Mettre à jour un poste** : `install/linux/update.sh` (Linux), `install\windows\update.bat`
(Windows) ou `install/macos/update.sh` (macOS). Le script arrête le client, récupère la nouvelle version (`git pull`), réinstalle avec les mêmes
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

**Version de test** (branche `cloclo`, travail pas encore validé) :

```bash
deploy/install_test.sh          # passe le serveur sur cloclo (ou la met à jour) et le redémarre
deploy/install_test.sh --main   # revient sur main
```

Même service, même port, **mêmes données** : seul le code change. Une copie de la base
(`avant-cloclo-<date>.db`, dans le dossier des données) est faite en quittant main. `deploy/update.sh`
met ensuite à jour la branche active. Si la version de test a fait évoluer la base et que main ne connaît
pas encore cette évolution, le retour sur main est refusé (le serveur reste sur cloclo).

Les options sont retenues (`deploy/server.conf`). Suivi : `systemctl status organizer`,
`journalctl -u organizer -f`. Le journal contient aussi chaque tentative de connexion (identifiant, adresse
IP, échec / blocage / réussite) : `journalctl -u organizer | grep organizer.auth`.

Les données (base `organizer.db` et pièces jointes `uploads/`) sont dans le dossier des données. Pour les
sauvegarder, ne copiez pas ce dossier pendant que le serveur tourne (la copie de la base pourrait être
incohérente) : utilisez l'export ci-dessous.

### 🗄️ Sauvegarde

- **À la main** : ⚙️ Réglages → 🗄️ **Données** (administrateurs) → ⬇️ *Télécharger une sauvegarde*.
- **Automatique** (script planifié sur le Pi) : créez un **jeton de sauvegarde** au même endroit (🔑 *Nouveau
  jeton* ; il n'est affiché qu'une fois), rangez-le dans un fichier lisible par vous seul, puis :

  ```bash
  curl -fsS -H "Authorization: Bearer $(cat ~/.config/organizer-backup.token)" \
       http://127.0.0.1:2603/api/v1/admin/backup -o organizer.tar      # ?uploads=false : base seule
  ```

L'archive `.tar` (non compressée, pour qu'un outil comme borg dédoublonne d'un jour à l'autre) contient une
copie cohérente de la base, les pièces jointes et un `manifest.json` (date, version, empreintes). Le jeton ne
sert qu'à cela, n'expire pas, se révoque dans les réglages, et ne fonctionne que depuis le réseau local
(jamais par Internet). Chaque sauvegarde est notée dans le journal : `journalctl -u organizer | grep
organizer.backup`.

#### Sauvegarde quotidienne avec borg

Script à placer sur le Pi (ex. `~/bin/organizer-backup.sh`, rendu exécutable par `chmod +x`). Le dépôt borg
est créé une fois : `borg init -e repokey /mnt/Donnees/borg/organizer` (ou `-e none` sans chiffrement).
Testé avec borg 1.4 ; `import-tar`, `--glob-archives` et `compact` existent depuis borg 1.2 (Raspberry Pi
OS) ; la syntaxe de borg 2 est différente.

```bash
#!/usr/bin/env bash
# Sauvegarde quotidienne d'Organizer dans un dépôt borg (sur le Pi, lancée par cron ou un timer systemd).
set -uo pipefail
export BORG_REPO="${BORG_REPO:-/mnt/Donnees/borg/organizer}"          # dépôt créé une fois par « borg init »
# export BORG_PASSCOMMAND="cat $HOME/.config/borg-organizer.pass"      # si le dépôt est chiffré
TOKEN="$(cat "$HOME/.config/organizer-backup.token")"
URL="${ORGANIZER_URL:-http://127.0.0.1:2603}/api/v1/admin/backup"
NAME="organizer-$(date +%Y-%m-%dT%H:%M:%S)"

# L'archive passe directement de curl à borg, sans fichier intermédiaire sur la carte SD.
curl -fsS -H "Authorization: Bearer $TOKEN" "$URL" | borg import-tar --compression zstd "::$NAME" -
status=("${PIPESTATUS[@]}")
if [[ ${status[1]} -ne 0 ]]; then                  # borg a échoué : il n'a rien enregistré
    echo "❌ Sauvegarde d'Organizer : échec de borg" >&2; exit 1
fi
if [[ ${status[0]} -ne 0 ]]; then                  # téléchargement interrompu : archive incomplète
    borg delete "::$NAME"
    echo "❌ Sauvegarde d'Organizer : téléchargement échoué (archive incomplète supprimée)" >&2; exit 1
fi
# Garder 14 jours, 8 semaines et 12 mois de sauvegardes, puis libérer la place.
borg prune --glob-archives 'organizer-*' --keep-daily 14 --keep-weekly 8 --keep-monthly 12 && borg compact
```

Lancement chaque nuit à 3 h 30 : `crontab -e`, puis la ligne
`30 3 * * * $HOME/bin/organizer-backup.sh >> $HOME/organizer-backup.log 2>&1`.
Liste des sauvegardes : `borg list /mnt/Donnees/borg/organizer`.

⚠️ L'archive borg n'est supprimée en cas d'échec que si c'est le **téléchargement** qui a échoué (archive
incomplète) : un simple `borg delete` sur toute erreur effacerait une bonne sauvegarde déjà présente sous le
même nom.

### ♻️ Restauration

Sur le Pi, depuis le dossier du projet :

```bash
deploy/restore.sh ~/organizer-20261108-203451.tar           # archive téléchargée (copiée sur le Pi : scp)
borg export-tar /mnt/Donnees/borg/organizer::organizer-2026-11-08T03:30:00 - | deploy/restore.sh -
deploy/restore.sh --db-only organizer.tar                   # la base seule (pièces jointes inchangées)
```

Le script vérifie d'abord l'archive **sans arrêter le serveur** (contenu, empreintes, intégrité de la base,
version), affiche ce qu'elle contient (date, nombre de tâches…) et demande confirmation. Il arrête ensuite
le service quelques secondes, met les données actuelles **de côté** dans
`<données>/avant-restauration-<date>/` (rien n'est effacé ; un `LISEZMOI.txt` explique comment y revenir),
installe la sauvegarde, redémarre et vérifie que le serveur répond. Une archive abîmée ou incomplète est
refusée sans rien toucher ; une archive d'une version plus récente d'Organizer aussi (mettre d'abord le
serveur à jour, ou `--force`).

Après une restauration, tout revient à l'instant de la sauvegarde, y compris les comptes, les mots de passe,
les appareils connectés et les jetons de sauvegarde : un appareil connecté depuis devra se reconnecter, un
jeton créé depuis n'existera plus.

**Mise à jour du serveur** : `deploy/update.sh` (`git pull`, puis l'installeur avec les mêmes options :
dépendances, service régénéré s'il a changé, redémarrage, vérification de la version). Mettre à jour le
serveur **avant** les postes. Si la nouvelle version fait évoluer la base, elle le fait toute seule au
démarrage, après en avoir gardé une copie à côté d'elle (`organizer.db.avant-migration-v<n>-<date>` dans
le dossier des données) ; en cas d'échec, rien n'est modifié et le serveur ne démarre pas
(`journalctl -u organizer`). Revenir à une version plus ancienne d'Organizer après une telle évolution est
refusé : restaurer plutôt une sauvegarde.

**Versions** : `MAJEUR.MINEUR.CORRECTIF` (actuellement **1.2.0** ; notes de version : [`CHANGELOG.md`](CHANGELOG.md)),
visible sur `http://<ip>:2603/api/v1/version` et dans Réglages → 🔌 Connexion du client bureau.

## 📲 Sur le téléphone

Ouvrir `http://<ip-du-pi>:2603` puis :

- **iPhone** : Safari → Partager → **« Sur l'écran d'accueil »** : Organizer s'ouvre en plein écran, comme
  une application (appui long sur l'icône : « Nouvelle tâche », « Kanbans »).
- **Android** : Chrome → ⋮ → « Ajouter à l'écran d'accueil ». En HTTP, c'est un raccourci qui s'ouvre dans
  Chrome ; pour le vrai mode application, il faut le HTTPS : passer par l'adresse publique
  (`https://organizer.blou.top`, voir ci-dessous).

Le bouton ➕ propose tâche, événement ou note. Dans une note, toucher le texte passe en **mode écriture** :
seuls le texte et la barre de boutons (collée au clavier) restent à l'écran ; le bouton ⚙ de l'en-tête
déplie projet, tags et partage.

## 🌍 Accès depuis Internet (Cloudflare Tunnel)

Objectif : `https://organizer.blou.top` partout (téléphone en 4G, client bureau hors de la maison), avec un
certificat reconnu, **sans ouvrir de port** sur la box. `cloudflared`, installé sur le Pi, ouvre lui-même une
connexion sortante vers Cloudflare ; Cloudflare reçoit les visiteurs en HTTPS et les transmet par ce tunnel
à `http://127.0.0.1:2603`. Gratuit. ⚠️ Cloudflare voit passer le trafic en clair (choix assumé).

Le serveur Organizer n'a rien à changer : il reconnaît le vrai visiteur derrière le tunnel (adresse IP pour
l'anti force brute et le journal, HTTPS pour le cookie `Secure` et HSTS), refuse `/docs` aux non connectés
et le jeton de sauvegarde depuis Internet.

> Intitulés du tableau de bord Cloudflare vérifiés en **novembre 2026** (documentation Cloudflare du
> 23/06/2026). Cloudflare les change régulièrement : si un menu a bougé, chercher le même mot (« Tunnels »,
> « Edge Certificates »…) dans la barre de recherche du tableau de bord.

> 💡 **Un tunnel existe déjà sur le Pi** (pour d'autres services) ? Inutile d'en créer un second : un
> tunnel est le lien entre **une machine** et Cloudflare, et il dessert autant d'adresses (routes) qu'on
> veut. Sauter les étapes 2 et 3 et ajouter seulement la route de l'étape 4 à ce tunnel. Si son
> `cloudflared` tourne dans **Docker**, `127.0.0.1` y désigne le conteneur et non le Pi, et Organizer ne
> croirait pas l'adresse des visiteurs transmise par le conteneur (tous paraîtraient venir de la même
> adresse) : lancer ce conteneur avec `network_mode: host` et garder `http://127.0.0.1:2603`.

### 1. Le domaine sur Cloudflare (une fois)

Si `blou.top` n'est pas encore géré par Cloudflare : [dash.cloudflare.com](https://dash.cloudflare.com) →
**Add a domain** (formule *Free*), puis, chez le bureau d'enregistrement du domaine, remplacer ses serveurs
DNS (*nameservers*) par les deux que Cloudflare indique. Attendre que le domaine passe à l'état **Active**
(de quelques minutes à quelques heures). Les enregistrements DNS existants sont repris.

### 2. Installer `cloudflared` sur le Pi

Paquet officiel de Cloudflare (dépôt « any » : toute Debian, dont Raspberry Pi OS) ; il sera ensuite mis à jour
par `sudo apt upgrade` comme le reste du système :

```bash
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' \
    | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update && sudo apt-get install cloudflared
cloudflared --version
```

### 3. Créer le tunnel (tableau de bord)

1. [dash.cloudflare.com](https://dash.cloudflare.com) → menu de gauche **Networking** → **Tunnels** →
   **Create a tunnel**.
2. Nom : `organizer-pi` → **Create Tunnel**.
3. Système : **Debian** (architecture **arm64** pour un Pi 4 / 5 en 64 bits). La page affiche des commandes
   d'installation : `cloudflared` étant déjà installé (étape 2), ne copier que la **dernière**, de la forme
   `sudo cloudflared service install eyJh…` (le long texte est le **jeton du tunnel** : secret, à ne pas
   partager). La lancer sur le Pi : elle crée et démarre le service systemd `cloudflared`.
4. Le connecteur apparaît en bas de la page (état **Connected**) → **Continue**.

### 4. Publier Organizer

Dans le tunnel (**Networking** → **Tunnels** → `organizer-pi`), onglet **Routes** → **Add route** →
**Published application** :

| Champ | Valeur |
|---|---|
| Subdomain | `organizer` |
| Domain | `blou.top` |
| Path | *(vide)* |
| Service URL | `http://127.0.0.1:2603` |

→ **Add route**. Cloudflare crée lui-même l'enregistrement DNS `organizer.blou.top`.

⚠️ Écrire `127.0.0.1` et **pas** `localhost` : `localhost` peut désigner l'adresse IPv6 `::1`, où Organizer
n'écoute pas (il écoute en IPv4). En HTTPS local (mkcert, voir plus bas), mettre
`https://127.0.0.1:2603` et activer **No TLS Verify** dans les réglages TLS de la route (le certificat est
émis pour le nom du Pi, pas pour 127.0.0.1).

### 5. Réglages du domaine

Dans [dash.cloudflare.com](https://dash.cloudflare.com), choisir le domaine `blou.top`, puis :

- **SSL/TLS** → **Edge Certificates** → **Always Use HTTPS** : **activé** (un visiteur qui tape
  `http://organizer.blou.top` est redirigé en HTTPS). Si l'option n'apparaît pas : dans **SSL/TLS** →
  **Overview**, le mode de chiffrement ne doit pas être *Off*.
- Laisser **HSTS** désactivé dans Cloudflare : Organizer envoie déjà son propre en-tête HSTS aux visiteurs en
  HTTPS.
- **Network** → **WebSockets** : **activé** (c'est la valeur par défaut). L'interface en a besoin.
- **Security** → **Settings** (filtre *Bot traffic*) → **Bot fight mode** : **désactivé** (valeur par
  défaut). Activé, il bloque les clients qui ne sont pas des navigateurs : le client bureau, `curl`…

### 6. Vérifier

```bash
systemctl status cloudflared          # sur le Pi : « active (running) »
curl -sI https://organizer.blou.top/api/v1/version | grep -i -E "^HTTP|strict-transport"
#   HTTP/2 200  +  strict-transport-security: max-age=31536000
curl -sI http://organizer.blou.top/ | head -1      # 301 : redirigé vers https
```

- Le tunnel est **Healthy** dans **Networking** → **Tunnels**.
- Depuis le téléphone **en 4G** (Wi-Fi coupé) : `https://organizer.blou.top` → page de connexion avec le
  cadenas. Après connexion, `journalctl -u organizer | grep organizer.auth | tail -1` sur le Pi doit montrer
  l'**adresse publique** du téléphone, pas `127.0.0.1` (sinon, la vraie adresse des visiteurs n'arrive pas :
  vérifier la *Service URL*).
- `https://organizer.blou.top/docs` sans être connecté → renvoie à la page de connexion.

### 7. Ensuite

- **Téléphones** : ouvrir `https://organizer.blou.top` et installer l'application (iPhone : Partager → Sur
  l'écran d'accueil ; **Android** : Chrome → ⋮ → **Installer l'application**, enfin en vrai mode
  application). Une icône installée depuis `http://<ip-du-pi>:2603` est une autre adresse : la supprimer et
  réinstaller depuis l'adresse publique (il faut aussi se reconnecter).
- **Client bureau** (utilisable hors de la maison) : Réglages → 🔌 Connexion → changer de serveur → taper
  l'adresse **avec** `https://` : `https://organizer.blou.top` (sans `https://`, le client suppose une
  adresse locale en HTTP et ajoute le port 2603). À la maison, il passera tout seul par le réseau local
  (voir « Réseau local automatique » plus haut).
- **Liens à partager** : Réglages → 🗄️ Données → 🌍 **Adresse publique** = `https://organizer.blou.top`.
  Les boutons « 🔗 Copier le lien » (notes, tâches, événements) donnent alors un lien valable partout ; il
  propose d'ouvrir l'élément dans le client bureau (protocole `organizer://`, déclaré par l'installeur du
  client et par ses scripts de mise à jour) ou dans le navigateur.
- **Réseau local** : `http://<ip-du-pi>:2603` continue de fonctionner (le serveur écoute toujours sur
  `0.0.0.0`). Pour n'autoriser **que** le tunnel : `deploy/install.sh --reuse --host 127.0.0.1` (les appareils
  de la maison passent alors eux aussi par `https://organizer.blou.top`). La sauvegarde par jeton marche
  dans les deux cas (elle se fait sur le Pi, par `127.0.0.1`).
- Mots de passe : 12 caractères minimum ; un compte avec un ancien mot de passe court voit un bandeau orange
  tant qu'il ne l'a pas changé. Tentatives de connexion : `journalctl -u organizer | grep organizer.auth`.
- Limites de Cloudflare (formule gratuite) sans effet ici : envoi de 100 Mo max par requête (les pièces
  jointes sont limitées à 50 Mo) ; une requête sans réponse au bout de 100 s est coupée (le flux temps réel
  envoie un signe de vie toutes les 20 s).
- **Couper l'accès Internet** : `sudo systemctl stop cloudflared` (et `disable` pour qu'il ne redémarre pas)
  ; ou supprimer la route dans le tableau de bord.

### HTTPS sur le réseau local seulement (mkcert, facultatif)

Inutile avec Cloudflare Tunnel. Pour du HTTPS sans passer par Internet :

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
