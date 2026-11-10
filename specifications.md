# 📋 Organizer — Spécifications

> Document de référence fonctionnel et technique. **Mis à jour à chaque changement.**
> Version : 1.9.1 — 2026-11-08

---

## 1. Vision

Un organiseur de tâches **agréable à l'œil, très user friendly**, avec des emojis et des infobulles partout pour
s'y retrouver d'un coup d'œil. Multi-utilisateurs, hébergé sur un Raspberry Pi du réseau local, utilisable :

- 🖥️ depuis un **client bureau** (Linux / Windows) ;
- 🌐 depuis un **navigateur** (`http://<ip-du-pi>:2603`) ;
- 📱 depuis un **téléphone** (interface adaptée, installable sur l'écran d'accueil — PWA).

---

## 2. Architecture

```
                   ┌───────────────────────────── Raspberry Pi 5 (Python 3.11) ─────────────┐
 📱 Téléphone  ─┐  │  Uvicorn :2603                                                          │
 🌐 Navigateur ─┼──┼─▶ NiceGUI (pages web)  ──┐                                              │
                │  │                          ├─▶ Services métier ─▶ SQLModel ─▶ SQLite      │
 🖥️ Client  ────┼──┼─▶ API REST /api/v1  ─────┘        │                                     │
   bureau       │  │   SSE /api/v1/events ◀────────────┘ (diffusion des changements)         │
                │  │   Pièces jointes : data/uploads/                                        │
                │  └─────────────────────────────────────────────────────────────────────────┘
```

- **Une seule interface**, écrite une fois avec NiceGUI (pages, composants, cartes, éditeur).
  - Côté **serveur**, elle accède aux données via les services métier directement (`LocalDataSource`).
  - Côté **client bureau**, la même interface tourne localement dans une fenêtre native (pywebview) et accède
    aux données via l'API REST du serveur (`RemoteDataSource`, httpx).
  - Les deux implémentent la même interface `DataSource` : le code UI ne sait pas où sont les données.
- **Temps réel** (✅ étape 8) : toute modification est diffusée pour que les autres écrans se rafraîchissent
  seuls (≈ 0,5 s) : bus d'événements interne (`core/events.py`) → pages web du serveur directement, clients
  bureau par un flux **SSE** (`GET /api/v1/events`, simple HTTP en flux, au lieu du WebSocket prévu). Seul un
  signal « ces tables ont changé » est diffusé ; chaque écran relit ce qu'il a le droit de voir. La page ou
  l'appareil à l'origine d'une modification ne se rafraîchit pas une seconde fois (en-tête
  `X-Organizer-Origin` pour le client bureau) ; une page attend la fin d'un glisser-déposer en cours ; un
  client bureau qui se reconnecte se rafraîchit (il a pu manquer des modifications).
- **Pas de mode hors ligne** en v1 : le client bureau a besoin du serveur.

### 2.1 Bibliothèques

| Rôle | Bibliothèque | Version |
|---|---|---|
| Interface web/bureau + serveur HTTP | NiceGUI (FastAPI, Uvicorn, Quasar/Vue) | 4.0.0 |
| ORM + modèles | SQLModel / SQLAlchemy | 0.0.48 / 2.1.8 |
| Hachage des mots de passe | argon2-cffi | 25.1.0 |
| Jetons de session | `secrets` + SHA-256 (bibliothèque standard) | — |
| Client HTTP (client bureau → API) | httpx | 0.28.1 |
| Fenêtre native du client bureau | pywebview (+ PyGObject sous Linux) | 6.2.1 |
| Éditeur markdown | CodeMirror 6 **fourni par NiceGUI** (paquet ESM `nicegui-codemirror`) + composant maison `markdown_editor.js` | 6.x |
| Notifications système (client bureau) | desktop-notifier (D-Bus sous Linux, WinRT sous Windows ; `notify-send` en secours) | 6.2.0 |
| Tests / lint | pytest, pytest-asyncio (tests des pages NiceGUI), ruff (`target-version = py311`) | — |

Fichiers : `requirements.txt` (serveur), `requirements-client.txt` (client bureau), `requirements-dev.txt` (dev).

### 2.2 Arborescence prévue

```
organizer/
  config.py              # chemins, port, paramètres (variables d'environnement)
  core/                  # ✅ étape 1
    enums.py             # Importance, Urgence, Statut, Type… : valeur, libellé, emoji, infobulle, couleur
    models.py            # tables SQLModel
    schemas.py           # objets échangés (Pydantic) : *In / *Patch / *Out, filtres, tri
    db.py                # moteur SQLite (clés étrangères, WAL), création du schéma
    errors.py            # erreurs métier (message français affichable)
    rules.py             # règles pures : échéances, rappels, matrice, Ctrl+drop, recherche, calendrier
    unit_of_work.py      # transactions + capture automatique de l'historique annuler / rétablir
    services/            # users, auth, account, labels (projets + tags), items (base commune), tasks,
                         # agenda (événements), boards, attachments, undo ;
                         # façade `Services`
    datasource.py        # interface DataSource + LocalDataSource (serveur)
  server/                # ✅ étape 2
    app.py               # point d'entrée serveur : build() + ui.run()
    state.py             # état global : base, services, anti force brute, tickets de connexion
    security.py          # middleware d'authentification (cookie / Bearer), cookies
    wiring.py            # assemblage : middleware, erreurs, routes (partagé avec les tests)
    web_auth.py          # /auth/complete (ticket → cookie), /auth/logout
    pages.py             # /login, /setup + branchement des pages de l'UI sur LocalDataSource
    api/                 # routes REST /api/v1 (auth, users, labels, tasks, boards, undo, events : SSE)
    pwa.py               # manifeste, service worker, en-têtes iOS / Android, icônes /icons
  client/                # ✅ étape 7
    app.py               # DesktopClient : /connect, pages sur RemoteDataSource, verrou de la fenêtre, main()
    api.py               # ApiClient (httpx, jeton Bearer) ; erreurs HTTP → erreurs métier
    remote.py            # RemoteDataSource : mêmes méthodes que les services, via l'API
    config.py            # client.json (serveur, identifiant, jeton) ; adresse saisie → URL
    system.py            # ouvrir fichiers / liens, dossiers de configuration et de cache
    notifications.py     # rappels → notifications système (une fois par jour et par tâche)
  ui/                    # ✅ étape 3
    theme.py             # couleurs Quasar dérivées des enums (imp0…, urg0…, st0…), CSS des cartes, sombre
    context.py           # UiContext : source de données, rafraîchissement, Ctrl+Z, erreurs → toasts
    format.py            # dates en français (« Aujourd'hui », « lun. 9 nov. », « dans 3 j »)
    layout.py            # en-tête (☰, ↩️ ↪️, compte), colonne de gauche, raccourcis clavier, bouton ➕
    components/          # task_card, level_slider, task_editor, markdown_editor, filter_bar, task_list,
                         # search_dialog, tag_chips, dnd (.py + .js : glisser-déposer),
                         # resizer (.py + resize.js : largeur des colonnes)
    pages/               # home, tasks (+ recherche), kanban, matrix, calendar, settings
  assets/                # icônes (SVG source, PNG, ICO, maskable, apple-touch) — scripts/make_icons.sh
tests/
scripts/demo.py          # démo terminal + données d'exemple (base data/demo.db)
deploy/                 # install.sh (serveur : venv + service systemd généré), update.sh, common.sh,
                         # install_test.sh (bascule sur la branche de test cloclo), restore.sh
run_server.py
run_client.py
```

---

## 3. Utilisateurs, authentification, partage

- **Comptes** : le **premier compte créé est admin** (écran d'initialisation au premier lancement). L'admin crée
  les autres comptes ; pas d'inscription libre.
- **Mots de passe** : **12 caractères minimum** pour tout nouveau mot de passe (création, changement,
  réinitialisation par l'admin). Un compte dont le mot de passe est plus ancien et plus court se connecte
  toujours, mais la connexion le repère (seul moment où le serveur voit le mot de passe : la base ne garde
  que son empreinte) et pose la préférence `security:weak_password` → **bandeau orange** « ⚠️ Votre mot de
  passe est court… » en haut des pages (web et client bureau), bouton « Changer » vers Réglages → Profil ;
  retirée dès que le mot de passe change.
- **Connexion web** : identifiant + mot de passe, case « 🍪 Se souvenir de moi » → cookie de session
  (HttpOnly, SameSite=Lax, et `Secure` quand le visiteur est en HTTPS) valable **30 jours** ; sinon cookie de
  session de navigateur.
- **Connexion client bureau** : adresse du serveur + identifiant + mot de passe → **jeton API** stocké dans le
  dossier de config utilisateur (jamais le mot de passe). Reconnexion automatique au lancement.
- **Sessions** : visibles et révocables dans les réglages (« appareils connectés »).
- **Détails techniques** :
  - jeton aléatoire de 256 bits ; **seule son empreinte SHA-256** est en base (table `auth_session`) ;
  - sessions **glissantes** : chaque utilisation (au plus toutes les 10 min) repousse l'expiration
    (web « se souvenir de moi » : 30 j ; web sans : 24 h d'inactivité ; client bureau : 90 j) ;
  - connexion web en deux temps : la page `/login` vérifie le mot de passe côté serveur et émet un **ticket**
    à usage unique (60 s) ; le navigateur est redirigé vers `/auth/complete?ticket=…`, dont la réponse HTTP pose
    le cookie `organizer_session` (HttpOnly, SameSite=Lax). Le mot de passe ne transite jamais par du JS ;
  - **anti force brute** à deux niveaux : 5 échecs en 10 min pour un couple (adresse IP, identifiant) →
    blocage temporaire de ce visiteur (remis à zéro par une connexion réussie) ; **20 échecs en 1 h pour un
    identifiant, toutes adresses confondues** → nouvelles connexions à ce compte refusées jusqu'à ce que les
    échecs sortent de la fenêtre (les appareils déjà connectés le restent ; pas remis à zéro par une
    connexion réussie). Les compteurs portent sur l'identifiant tapé, existant ou non. Seuils réglables
    (`Settings.login_*`) ;
  - **journal** : chaque échec, blocage, refus et connexion réussie est écrit (logger `organizer.auth`,
    identifiant + IP du visiteur) dans la sortie du service → `journalctl -u organizer` ;
  - changer son mot de passe déconnecte les autres appareils ; désactiver un compte ou réinitialiser son
    mot de passe (admin) le déconnecte partout ;
  - les redirections après connexion n'acceptent que des chemins internes (pas de redirection ouverte).
- **API REST** `/api/v1`, documentée sur **`/docs`** (réservé aux utilisateurs connectés) : authentification par `Authorization: Bearer <jeton>`
  (client bureau) ou par le cookie (navigateur). Erreurs en JSON `{"detail": "message en français"}`.
- **Visibilité des tâches** :
  - chaque tâche a un **propriétaire** ; elle est privée par défaut ;
  - elle peut être **partagée** avec d'autres utilisateurs (droit d'édition) ;
  - **partager un board** donne accès aux tâches posées dessus (et à leurs sous-tâches) ;
  - les **sous-tâches suivent la visibilité de leur parent** (une sous-tâche créée par un invité lui
    appartient, mais reste visible de tous ceux qui voient le parent) ;
  - **supprimer** et **partager** sont réservés au propriétaire (pour supprimer : propriétaire de la tâche ou
    de son parent) ;
  - être admin ne donne **pas** accès aux tâches privées des autres.
- **Projets et tags** : chacun est **🌍 public** (visible et utilisable par tous) ou **🔒 privé** (visible
  uniquement par son créateur), au choix. Voir 4.5.
- **Accès** : réseau local en HTTP (`http://<pi>:2603`) et, en option, **depuis Internet** en HTTPS par un
  proxy installé sur le Pi (Cloudflare Tunnel retenu, `https://organizer.blou.top`). Voir §10.4.

---

## 4. Modèle de données

### 4.1 Tâche

| Attribut | Détail |
|---|---|
| Titre | texte court, obligatoire |
| Importance | 4 niveaux (voir 4.2) |
| Urgence | 4 niveaux (voir 4.2) |
| Échéance (due date) | date, optionnelle, éditable (heure optionnelle) |
| Statut | ⏳ Pas commencé · 🚧 En cours · ⏸️ En pause · ✅ Fini · ❌ Annulé |
| Type | 📌 À faire · 👁️ Suivi |
| Date de rappel | pour le type Suivi (voir 4.3) |
| Projet / sujet | un seul projet (optionnel), choisi dans la liste des réglages |
| Tags | plusieurs, choisis dans la liste des réglages |
| Notes | markdown (voir §6) |
| Liens | hyperliens, chemins de fichiers locaux, pièces jointes (voir 4.4) |
| Parent | tâche parente si c'est une sous-tâche (voir §5) |
| Méta | propriétaire, partages, création, modification, date de fin |

### 4.2 Niveaux (avec emoji, couleur et infobulle)

| Niveau | Importance | Urgence |
|---|---|---|
| 1 | ⚪ Mineure — « Peu d'impact si ce n'est pas fait » | 🐢 Quand possible — « Aucune pression de temps » |
| 2 | 🔵 Normale — « Utile, à faire en temps voulu » | 🕐 Bientôt — « À traiter dans les prochains jours » |
| 3 | 🟠 Importante — « Impact réel, à ne pas négliger » | ⏰ Pressant — « À traiter rapidement » |
| 4 | 🔴 Critique — « Conséquences lourdes si raté » | 🔥 Immédiat — « À traiter maintenant » |

Infobulles détaillées également sur les statuts et les types.

### 4.3 Type Suivi et rappel

- Par défaut, **rappel = échéance − N jours** (N = 2 par défaut, réglable globalement et par tâche).
  Si l'échéance bouge, le rappel suit.
- Le rappel peut être **fixé manuellement** : il ne suit plus l'échéance (bouton 🔗 pour le re-corréler).
- Au rappel : la tâche remonte sur l'**accueil** (section 🔔 Rappels) et le **client bureau** affiche une
  **notification système**.

### 4.4 Liens

| Type | Web / téléphone | Client bureau |
|---|---|---|
| 🌐 Hyperlien | ouvre un nouvel onglet | ouvre le navigateur par défaut |
| 📁 Chemin local (`C:\…`, `/home/…`) | **copie le chemin dans le presse-papiers** (+ toast) | ouvre avec l'application par défaut de l'OS |
| 📎 Pièce jointe (envoyée au serveur) | téléchargement / ouverture | téléchargement puis ouverture |

**Reconnaissance web / fichier** (`rules.detect_link_kind`) : est un **chemin** ce qui commence par `/`, `~`,
`./`, `../`, `C:\`, `\\serveur` ou `file://`, ainsi qu'un simple nom de fichier (`notes.txt`) ; est une
**adresse web** ce qui a un protocole (`https://`, `mailto:`…), commence par `www.`, est un serveur local
(`localhost:2603`, `192.168.1.20:2603`) ou ressemble à un nom de domaine (`google.fr`, `exemple.com/page`).
Sans protocole, on ouvre en `https://` (en `http://` pour un serveur local). Dans les notes, une adresse
reconnue comme web par le markdown est toujours ouverte.

Pièces jointes : stockées dans `data/uploads/` (50 Mo max par fichier), accessibles au déposant et à quiconque
voit une tâche qui les référence. Seuls les types sûrs (PDF, images, texte brut, mp3/mp4) s'affichent dans le
navigateur ; tout le reste (HTML, SVG…) est forcé en téléchargement, avec `Content-Security-Policy: sandbox`.
Retirer le lien (annulable) conserve le fichier.

### 4.5 Projets et tags

- **Projet / sujet** : nom, emoji, couleur, description, archivé oui/non. Une tâche → zéro ou un projet.
- **Tag** : nom, couleur. Une tâche → plusieurs tags. Autocomplétion dans l'éditeur ; création à la volée
  possible depuis l'éditeur (ajoute le tag à la liste, privé par défaut).
- **Couleur d'un nouveau tag** : choisie automatiquement dans une palette de 24 teintes (`rules.TAG_PALETTE`),
  la plus **éloignée visuellement** (écart ΔE dans l'espace CIELAB) des couleurs des tags existants — et en
  priorité de celles des tags déjà posés sur la tâche en cours d'édition — avec un peu de hasard parmi les
  meilleures candidates. Le dialogue des réglages propose cette couleur, modifiable.
- **Visibilité** : chaque projet / tag a un créateur et un drapeau **🌍 public / 🔒 privé**.
  - Public : visible et utilisable par tous ; modifiable par son créateur et les admins.
  - Privé : visible, utilisable et modifiable uniquement par son créateur.
  - Sur une tâche partagée, un projet ou un tag privé d'un autre utilisateur **n'apparaît pas** aux autres.
  - Les noms doivent être uniques parmi ce qu'un utilisateur voit (ses privés + les publics).
- Gestion complète (créer, renommer, recolorer, réordonner, archiver, supprimer, fusionner deux tags) dans
  **⚙️ Réglages**.

### 4.6 Boards

- **Board** : nom, emoji, propriétaire, partages, type (prédéfini / personnalisé), filtres enregistrés.
- **Colonne** (boards personnalisés) : nom, emoji, couleur, position.
- **Placement** : (board, colonne, tâche, position). Une tâche peut être sur plusieurs boards personnalisés.

### 4.7 📅 Événements (agenda)

Un événement ressemble à une tâche sans importance, urgence ni statut. Les **champs communs** (titre, notes,
projet, tags, partage, liens et pièces jointes, propriétaire, dates de création / modification) viennent
d'une base commune (`ItemBase` pour les tables, `ItemOut` pour les objets échangés, `ItemService` pour la
logique) ; chacun a sa table (`task` / `event`) et ses tables de liaison (`event_tag`, `event_share`,
`event_link`).

- **Début et fin** : dates et heures **locales**. Sans heure : **toute la journée**, du premier au dernier
  jour inclus (plusieurs jours possibles). Avec heures : la fin doit être après le début ; sans heure de
  fin, il dure **une heure** ; il peut passer minuit (un événement qui finit à minuit pile ne déborde pas
  sur le lendemain).
- **Lieu** : texte libre ou lien. Un lien (Google Maps…) s'ouvre tel quel ; un texte ouvre une recherche
  Google Maps. **Waze** : navigation vers l'adresse, ou vers les coordonnées d'un lien qui en contient
  (`…/@48.85,2.35,…`, `?q=48.85,2.35`) ; pas de Waze pour un lien court sans coordonnées.
- **Couleur** : celle du projet, sinon un bleu par défaut ; une couleur choisie la remplace.
- **Visibilité et droits** : privé (par défaut), **partagé** avec des personnes — chacune **modifiable** ou
  en **lecture seule** —, et/ou **public** (visible en lecture par tous les comptes du serveur).
  Supprimer, partager, rendre public, transformer : propriétaire seulement. Comme pour les tâches, un tag
  privé d'un autre utilisateur est invisible et préservé.
- **Conversion tâche ↔ événement** (une seule action, annulable) : titre, notes, projet, tags, partages et
  liens sont repris ; tâche → événement : début à l'échéance (ou aujourd'hui à 9 h), une heure ; événement
  → tâche : échéance = début. Réservé au propriétaire ; impossible pour une sous-tâche ou une tâche qui a
  des sous-tâches.
- API : `/api/v1/agenda` (`/events` est déjà le flux temps réel) — `POST /agenda/query` (période, portée,
  texte, projets, tags), `POST /agenda`, `GET|PATCH|DELETE /agenda/{id}`, `PUT /agenda/{id}/shares`,
  `POST /agenda/{id}/links`, `PATCH|DELETE /agenda-links/{id}`, `POST /agenda/{id}/attachments`,
  `POST /agenda/{id}/to-task`, `POST /tasks/{id}/to-event`.

---

## 5. Sous-tâches

- Une sous-tâche est une **vraie tâche** (tous les attributs) rattachée à un parent. **Un seul niveau** de
  profondeur.
- **Éditeur du parent** : section « 🌳 Sous-tâches » : ajout rapide (titre + Entrée), case pour terminer d'un clic,
  ✏️ pour ouvrir l'éditeur complet, réordonnancement par glisser-déposer. À la création, la sous-tâche hérite
  importance / urgence / échéance / projet du parent (modifiables).
- **Carte du parent** : barre de progression `▰▰▰▱▱ 3/5` (les annulées ne comptent pas).
- **Carte d'une sous-tâche** : badge `↳ Nom du parent`, cliquable.
- **Automatismes** :
  - une sous-tâche passe « En cours » → le parent passe « En cours » s'il était « Pas commencé » ;
  - toutes les sous-tâches finies → **proposition** (non forcée) de terminer le parent ;
  - échéance de la sous-tâche postérieure à celle du parent → ⚠️ avec infobulle.
- **Suppression d'un parent** : choix entre supprimer les sous-tâches ou les détacher (deviennent indépendantes).
- **Affichage** : masquées par défaut dans kanbans / matrice / liste (filtre « inclure les sous-tâches ») ;
  remontent quand même sur l'accueil si en retard ou urgentes.

### 5.1 Rattacher par glisser-déposer (Ctrl + drop) — ✅ étape 6

Partout où des tâches apparaissent en cartes (liste, kanbans, matrice, accueil, recherche) :

- **Glisser-déposer** normal : déplace la carte (change colonne / quadrant / ordre). À la souris, la carte se
  saisit après quelques pixels de mouvement ; un « fantôme » suit le pointeur, la carte d'origine s'estompe, la
  zone survolée se surligne (bleu ; rouge si le dépôt y est interdit, avec la raison dans une bulle) ;
  Échap annule. Un clic simple ouvre toujours l'éditeur.
- **Glisser avec Ctrl enfoncé au-dessus d'une autre carte** : la carte cible se met en **surbrillance** ;
  au relâchement, la tâche déposée **devient une sous-tâche de la cible**.
  - 🟢 Surbrillance verte : rattachement possible.
  - 🔴 Surbrillance rouge + bulle explicative : impossible, et rien ne se passe. Cas :
    la cible est elle-même une sous-tâche · la tâche déposée a déjà des sous-tâches · cible = elle-même.
  - Si la tâche déposée était déjà sous-tâche d'un autre parent, elle change de parent.
  - **Pas de confirmation** : l'action est immédiate (petit message « 🌳 … → sous-tâche de … ») et s'annule
    avec **Ctrl+Z** (voir §6.1).
  - Une bulle rappelle l'astuce quand on survole une carte : « Ctrl : en faire une sous-tâche ».
- **Détacher** : bouton « Détacher du parent » dans l'éditeur et dans le menu de la carte.
- **Sur téléphone** (pas de touche Ctrl) : **appui long** (~0,35 s, petite vibration) pour saisir la carte, puis
  on la glisse ; le défilement est bloqué tant qu'on porte la carte (un doigt qui bouge tout de suite fait
  défiler normalement). La **maintenir ~1 s au-dessus d'une autre carte** passe en mode rattachement (même
  code couleur), et le relâchement rattache. Partout aussi : menu ⋯ de la carte → **« 🌳 Rattacher à… »**
  (recherche, seules les tâches pouvant l'accueillir sont proposées).
- **Défilement automatique** : pendant un glisser, approcher la carte du bord de l'écran (ou du kanban)
  fait défiler la page ou les colonnes.
- Implémentation : un seul composant par page (`ui/components/dnd.js`), qui gère souris, événements tactiles
  et, à défaut, événements « pointer » ; les règles de rattachement sont dupliquées côté navigateur pour la
  surbrillance instantanée et revérifiées par le serveur.

---

## 6. Éditeur de tâche (et d'événement)

S'ouvre en panneau latéral (bureau) ou en plein écran (téléphone). Le même panneau sert aux tâches et aux
**événements** : la bascule **📋 Tâche / 📅 Événement** de l'en-tête passe de l'un à l'autre (§6.2).

- **Titre** en grand, éditable directement.
- **Curseurs (slide bars)** pour importance, urgence, statut et type : on peut glisser ou cliquer directement
  sur un cran. Chaque cran a son emoji et son **infobulle** explicative ; la couleur du curseur suit le niveau.
- **Échéance** : sélecteur de date + raccourcis (Aujourd'hui, Demain, +1 semaine, Aucune).
- **Rappel** (type Suivi) : décalage en jours ou date manuelle (voir 4.3).
- **Projet**, **tags** (autocomplétion), **partage**.
- **Liens** : liste avec icône par type, ajout d'URL / chemin local / pièce jointe.
- **Sous-tâches** (voir §5).
- **Notes markdown façon Obsidian** (CodeMirror 6, *live preview*, ✅ étape 4) :
  - la mise en forme s'applique pendant la frappe : titres `#`…`######`, **gras**, *italique*, ~~barré~~,
    `code`, blocs de code, citations `>`, règles `---`, liens `[texte](url)`, adresses web et chemins de
    fichiers (`/home/…`, `~/…`, `C:\…`) soulignés ;
  - la syntaxe est **masquée** et réapparaît quand le curseur la touche (titres et citations : quand le curseur
    est sur la ligne ; puces et cases : quand il est dans le marqueur) ; sans le focus, tout est rendu ;
  - puces `-` / `*` affichées « • » ; numéros colorés ; `- [ ]` / `- [x]` affichés en **cases à cocher
    cliquables** (tâche cochée barrée) ;
  - **continuation automatique des listes** : Entrée sur `1. …` crée `2. ` (et renumérote la suite), sur
    `- …` crée `- `, sur `- [ ] …` crée `- [ ] ` ; Entrée sur un élément vide termine la liste ; Retour
    arrière en début d'élément retire la puce ; Tab / Maj+Tab indente / désindente (4 espaces) ;
  - **clic** sur un lien, une adresse ou un chemin → ouverture selon le §4.4 (web : nouvel onglet ;
    chemin : copié dans le presse-papiers ; client bureau : ouverture du fichier), sans déplacer le curseur.
    Si le curseur est déjà dans le lien (on l'édite, sa syntaxe est visible), le clic sert à éditer et
    **Ctrl+clic** (⌘+clic sur Mac) l'ouvre. Le double-clic ouvre aussi (une seule ouverture) ;
  - **Ctrl+Z / Ctrl+Maj+Z dans les notes** = annulation de la frappe (historique propre à l'éditeur) ; ils
    ne déclenchent pas l'annulation des actions de la page ;
  - enregistrement : au plus toutes les 1,5 s pendant la frappe, à la sortie du champ et à la fermeture de
    l'éditeur.
- **Sauvegarde automatique** (avec indicateur discret « ✔ enregistré ») : curseurs et listes immédiatement,
  titre à la sortie du champ (ou Entrée), notes toutes les 1,5 s pendant la frappe et à la sortie du champ.
- **Création** : le bouton ➕ (ou **N**) ouvre l'**éditeur complet** sur un *brouillon* : curseurs, échéance,
  projet, tags et notes se règlent avant même le titre ; la tâche est créée dès qu'elle a un titre (sortie du
  champ, Entrée ou fermeture de l'éditeur) — une seule entrée « Créer » dans l'historique. Sans titre, rien
  n'est créé. Sous-tâches, liens et partage sont disponibles une fois la tâche créée. Bouton
  « ➕ Nouvelle tâche » en bas de l'éditeur pour enchaîner.
- **Lien direct** : `?task=<id>` dans l'URL d'une page ouvre l'éditeur de cette tâche au chargement ;
  `?task=new` ouvre l'éditeur sur une nouvelle tâche.
- **Curseurs** : chaque cran occupe une cellule de même largeur (emoji + libellé + infobulle) ; on glisse,
  on clique sur la piste ou sur l'emoji. La couleur du curseur suit la valeur.
- **Échéance** : champ date + **heure facultative** + raccourcis Aujourd'hui / Demain / +1 semaine / Aucune
  (effacer la date efface l'heure) ; rappel de suivi :
  « 🔗 Lié à l'échéance » (jours avant) ou « 📌 Date fixe ».
- **Sous-tâches** dans l'éditeur du parent : case à cocher pour terminer, clic pour ouvrir, ajout rapide.
  Quand la dernière est cochée : fenêtre « 🎉 Terminer la tâche parente ? ».
- **Liens** : saisie libre (hyperlien ou chemin détecté automatiquement), bouton « 📎 Joindre un fichier »
  (plusieurs fichiers à la fois), et **dépôt de fichiers** (glissés depuis le système) n'importe où sur
  l'éditeur, qui s'encadre « 📎 Déposer pour joindre » pendant le survol, ou sur la **carte / ligne d'une
  tâche** (n'importe quelle page), encadrée pendant le survol, qui joint le fichier à cette tâche. Sur une
  nouvelle tâche pas encore créée : message « Donnez d'abord un titre ». Ailleurs sur la page, le dépôt est
  refusé (le navigateur ou la fenêtre du client bureau n'ouvre pas le fichier à la place de l'application).
  Si le moteur ne transmet que l'adresse `file://` du fichier (sans son contenu), le client bureau lit le
  fichier sur le poste ; un navigateur affiche un message. Fenêtre du client bureau sous Linux : WebKitGTK
  ne donne à la page ni le contenu ni l'adresse (adresses `file://` masquées) ; la fenêtre capte les
  adresses côté GTK (`drag-data-received`, `client/window.py`) et les relaie à la page
  (`window.organizerNativeDrop`). Dépôts sans cible notés dans le journal.

### 6.0 📅 Éditeur d'événement

- **Début / fin** : interrupteur « 🌙 Toute la journée » (jours de début et de fin), sinon date et heure de
  début et de fin ; résumé en clair avec la durée (« sam. 21 nov. 2026 · 20:00 → 22:30 (2 h 30) »).
  Changer le début **garde la durée** (la fin suit) ; une fin avant le début est refusée.
- **📍 Lieu** + boutons 🗺️ Google Maps et 🚗 Waze (§4.7).
- **🎨 Couleur** : « Auto » (couleur du projet), 12 couleurs proposées, ou une couleur libre (pipette).
- Projet, tags, liens et fichiers, notes : comme pour une tâche.
- **📢 Public** (propriétaire) et **👥 Partager avec** : chaque personne est « ✏️ Peut modifier » ou
  « 👁️ Lecture seule ».
- **Lecture seule** (événement public d'un autre, ou partagé sans droit de modification) : affichage sans
  champs de saisie (horaires, lieu avec Maps / Waze, projet, tags, liens, notes), « 👤 Appartient à … ».
- Adresse directe : `?event=<id>` (ou `?event=new`), comme `?task=`.

### 6.0 bis 🔁 Bascule tâche ↔ événement

- **Brouillon** : on passe de l'un à l'autre en gardant titre, notes, projet et tags ; les champs propres à
  l'un (curseurs, ou horaires / lieu…) sont gardés pour une rebascule. Une échéance devient un début (et
  inversement).
- **Élément existant** (propriétaire seulement ; pas pour une sous-tâche ni une tâche qui a des
  sous-tâches) : il est **converti** (§4.7) en **une seule action** annulable ; si on rebascule dans la même
  session, les champs propres d'avant sont repris dans la même action.

### 6.1 ↩️ Annuler / rétablir (général)

- **Ctrl+Z** annule la dernière action, **Ctrl+Maj+Z** (ou **Ctrl+Y**) la rétablit — partout dans l'application.
- Dans un champ texte ou l'éditeur de notes ayant le focus, Ctrl+Z annule d'abord la **frappe** (historique
  propre à l'éditeur) ; hors champ, c'est l'historique des actions qui est utilisé.
- Actions annulables : création, modification (attributs, notes, liens…), suppression, déplacement de carte,
  rattachement / détachement de sous-tâche, changements de projets / tags / boards.
- **Historique par utilisateur, côté serveur** (50 dernières actions) : il fonctionne de la même façon sur le
  web, le téléphone et le client bureau. Les modifications successives rapides d'un même champ
  (sauvegarde automatique) sont regroupées en une seule action.
- Chaque action enregistre l'état **avant / après** des lignes touchées (capture automatique dans
  `core/unit_of_work.py`, table `undo_entry`). Si une ligne a été modifiée depuis (par quelqu'un d'autre),
  l'annulation est refusée avec un message explicite plutôt que d'écraser ce travail, et l'action est retirée
  de l'historique pour que le Ctrl+Z suivant porte sur la précédente.
- Une nouvelle action vide la pile « rétablir ».
- Fusion : même tâche + mêmes champs modifiés, à moins de 5 s d'intervalle → une seule entrée.
- Un petit toast indique ce qui a été annulé (« ↩️ Annulé : déplacement de *X* »).
- **Téléphone** : boutons ↩️ / ↪️ dans la barre du haut (visibles seulement s'il y a quelque chose à annuler).

---

## 7. Cartes de tâches

Repérer l'état d'une tâche d'un coup d'œil :

| Élément visuel | Signification |
|---|---|
| **Liseré gauche** coloré (épaisseur croissante) | importance |
| Emoji d'urgence en haut à droite (🔥 pulse doucement) | urgence |
| **Fond teinté** léger | statut (en cours = bleu léger, en pause = jaune pâle, …) |
| Fini : carte estompée, titre barré · Annulé : gris, bordure pointillée | statut terminal |
| Pastille d'échéance : 🔴 en retard · 🟠 aujourd'hui · 🟡 ≤ 3 jours · neutre sinon | échéance |
| 📌 / 👁️ + 🔔 date de rappel | type et rappel |
| Puce projet (emoji + couleur) | projet |
| Pastilles colorées (fond teinté de la couleur du tag) | tags — même rendu dans l'éditeur et les filtres |
| `▰▰▱ 2/3` | progression des sous-tâches |
| `↳ Parent` | c'est une sous-tâche |
| 📝 / 🔗 n / 👥 | a des notes / des liens / est partagée |

Chaque élément a une **infobulle**. Clic → éditeur ; menu ⋯ → actions rapides (changer statut, 📋 dupliquer,
détacher, supprimer ; rattacher à venir). Supprimer est immédiat (Ctrl+Z annule) ; si la tâche a des
sous-tâches, on demande s'il faut les supprimer aussi ou les garder.

---

## 8. Navigation et modules

**Colonne de gauche** (repliable ; menu ☰ sur téléphone) :

1. 🏠 **Accueil** — résumé des points chauds
2. 📋 **Toutes les tâches** — liste générale
3. 📊 **Kanbans** — boards prédéfinis + personnalisés
4. 🎯 **Matrice d'Eisenhower**
5. 📅 **Calendrier** — grille du mois
6. 🔍 **Recherche** (aussi accessible partout par `Ctrl+K`)
7. ⚙️ **Réglages**

Bouton flottant **➕ Nouvelle tâche** sur tous les écrans (raccourci **N**) : ouvre l'éditeur complet en
mode création (voir §6).

**En-tête** : ☰ (afficher / masquer la colonne), ↩️ / ↪️ (annuler / rétablir, infobulle = action concernée,
grisés s'il n'y a rien), menu du compte (réglages, déconnexion).

**Raccourcis** : Ctrl+Z, Ctrl+Maj+Z / Ctrl+Y, N (hors champ texte).

### 8.1 🏠 Accueil

- Salutation + date du jour.
- 🔥 **En retard** · 📅 **Aujourd'hui** · 🔔 **Rappels** (suivis dont le rappel est atteint) ·
  🎯 **À faire maintenant** (quadrant « Faire ») · 🚧 **En cours**.
- Compteurs : ouvertes, en retard, en cours, finies cette semaine. **Cliquer sur un compteur** déplie sous
  les compteurs un panneau avec les cartes des tâches concernées (re-cliquer ou ✕ pour replier).

### 8.2 📋 Liste générale

- Cartes, **tri** : ⚡ priorité combinée, 📅 échéance, 🔴 importance, 🔥 urgence, 🆕 création,
  ✏️ modification, 🔤 titre — avec bouton ↓/↑ pour inverser ; **regroupement** : aucun, projet, statut, type,
  échéance, importance (une section titrée par groupe, avec son nombre de tâches).
- Barre de filtres (voir 8.5) ; compteur « N tâches ».
- Les tâches finies / annulées sont repliées en bas (« ✅ Terminées et annulées ») sauf si un filtre de
  statut est actif.
- **Filtres, tri et regroupement sont mémorisés** pour chaque utilisateur (en base, table `user_pref` : ils
  suivent l'utilisateur sur tous ses appareils).
- *Vue compacte (une ligne par tâche) : à venir.*

### 8.2 bis 🔍 Recherche

- **Ctrl+K** (ou 🔍 dans l'en-tête), partout : fenêtre de recherche, résultats pendant la frappe (titre,
  notes, tags, projet ; sans accents ni majuscules), sous-tâches et tâches terminées comprises (les ouvertes
  d'abord). Clic ou Entrée → ouvre l'éditeur de la tâche. « Recherche avancée → » ouvre la page.
- Page **`/search?q=…`** : même liste que « Toutes les tâches » (filtres, tri, regroupement), sous-tâches
  incluses et tâches terminées mélangées aux autres ; préférences mémorisées séparément.

### 8.3 📊 Kanbans

Boards **prédéfinis** (déplacer une carte modifie l'attribut correspondant) :

| Board | Colonnes | Effet du dépôt |
|---|---|---|
| 📊 Par statut | les 5 statuts | change le statut |
| 📅 Par échéance | ⚠️ En retard · 📅 Aujourd'hui · 🌅 Demain · 🗓️ Cette semaine · 🔭 Plus tard · ∅ Sans échéance | Aujourd'hui / Demain → cette date ; Cette semaine → vendredi ; Plus tard → +7 j ; Sans échéance → efface ; En retard → dépôt interdit |
| 🗂️ Par type | 📌 À faire · 👁️ Suivi | change le type |
| 📁 Par projet | un projet par colonne + « Sans projet » | change le projet |

Les colonnes des boards prédéfinis sont triées par **urgence**, puis par un **rang manuel** (table
`task_rank`, puis importance et échéance à égalité). **Reclasser** une carte dans une colonne (ou la déposer à
un endroit précis d'une autre colonne) affine ainsi son urgence :

- un trait bleu montre où la carte va s'insérer ;
- son urgence est ramenée au minimum nécessaire pour rester entre ses voisines (ex. : déposée au-dessus
  d'une carte 🔥, elle devient 🔥 ; déposée sous une carte 🕐 en bas de colonne, elle devient 🕐) ;
- son rang fixe sa place parmi les cartes de même urgence (rang partagé par tous les boards prédéfinis et
  par le tri « Urgence » de la liste) ;
- changement de colonne + reclassement = **une seule** action annulable (`TaskService.move`, API
  `POST /tasks/{id}/move`).

La colonne « En retard » refuse les dépôts venus d'ailleurs, de même que « Cette semaine » le samedi et le
dimanche (il ne reste plus de jour après demain) ; on peut toujours y reclasser ses propres cartes.

Boards **personnalisés** (✅ étape 6) : colonnes libres (nom, emoji, couleur), cartes rangées à la main par
glisser-déposer (l'ordre dans la colonne est conservé), une tâche peut figurer sur plusieurs boards.

- Création : « ➕ Nouveau board » (nom + emoji ; colonnes de départ 📥 À faire · 🚧 En cours · ✅ Fait).
- « ➕ Ajouter des tâches » : sélecteur avec recherche, choix de la colonne d'arrivée.
- Menu de colonne : modifier (nom, emoji, couleur), déplacer à gauche / à droite, supprimer (ses cartes
  passent dans la première colonne restante).
- Menu ⋯ des cartes : « ➖ Retirer du board » (la tâche n'est pas supprimée).
- « ⚙️ Board » (propriétaire) : renommer, 👥 partager, supprimer. Les **membres** d'un board partagé voient
  les tâches posées dessus (et leurs sous-tâches) et peuvent déplacer / ajouter / retirer des cartes, mais
  pas gérer le board. Retirer une tâche du board retire cet accès.
- Toutes les opérations sont annulables (Ctrl+Z).

Pour tous les boards :

- Sélecteur de board en haut de page ; board courant dans l'URL (`/kanban?board=status|due|kind|project|<id>`)
  et mémorisé (dernier board ouvert).
- Option « 🙈 Masquer les terminées depuis plus de 1 / 3 / 7 / 30 jours », « toutes » ou « aucune » (7 jours
  par défaut).
- Page en **pleine largeur**, colonnes **jusqu'en bas de la fenêtre** (toute la hauteur est une zone de
  dépôt) ; colonnes de 264 px par défaut.
- Bouton ⇤ dans l'en-tête d'une colonne : la **replier** en bande étroite (titre vertical, compteur), qui
  reste une zone de dépôt (la carte va alors en fin de colonne, sans reclassement) ; clic sur la bande pour
  la déplier.
- **Redimensionner** une colonne en tirant son bord droit (souris ou doigt, 200 à 720 px) ; double-clic sur
  le bord : largeur par défaut.
- Barre de filtres (voir 8.5) ; filtres, option, colonnes repliées et largeurs mémorisés **par board**
  (préférence `board:<clé>`).
- Téléphone : colonnes d'au plus ~86 % de l'écran qui défilent horizontalement, une par une.

### 8.4 🎯 Matrice d'Eisenhower

Module indépendant, fonctionne comme un **kanban en 2D** :

- **Vue 2×2** (par défaut) — axes : important = importance ≥ 3, urgent = urgence ≥ 3 :
  🔥 **Faire** (important + urgent) · 📅 **Planifier** (important, pas urgent) ·
  🤝 **Déléguer** (urgent, pas important) · 🗑️ **Éliminer** (ni l'un ni l'autre).
- Déposer une carte dans un autre quadrant ajuste importance / urgence au **minimum nécessaire** pour
  entrer dans ce quadrant (ex. importance 2 → 3 ; une valeur déjà compatible n'est pas modifiée).
- **Vue détaillée 4×4** (bascule) : une case par combinaison exacte ; le dépôt fixe les deux valeurs. Les
  tâches y sont affichées en lignes compactes (elles aussi déplaçables), chaque case teintée de la couleur
  de son quadrant.
- Disposition classique : urgent à gauche, important en haut (axes affichés).
- Mêmes filtres que les kanbans ; par défaut, filtre « statut ouvert » (les tâches finies / annulées sont
  masquées) ; vue et filtres mémorisés (préférence `view:matrix`).
- Téléphone : les quatre quadrants sont empilés.

### 8.4 bis 📅 Calendrier

Page `/calendar` (pleine largeur, pleine hauteur) — **première étape** du chantier « événements » (voir
`TODO.md`) :

- Grille classique du mois : **7 colonnes, du lundi au dimanche**, 4 à 6 semaines complètes ; les jours des
  mois voisins complètent la première et la dernière ligne (grisés), le week-end est légèrement teinté,
  aujourd'hui est entouré.
- En-tête : ‹ › pour passer au mois précédent / suivant, nom du mois, bouton « Aujourd'hui » (grisé quand
  on est déjà sur le mois en cours). Le mois se choisit aussi par l'adresse : `/calendar?month=2026-11`.
- **Échéances des tâches** (sous-tâches comprises) : petites pastilles elliptiques dans la case du jour,
  de la **couleur de l'urgence** (🐢 vert, 🕐 jaune, ⏰ orange, 🔥 rouge ; texte noir ou blanc selon le fond),
  titre coupé par « … », heure en tête s'il y en a une ; infobulle complète (titre, échéance, urgence,
  importance, statut). **Pourtour** = **importance** (couleur et épaisseur : ⚪ 1 px gris, 🔵 2 px bleu,
  🟠 2 px orange, 🔴 3 px rouge), séparé du fond par un liseré clair (visible même orange sur orange).
  Ordre dans une journée : retards, puis urgence décroissante, heure, titre
  (`rules.calendar_days`). Tâches finies : à leur date, estompées et barrées ; annulées : absentes.
- **Tâches en retard** (échéance passée, pas finie) : affichées **aujourd'hui** (et non plus à leur date),
  pastille ⚠️ à rayures rouge sombre qui pulse ; la case du jour est bordée de rouge.
- **Barre de filtres** au-dessus de la grille, mémorisée (préférence `view:calendar`) : interrupteur
  « 📋 Tâches » (affichées ou non — activé par défaut tant qu'il n'y a pas d'événements) et « Tâches de
  qui ? » : 👤 mes tâches, 🤝 partagées avec moi, 👥 les deux. Légende des couleurs à droite.
- **📥 Sans échéance** : colonne à droite de la grille (sous la grille sous 1024 px de large) avec les tâches
  ouvertes sans échéance, les plus prioritaires d'abord, dans les mêmes pastilles. **Largeur réglable**
  (poignée sur son bord gauche, 160 à 560 px ; double-clic : largeur par défaut) et **repliable** (⇥) en
  une bande étroite (titre vertical, nombre de tâches) qui reste une zone de dépôt ; clic pour la déplier.
  Largeur et repli mémorisés (`view:calendar` → `undated: {width, collapsed}`). Sur petit écran, repliée
  = une barre sous la grille.
- **Glisser-déposer** (souris ; doigt : appui long) : une pastille déposée sur un autre jour prend cette
  échéance (l'heure est gardée) ; déposée sur « Sans échéance », elle perd son échéance (et son heure) ; une
  tâche de « Sans échéance » déposée sur un jour la reçoit. Annulable (Ctrl+Z), toast de confirmation.
  Une tâche en retard reposée sur aujourd'hui prend la date du jour. Ctrl + dépôt sur une autre pastille :
  en faire une sous-tâche (comme partout).
- **Clic** sur une case : la sélectionne (cadre bleu). **Clic-glisser** d'une case à l'autre : sélectionne
  la plage de jours. **Clic droit** : sélectionne la case (sauf si elle fait déjà partie de la sélection) et
  ouvre un menu : « 📅 Nouvel événement » (un jour : de 9 h à 10 h ; plusieurs jours : toute la journée sur
  la plage) et « 📋 Nouvelle tâche » (échéance le premier jour). Sur téléphone, le menu s'ouvre par un
  appui long. **Double-clic sur une pastille** : ouvre l'éditeur
  de la tâche. **Double-clic ailleurs dans la case** (même vide) : la case s'agrandit à toute la fenêtre
  (animation depuis la case) et montre les **cartes complètes** de ses tâches (« ⚠️ En retard » puis
  « 📅 Échéance ce jour ») ; une carte s'ouvre dans l'éditeur, Échap ou ✕ referme.
- Téléphone : mêmes 7 colonnes, cases plus basses, pastilles plus petites ; légende masquée.

### 8.5 Barre de filtres

- Champ texte général (titre, notes, tags, projet ; sans accents ni majuscules).
- Bouton **« 🎛️ Filtres (n) »** qui déplie les menus déroulants multi-sélection : importance, urgence,
  statut, type, projet (dont « ∅ Sans projet »), tags, échéance (en retard / aujourd'hui / demain / cette
  semaine / plus tard / sans échéance), portée (toutes / les miennes / partagées avec moi) ; le nombre de
  critères actifs s'affiche sur le bouton.
- Case « 🌳 Inclure les sous-tâches ». Bouton « ↺ Réinitialiser ».
- Composant réutilisable (`ui/components/filter_bar.py`) : kanbans et matrice à l'étape 6.

### 8.6 ⚙️ Réglages

Page `/settings` à onglets (onglet initial : `?tab=profile|appearance|reminders|projects|tags|devices|users|data`) :

- 👤 **Profil** : nom affiché ; changement de mot de passe (12 caractères minimum ; déconnecte les autres
  appareils).
- 🎨 **Apparence** : thème 🖥️ comme le système / ☀️ clair / 🌙 sombre, appliqué immédiatement et mémorisé
  pour le compte.
- 🔔 **Rappels** : décalage par défaut (jours avant l'échéance), notifications bureau oui/non.
- 📁 **Projets** : créer, modifier (nom, emoji avec palette, couleur, description, 🌍 public / 🔒 privé),
  réordonner (↑ ↓), archiver / désarchiver, supprimer (les tâches restent, sans projet) ; les projets
  publics d'autres utilisateurs sont en lecture seule (sauf pour les admins).
- 🏷️ **Tags** : créer, modifier (nom, couleur, public / privé), réordonner, **fusionner** dans un autre tag,
  supprimer.
- 💻 **Appareils connectés** : navigateurs et clients bureau, date de connexion, dernière activité,
  expiration ; déconnecter un appareil ou tous les autres.
- 👥 **Utilisateurs** (admin) : créer un compte, réinitialiser un mot de passe, désactiver / réactiver,
  donner / retirer les droits admin (pas sur soi-même).
- 🗄️ **Données** (admin) : ⬇️ télécharger une **sauvegarde** du serveur (archive `.tar`, pièces jointes
  incluses ou non ; le navigateur la télécharge, le client bureau l'enregistre dans « Téléchargements ») ;
  🔑 **jetons de sauvegarde** : créer (le secret n'est affiché qu'une fois, avec un exemple `curl`), voir la
  dernière utilisation (date, adresse), révoquer. Voir §10.5.
- 🔌 **Connexion** (client bureau uniquement, voir §10.1).
- *À venir* : 📊 **Boards** (gestion des boards personnalisés depuis les réglages).

Toutes les modifications de projets et de tags sont annulables (Ctrl+Z).

---

## 9. Responsive / téléphone

- La colonne de gauche devient un tiroir (☰).
- Kanbans : colonnes en défilement horizontal au doigt (repliables, redimensionnables) ; matrice 2×2 empilée.
- Éditeur en plein écran ; curseurs utilisables au doigt.
- Glisser-déposer tactile (appui long pour saisir une carte).
- **PWA** (✅ étape 8) : manifeste (`/manifest.webmanifest`), icônes (dont « maskable » pour Android et
  `apple-touch-icon` pour iOS), plein écran (`standalone`), raccourcis « Nouvelle tâche » et « Kanbans »
  (appui long sur l'icône), couleur de la barre d'état selon le thème. Service worker minimal, actif en
  HTTPS : rien en cache (pas de mode hors ligne), mais une page « Serveur injoignable » lisible.
  - **iPhone** : Safari → Partager → « Sur l'écran d'accueil » ; fonctionne en HTTP sur le réseau local.
  - **Android** : en HTTP, Chrome ne crée qu'un raccourci qui s'ouvre dans le navigateur ; le vrai mode
    « application » demande le serveur en **HTTPS** (§10).

---

## 10. Déploiement

- **Serveur** : Raspberry Pi 5, Python 3.11, écoute sur `0.0.0.0:2603`. Données dans `data/`
  (`organizer.db`, `uploads/`), chemin configurable par variable d'environnement.
- **Installation du serveur** : `deploy/install.sh`, lancé depuis le compte de l'utilisateur (avec ou sans
  `sudo`). Il vérifie Python ≥ 3.11, crée `.venv`, installe `requirements.txt`, puis **génère** le service
  systemd `organizer` (`/etc/systemd/system/organizer.service`) : `User=` = celui qui lance la commande —
  `SUDO_USER` sous sudo, **jamais root** (lancé directement en root, le script refuse) —,
  `WorkingDirectory` = dossier du projet, `ORGANIZER_DATA_DIR` / `ORGANIZER_HOST` / `ORGANIZER_PORT` /
  HTTPS selon les options, `Restart=always`, `WantedBy=multi-user.target` (démarrage avec la machine). Le service est activé et
  (re)démarré, et le script attend la réponse de `/api/v1/version` avant d'afficher les adresses. Options
  retenues dans `deploy/server.conf` (non versionné) ; `--print-service`, `--uninstall`. Les étapes
  utilisateur (venv, pip, git) tournent sous ce compte, seules les étapes système passent par sudo.
- **Client bureau** : Linux (GTK/WebKit) et Windows (Edge WebView2), lancé par `run_client.py`
  (`--browser` : dans le navigateur au lieu d'une fenêtre). Voir §10.1.

### 10.1 🖥️ Client bureau (✅ étape 7)

- **Principe** : la même interface que le site (pages `organizer/ui`), servie **localement** sur
  `127.0.0.1` (port libre) et affichée dans une fenêtre native pywebview (GTK forcé sous Linux) ; les
  données passent par l'API REST du serveur (`RemoteDataSource` : mêmes méthodes, mêmes erreurs que les
  services locaux).
- **Connexion** (`/connect`) : adresse du serveur (`raspberrypi.local` ou `192.168.1.20` suffit : `http://`
  et le port 2603 sont ajoutés ; un nom de domaine public sans port, comme `organizer.blou.top`, devient
  `https://organizer.blou.top`), identifiant, mot de passe → **jeton API** (90 jours glissants) enregistré
  dans `client.json` (lisible par l'utilisateur seul ; jamais le mot de passe). Reconnexion automatique ;
  jeton expiré ou révoqué → retour à `/connect` avec un message ; serveur injoignable → message et
  « 🔄 Réessayer ». Un serveur sans compte renvoie vers `/setup` dans un navigateur.
- **Dossier de configuration** : `~/.config/organizer/` (Linux), `%APPDATA%\Organizer\` (Windows) ; cache des
  pièces jointes ouvertes : `~/.cache/organizer/` ; `ORGANIZER_CLIENT_DIR` remplace les deux.
- **Verrou de la fenêtre** : le serveur local n'accepte que la fenêtre lancée (secret aléatoire par lancement,
  passé dans l'URL de départ puis gardé en cookie) ; un autre programme du poste reçoit « 🔒 Accès réservé ».
- **Liens** (§4.4) : adresse web → navigateur par défaut ; chemin local (`~`, variables d'environnement,
  `file://`) → application par défaut du système (« 📁 Introuvable sur ce poste » sinon) ; pièce jointe →
  téléchargée dans le cache puis ouverte.
- **🔔 Rappels** : toutes les 5 minutes, les suivis dont le rappel est atteint sont notifiés (notification
  système, une fois par jour et par tâche, regroupées au-delà de 3) si l'option des réglages est active ; un
  clic ouvre la tâche dans la fenêtre.
- **Réglages → 🔌 Connexion** : serveur, compte, appareil, emplacement de la configuration ; ouvrir le site
  dans le navigateur, tester une notification, se déconnecter / changer de serveur.
- Pas de mode hors ligne ; les modifications faites ailleurs apparaissent au prochain affichage (temps réel :
  étape 8).
- **Arrière-plan** : fermer la fenêtre la **cache** ; le client continue (rappels, raccourcis). La première
  fois dans une session, une notification l'explique. Pour l'arrêter : menu du compte → ⏻ Quitter
  Organizer, action « Quitter » du lanceur, ou `run_client.py --quit`.
- **Instance unique** : un nouveau lancement transmet sa commande au client déjà lancé (≈ 0,07 s) au lieu
  d'en démarrer un second (`instance.json` : port local, secret) : `run_client.py` (afficher),
  `--new-task` (afficher et ouvrir l'éditeur de nouvelle tâche **sur la page affichée**), `--quit`,
  `--hidden` (démarrer caché, pour l'ouverture de session).
- **Raccourcis clavier globaux** (par défaut **Ctrl+Alt+O** : ouvrir, **Ctrl+Alt+N** : nouvelle tâche) :
  déclarés au système par l'installeur, qui lance alors ces commandes. Sous Wayland une application ne peut
  pas écouter le clavier hors de sa fenêtre : KDE Plasma (kglobalaccel, par D-Bus) et GNOME (gsettings) sont
  configurés automatiquement, les autres bureaux reçoivent la commande à associer ; sous Windows, ce sont les
  touches de raccourci des raccourcis du menu Démarrer.
- **Icône** de l'application (`organizer/assets/`, générée depuis un SVG par `scripts/make_icons.sh`) :
  fenêtre, lanceur, menu Démarrer ; identifiant d'application `organizer` (Wayland) pour que la barre des
  tâches associe la fenêtre au lanceur.
- **Réseau local automatique** (`client/lan.py`, `server/local_access.py`) : le client configuré sur l'adresse
  publique demande au serveur (`GET /api/v1/local-access`, avec son jeton) ses adresses sur le réseau local
  (détectées : adresse de sortie et adresses IPv4 privées du Pi, port d'écoute ; aucune si `--host
  127.0.0.1` ; imposées par `ORGANIZER_LOCAL_URLS`) et la **clé du compte** (HMAC de la clé secrète du
  serveur `<données>/instance.key` et de l'identifiant du compte), gardées dans `client.json`. Il essaie ces
  adresses : le serveur doit d'abord **prouver** qu'il connaît la clé (`GET /api/v1/local-access/proof?
  user=…&nonce=…` → HMAC du nombre tiré par le client ; route **réservée aux adresses privées** : impossible
  de la faire calculer au vrai serveur à travers Internet pour la rejouer). Une seule fois prouvée, toutes
  les pages passent par l'adresse locale (`ApiClient.route`, partagée) ; preuve renouvelée avant une requête
  si elle date de plus de 15 s ; retour à l'adresse publique (et seconde tentative de la requête, sauf
  envoi de fichier) dès que le réseau local ne répond plus ; essai du réseau local toutes les 60 s,
  adresses redemandées toutes les 10 min. Désactivable (Réglages → 🔌 Connexion, `lan_enabled`). Sur le
  réseau local, le jeton circule en HTTP simple (comme avant la mise en ligne).
- **Indicateur de connexion** (`ui/components/connection_badge.py`, coin bas gauche de chaque page, rond
  🏠 / 🌍 et infobulle) : client bureau = route en cours (relue toutes les 3 s ; une adresse configurée
  déjà locale compte comme réseau local ; raison affichée si Internet : désactivé, serveur trop ancien,
  introuvable), clic → Réglages → 🔌 Connexion ; web = adresse du visiteur vue par le serveur (privée ou
  publique, derrière Cloudflare) et, par Internet, l'adresse locale conseillée à la maison. Un navigateur ne
  bascule pas tout seul : changer d'adresse, c'est changer d'origine (autre cookie, autre application
  installée, page HTTPS qui ne peut pas appeler une adresse HTTP).

### 10.2 📦 Installation du client bureau

- **Linux** : `install/linux/install.sh` (sans droits root) — vérifie Python ≥ 3.11 et WebKitGTK (commande
  d'installation selon la distribution), crée `.venv`, installe `requirements-client.txt`, puis
  `python -m organizer.client.install` : lanceur `~/.local/share/applications/organizer.desktop` (actions
  « Nouvelle tâche », « Quitter Organizer »), icônes `hicolor`, démarrage caché à l'ouverture de session
  (`~/.config/autostart`), raccourcis globaux. Options : `--no-autostart`, `--no-shortcuts`,
  `--show-key …`, `--new-key …`, `--uninstall`.
- **Windows** : `install\windows\install.bat` (double-clic ; appelle `install.ps1`, sans droits
  administrateur) — trouve Python ≥ 3.11 (`py -3` ou `python`), crée `.venv`, installe les dépendances, crée
  les raccourcis du menu Démarrer (« Organizer » avec Ctrl+Alt+O, « Organizer - Nouvelle tâche » avec
  Ctrl+Alt+N, « Organizer - Quitter »), du Bureau et du dossier Démarrage (`--hidden`) ; ils lancent
  `pythonw.exe` (sans console). Options : `-NoAutostart`, `-NoDesktop`, `-ShowKey`, `-NewKey`, `-Uninstall`
  (`uninstall.bat`).
- Journal du client : `client.log` dans son dossier de configuration (utile quand il tourne sans console).
- Les options choisies à l'installation sont retenues (`install.json` du dossier de configuration) ;
  `--reuse` / `-Reuse` les reprend.

### 10.3 🏷️ Versions et mises à jour

- **Version du logiciel** `MAJEUR.MINEUR.CORRECTIF` (`organizer.__version__`) : `0.<étape>.<correctif>`
  pendant le développement (0.7.0 = étape 7, 0.8.0 = étape 8), **1.0.0** le 9/11/2026 (validé sur le Pi et sous Windows) ; ensuite MINEUR pour une
  nouveauté, CORRECTIF pour une correction, MAJEUR pour un changement qui casse la compatibilité. Une
  étiquette git `v<version>` marque chaque version publiée.
- **Version de l'API** (`organizer.API_VERSION`, entier) : augmentée seulement quand un client plus ancien
  ne peut plus fonctionner avec le serveur.
- Le serveur l'annonce sans connexion : `GET /api/v1/version` → `{"version": "0.7.0", "api": 1}`.
- **Client bureau** : compare sa version à celle du serveur (au plus toutes les 10 min) et affiche un bandeau
  en haut des pages qui dit **qui** doit être mis à jour : 🔁 « mis à jour sur ce poste mais l'ancienne
  version tourne encore » (version sur le disque plus récente que celle en mémoire : quitter et relancer
  le client), 🔄 « ce poste est en retard » (commande de mise à jour du poste), ⚠️ en rouge si l'API n'est
  plus compatible, ℹ️ « c'est le serveur qui est en retard » (`deploy/update.sh` sur le Pi). Les deux versions sont aussi dans Réglages →
  🔌 Connexion.
- **Mettre à jour un poste** : `install/linux/update.sh` ou `install\windows\update.bat` — arrête le
  client, `git pull --ff-only`, relance l'installeur avec les options retenues (dépendances, lanceur,
  icônes, raccourcis), relance le client en arrière-plan s'il tournait. Un simple `git pull` suffit pour du
  code seul, à condition de redémarrer le client (⏻ Quitter puis relancer).
- **Mettre à jour le serveur** (Pi) : `deploy/update.sh` — `git pull` (sous le compte de l'utilisateur),
  puis `deploy/install.sh --reuse` : dépendances, service régénéré et `daemon-reload` s'il a changé,
  redémarrage, vérification de `/api/v1/version`. Les données (`data/`) ne sont pas touchées ; les
  évolutions de la base sont appliquées au démarrage (migrations, §10.6).
- Ordre conseillé : **le serveur d'abord**, puis les postes (le bandeau les y invite).
- **Branche de test** `cloclo` : le développement y est poussé au fil de l'eau ; `main` ne reçoit que ce
  qui a été validé. Sur le Pi, `deploy/install_test.sh` bascule l'installation sur `cloclo` (`--main` :
  retour ; `--branch x` : autre branche) puis relance `deploy/install.sh --reuse`. Mêmes données : copie de
  la base avant de quitter main ; retour sur main refusé si la base a été migrée au-delà de ce que main
  connaît. `deploy/update.sh` suit la branche active.
- Le code reste **compatible Python 3.11** (contrôlé par ruff, `target-version = py311`).
- **HTTPS par le serveur lui-même** (facultatif, réseau local) : `ORGANIZER_SSL_CERT` / `ORGANIZER_SSL_KEY`
  (fichiers PEM). Certificat conseillé : autorité locale **mkcert** (son certificat racine est à installer sur
  les téléphones) ; le client bureau la reconnaît avec `ORGANIZER_CA_FILE=<rootCA.pem>`. Inutile avec la mise
  en ligne par Cloudflare Tunnel (§10.4), qui fournit un certificat reconnu partout.

### 10.4 🌍 Mise en ligne (derrière un proxy)

Choix retenu : **Cloudflare Tunnel**. `cloudflared`, installé **sur le Pi** (paquet, pas Docker), ouvre une
connexion sortante vers Cloudflare : aucun port à ouvrir sur la box, pas de certificat à gérer. Cloudflare
reçoit `https://organizer.blou.top` et transmet en HTTP à `http://localhost:2603`. ⚠️ Cloudflare voit le trafic
en clair (choix assumé). Le serveur continue d'écouter sur `0.0.0.0` (accès local direct conservé) ; passer
à `127.0.0.1` : `deploy/install.sh --reuse --host 127.0.0.1` (variable `ORGANIZER_HOST` du service).

- **Visiteur réel** : uvicorn (`ProxyHeadersMiddleware`, actif par défaut) remplace l'adresse et le protocole
  de la connexion par ceux des en-têtes `X-Forwarded-For` / `X-Forwarded-Proto`, **seulement** si la connexion
  vient de 127.0.0.1 / ::1 (d'où `cloudflared` sur le Pi même ; sinon régler `FORWARDED_ALLOW_IPS`).
  `request.client.host` (anti force brute) et `request.url.scheme` sont donc ceux du visiteur.
- **Cookie `Secure`** dès que le visiteur est en HTTPS (`request.url.scheme`), que le HTTPS soit fait par le
  serveur ou par le proxy ; pas en HTTP local (le navigateur ne renverrait pas un cookie `Secure`).
- **En-têtes de sécurité** sur toutes les réponses (`SecurityHeadersMiddleware`, sans écraser ceux d'une
  réponse, ex. pièces jointes) : `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`,
  `Referrer-Policy: same-origin`, et `Strict-Transport-Security: max-age=31536000` (HSTS, 1 an) pour les
  visiteurs en HTTPS uniquement.
- **Documentation de l'API** (`/docs`, `/redoc`, `/openapi.json`) réservée aux connectés : sinon redirection
  vers `/login?next=/docs` (401 pour le schéma JSON).
- **Anti force brute par identifiant**, **journal des connexions**, **mots de passe de 12 caractères** : voir §3.
- **Sauvegarde et restauration** : voir §10.5.
- **Guide de mise en place** (domaine, `cloudflared` en paquet, tunnel créé dans le tableau de bord, route
  `organizer.blou.top` → `http://127.0.0.1:2603` — pas `localhost`, qui peut désigner `::1` —, Always Use
  HTTPS, WebSockets, Bot fight mode désactivé pour le client bureau, vérifications) : README, section
  « Accès depuis Internet ».

### 10.5 🗄️ Sauvegarde

`GET /api/v1/admin/backup` (`organizer/server/backup.py`, `server/api/admin.py`) renvoie une archive
**`.tar` non compressée**, produite au fil de l'envoi (pas de copie complète sur le disque) :

1. `organizer.db` : image **cohérente** de la base, prise sans arrêter le serveur par l'API de sauvegarde
   de SQLite (une copie du fichier pourrait manquer ce qui est encore dans le journal WAL), en un seul
   fichier (journal `DELETE`), vérifiée (`PRAGMA integrity_check`). L'image passe par un fichier temporaire
   `.backup-*.db` du dossier des données, supprimé à la fin (même si le téléchargement est interrompu) ;
2. `uploads/<id>` : pièces jointes (sauf `?uploads=false`) ; les envois en cours (`.part`) sont ignorés.
   Un fichier envoyé n'est jamais modifié ni supprimé : toutes celles que l'image référence sont présentes ;
3. `manifest.json`, **en dernier** (une archive tronquée n'en a pas) : `format` (`organizer-backup`),
   `format_version` (1), `created_at`, `version`, `api_version`, `includes_uploads`, `counts` (nombre
   d'utilisateurs, tâches, projets, tags, boards, pièces jointes) et `files` (nom, taille, SHA-256).

Non compressée pour un outil qui **dédoublonne** (borg…) : d'un jour à l'autre, il retrouve les mêmes blocs
et ne stocke que ce qui a changé, puis compresse lui-même. Nom proposé : `organizer-AAAAMMJJ-HHMMSS.tar`.

**Accès** : une session d'administrateur (cookie ou jeton du client bureau), ou un **jeton de sauvegarde**
(`Authorization: Bearer orgbk_…`, table `api_key`) :

- créé par un administrateur (Réglages → 🗄️ Données, ou `POST /api/v1/admin/backup-keys`), secret affiché
  **une seule fois** (seule son empreinte SHA-256 est stockée) ; sans expiration ; révocable
  (`DELETE /api/v1/admin/backup-keys/{id}`) ; date et adresse de la dernière utilisation conservées ;
- n'ouvre **que** cette route (jamais accepté comme session) ;
- **réseau local seulement** (adresse de bouclage ou privée) : derrière Cloudflare Tunnel, un visiteur venu
  d'Internet garde son adresse publique (même s'il prétend le contraire dans `X-Forwarded-For`), donc un
  jeton qui aurait fuité y est refusé (403) ;
- cesse de fonctionner si son créateur perd les droits admin ou est désactivé (et refonctionne s'il les
  retrouve).

Chaque sauvegarde et chaque jeton refusé sont écrits dans le journal (`organizer.backup`).

**Restauration** : `deploy/restore.sh <archive.tar | ->` (`organizer/server/restore.py`), en deux temps
pour n'arrêter le serveur que quelques secondes :

1. `prepare` (serveur en marche) : lecture de l'archive **en un seul passage** (fichier ou entrée standard,
   ex. `borg export-tar … -`), extraction dans `<données>/.restauration-<date>/` et vérification : seuls
   `organizer.db`, `uploads/<id>` et `manifest.json` sont admis (fichiers ordinaires ; tout autre élément,
   lien ou chemin → refus), manifeste présent et dernier, liste, tailles et SHA-256 conformes, base intègre
   et contenant les tables d'Organizer, `format_version` connue. Archive d'une version plus récente
   d'Organizer : refusée sauf `--force` (code de sortie 3). Résumé affiché (date, version, utilisateurs,
   tâches, projets, tags, pièces jointes), puis confirmation (`--yes` pour s'en passer ; obligatoire sans
   terminal) ;
2. arrêt du service, `swap` : base (et `-wal` / `-shm`) et `uploads/` actuels déplacés dans
   `<données>/avant-restauration-<date>/` (+ `LISEZMOI.txt` : comment revenir en arrière), installation de
   la sauvegarde (simples renommages) ; redémarrage, vérification de `/api/v1/version`.

`--db-only` : la base seule (les pièces jointes de l'archive sont vérifiées mais pas extraites) ; une archive
sans pièces jointes garde aussi celles du serveur. `--data-dir`, `--no-service` (serveur hors systemd,
arrêté à la main). Dossier des données, port, adresse et HTTPS lus dans `deploy/server.conf`.
Exemple de script borg quotidien (`curl … | borg import-tar … -`, `prune`, `compact`) : README.

---

### 10.6 🧬 Évolutions de la base (migrations)

`organizer/core/migrations.py`, appelé au démarrage du serveur (`init_db` → `migrate`) :

- **Numéro de schéma** dans l'en-tête de la base SQLite (`PRAGMA user_version`) : il voyage avec la base
  (sauvegardes, restaurations) et figure dans le `manifest.json` des sauvegardes (`schema_version`).
  0 = base antérieure à la 1.0.0 ; **1 = schéma de la 1.0.0** (point de départ, aucune modification).
- **Base neuve** : créée directement au dernier schéma. **Base existante** : tables nouvelles créées, puis
  chaque étape manquante, dans l'ordre, **chacune dans sa transaction avec la mise à jour du numéro**
  (changements de structure compris : connexion dédiée qui émet `BEGIN` elle-même, le pilote `sqlite3` ne
  le faisant pas avant un `ALTER TABLE`) ; une étape qui échoue est annulée entièrement et le serveur ne
  démarre pas. **Copie de sécurité** de la base (`organizer.db.avant-migration-v<n>-<date>`, à côté d'elle)
  avant toute étape qui touche aux données.
- **Base plus récente** que le code (retour à une ancienne version d'Organizer) : refusée au démarrage
  (« mettez Organizer à jour »), rien n'est modifié.
- Ajouter une étape : modifier le modèle, puis ajouter à la fin de `MIGRATIONS` une étape de numéro suivant
  faisant le même changement sur une base existante (`add_column(conn, table, colonne, "TYPE DEFAULT …")`,
  sans effet si la colonne existe). Ne jamais modifier une étape publiée. Garde-fou : une base créée par
  la version 0.9.0 (`tests/fixtures/organizer-0.9.0.db`) doit arriver exactement au schéma d'une base neuve,
  données intactes.

## 11. Feuille de route

| Étape | Contenu |
|---|---|
| 1 | ✅ Socle : config, modèles, base SQLite, services tâches / projets / tags / sous-tâches, historique annuler/rétablir + tests |
| 2 | ✅ Serveur : authentification (cookies, jetons), API REST, premier compte admin, pièces jointes, service systemd |
| 3 | ✅ Interface : thème clair/sombre, layout responsive, cartes, éditeur avec curseurs, ajout rapide, accueil, liste simple |
| 4 | ✅ Éditeur markdown CodeMirror (live preview, listes, cases, liens cliquables) |
| 5 | ✅ Modules : liste (filtres, tri, regroupement mémorisés), recherche Ctrl+K, réglages, dupliquer, heure d'échéance |
| 6 | ✅ Kanbans (prédéfinis + personnalisés, partage), matrice 2×2 / 4×4, glisser-déposer souris et tactile, Ctrl+drop |
| 7 | ✅ Client bureau : fenêtre native, RemoteDataSource, ouverture de liens, notifications |
| 8 | ✅ Temps réel (SSE), PWA, HTTPS facultatif, finitions (Rattacher à…, flèches dans Ctrl+K, défilement automatique, rappel par défaut à jour, compteur de filtres) |
| 1.0.0 | ✅ Mise en ligne (Cloudflare Tunnel, durcissement), sauvegarde / restauration, pièces jointes par glisser-déposer, client bureau plus rapide et réseau local automatique, Windows, migrations de la base |

---

## 12. Historique des changements

| Date | Version | Changement |
|---|---|---|
| 2026-11-07 | 0.1 | Spécification initiale |
| 2026-11-07 | 0.2 | Ctrl+drop sans confirmation ; annuler / rétablir général (Ctrl+Z) ; projets et tags publics ou privés ; rattachement sur téléphone par maintien |
| 2026-11-07 | 0.3 | **Étape 1 livrée** : modèles, base SQLite, services (utilisateurs, projets, tags, tâches, sous-tâches, liens, partage, filtres, tri, rappels), historique annuler / rétablir, règles pures ; 83 tests ; script de démo terminal |
| 2026-11-07 | 0.4 | **Étape 2 livrée** : sessions (cookie / jeton, glissantes, empreinte SHA-256), anti force brute, API REST `/api/v1` (34 routes, doc `/docs`), pièces jointes, pages /login, /setup et accueil provisoire, service systemd ; 118 tests |
| 2026-11-07 | 0.5 | **Étape 3 livrée** : interface NiceGUI (`organizer/ui`) — thème clair/sombre, colonne de gauche / tiroir mobile, cartes, éditeur latéral (curseurs, échéance, rappel, projet, tags créés à la volée, partage, sous-tâches, liens, pièces jointes, notes texte), ajout rapide, accueil « points chauds », liste, Ctrl+Z / N, lien `?task=` ; `DataSource` ; 126 tests |
| 2026-11-07 | 0.6 | Retours sur l'étape 3 : création dans l'éditeur complet (brouillon), compteurs de l'accueil cliquables (liste des tâches), `?task=new` ; sujet des liens de fichiers consigné dans `TODO.md` ; 128 tests |
| 2026-11-07 | 0.7 | **Étape 4 livrée** : éditeur de notes markdown façon Obsidian (CodeMirror 6 de NiceGUI) — rendu en direct, syntaxe masquée, puces, cases à cocher cliquables, continuation et renumérotation des listes, double-clic sur liens / adresses / chemins, Ctrl+Z local ; 130 tests + test interactif dans Firefox |
| 2026-11-07 | 0.8 | Notes : liens ouverts d'un **simple clic** (Ctrl+clic pendant l'édition du lien), double-clic dédoublonné ; infobulle avec la cible |
| 2026-11-08 | 0.9 | Liens web sans protocole (`google.fr`, `localhost:2603`…) ouverts au lieu d'être copiés ; règles de reconnaissance web / fichier précisées (§4.4) |
| 2026-11-08 | 1.0 | **Étape 5 livrée** : liste filtrable / triable / regroupable (préférences en base `user_pref`), barre de filtres réutilisable, recherche Ctrl+K + page `/search`, réglages complets (profil, mot de passe, thème, rappels, projets, tags, appareils, utilisateurs), dupliquer une tâche, heure d'échéance ; `AccountService` commun API / interface ; API : préférences et duplication (36 chemins, 49 opérations) ; 163 tests |
| 2026-11-08 | 1.1 | Couleur des nouveaux tags choisie automatiquement, distincte des autres tags (et surtout de ceux de la tâche éditée) ; API `GET /tags/suggest-color` ; 168 tests |
| 2026-11-08 | 1.2 | Tags affichés dans leur couleur partout (pastille + fond teinté) : cartes, sélecteur de l'éditeur et filtre « Tags » (puces et liste déroulante), puces légèrement espacées du libellé du champ |
| 2026-11-08 | 1.3 | **Étape 6 livrée** : boards personnalisés (tables `board`, `board_column`, `board_card`, `board_share` ; `BoardService` ; partage = accès aux tâches posées), pages Kanbans (4 boards prédéfinis + personnalisés, filtres et masquage des terminées par board) et Matrice (2×2, 4×4), glisser-déposer maison souris / tactile avec Ctrl+drop et maintien au doigt pour rattacher ; API : routes `/boards` (45 chemins, 63 opérations) ; 182 tests + tests interactifs dans Firefox |
| 2026-11-08 | 1.4 | Kanbans : pleine largeur et pleine hauteur, colonnes plus étroites, repliables et redimensionnables (mémorisé par board) ; reclassement dans une colonne avec repère d'insertion, qui ajuste l'urgence et un rang manuel (table `task_rank`, `TaskService.move`, API `POST /tasks/{id}/move` : 46 chemins, 64 opérations) ; tri « Urgence » départagé par ce rang ; 190 tests + vérification dans Firefox |
| 2026-11-08 | 1.5 | **Étape 7 livrée** : client bureau (`organizer/client`, `run_client.py`) — fenêtre native pywebview, connexion par jeton (`/connect`), `RemoteDataSource` (contrat identique aux services, vérifié par les tests), verrou de la fenêtre, ouverture des liens / fichiers locaux / pièces jointes, notifications des rappels (desktop-notifier 6.2.0), onglet de réglages 🔌 Connexion ; 206 tests + parcours vérifié dans Firefox et dans la fenêtre native |
| 2026-11-08 | 1.6 | Client bureau : fonctionne en **arrière-plan** (fermer = cacher ; ⏻ Quitter dans le menu du compte), **instance unique** pilotée par la ligne de commande (`--new-task`, `--quit`, `--hidden`), **raccourcis clavier globaux** (KDE / GNOME / Windows), **installeurs** Linux (`install/linux/install.sh`) et Windows (`install/windows/install.bat`), icône de l'application « Post-it en vrac » (choisie parmi 5 propositions), journal `client.log` ; 221 tests + essais réels (fenêtre native, KDE) |
| 2026-11-08 | 1.7 | **Versions** : `organizer.__version__` = 0.7.0 et `API_VERSION` = 1, route publique `GET /api/v1/version`, bandeau « mise à jour disponible » sur le client bureau ; scripts de mise à jour `install/linux/update.sh`, `install/windows/update.bat`, `deploy/update.sh` (Pi) ; options d'installation retenues (`--reuse`) ; 233 tests + mise à jour complète simulée |
| 2026-11-08 | 1.8 | **Étape 8** : temps réel (bus `core/events.py`, pages web abonnées, flux SSE `/api/v1/events` pour le client bureau, origine des modifications, attente pendant un glisser), PWA (manifeste, icônes maskable / apple-touch, service worker, raccourcis), HTTPS facultatif (`ORGANIZER_SSL_*`, `ORGANIZER_CA_FILE`), favicon = icône Post-it ; finitions : « 🌳 Rattacher à… » dans le menu des cartes, ↑ ↓ dans Ctrl+K, défilement automatique pendant un glisser, décalage de rappel par défaut lu au moment de créer, compteur « Filtres (n) » relatif aux filtres par défaut de la vue ; 246 tests + vérifications dans Firefox (temps réel entre onglets et client bureau, défilement) |
| 2026-11-08 | 1.8.1 | **Version 0.8.0** du logiciel. Correction : **Ctrl+Alt+O** n'ouvrait pas Organizer sous KDE (raccourci posé sans le drapeau « présent », ignoré au clavier) ; l'installeur utilise `setShortcutKeys` et vérifie que la touche est bien attribuée. Relancer `install/linux/install.sh` (ou `--reuse`) sur les postes déjà installés |
| 2026-11-08 | 1.9 | **Installation du serveur** : `deploy/install.sh` (venv, dépendances, service systemd généré pour l'utilisateur qui lance la commande — même sous sudo, jamais root —, `Restart=always`, démarrage au boot, vérification de la réponse, options retenues, `--print-service`, `--uninstall`) ; `deploy/update.sh` s'appuie dessus (`--reuse`) ; `deploy/organizer.service` (fixé sur l'utilisateur `pi`) supprimé ; 251 tests + installation, mise à jour et désinstallation déroulées dans un bac à sable |
| 2026-11-08 | 1.9.1 | Bandeau de version du client bureau : détecte un client mis à jour sur le disque mais pas redémarré (« quittez puis relancez Organizer »), messages qui nomment qui doit être mis à jour (ce poste / le serveur), vérification toutes les 10 min ; version installée affichée dans 🔌 Connexion ; 254 tests |
| 2026-11-08 | 1.10 | **Mise en ligne, étape 1** (Cloudflare Tunnel retenu, §10.4) : cookie `Secure` selon le protocole du visiteur (et non plus selon le certificat du serveur), en-têtes de sécurité sur toutes les réponses (HSTS en HTTPS seulement), vraie IP du visiteur derrière un proxy local vérifiée par des tests (`tests/test_proxy.py`), page « Serveur injoignable » de la PWA reformulée ; 264 tests |
| 2026-11-08 | 1.11 | Mise en ligne, étape 2a : documentation de l'API (`/docs`, `/redoc`, `/openapi.json`) réservée aux utilisateurs connectés ; 270 tests |
| 2026-11-08 | 1.12 | Mise en ligne, étapes 2b-2c : anti force brute par identifiant toutes adresses confondues (20 échecs / h, `LoginBlock`), journal des connexions (échecs, blocages, refus, réussites) ; journal du serveur enfin configuré (`configure_logging` : messages INFO d'Organizer dans `journalctl -u organizer`) ; 277 tests |
| 2026-11-08 | 1.13 | Mise en ligne, étape 2d : option `--host` de `deploy/install.sh` (`ORGANIZER_HOST` écrit dans le service, retenue par `--reuse`, vérification finale sur la bonne adresse) ; 277 tests + installation en bac à sable avec `--host 127.0.0.1` |
| 2026-11-08 | 1.14 | Mise en ligne, étape 2e : mots de passe de **12 caractères minimum** ; un ancien mot de passe plus court fonctionne toujours mais est repéré à la connexion (`security:weak_password`) → bandeau orange jusqu'au changement ; bandeaux généralisés (`UiContext.banners`, `Banner` : ton, action, cible) ; 282 tests + bandeau vérifié dans Firefox |
| 2026-11-08 | 1.15 | Mise en ligne, étape 3 : **sauvegarde** (§10.5) — archive `.tar` non compressée produite au fil de l'envoi (image cohérente de la base par l'API de sauvegarde SQLite, pièces jointes, `manifest.json` avec empreintes), `GET /api/v1/admin/backup` (admin ou jeton), **jetons de sauvegarde** (table `api_key` : sans expiration, révocables, export seul, réseau local seulement, routes `/admin/backup-keys`), onglet ⚙️ Réglages → 🗄️ Données (web : téléchargement ; client bureau : dossier Téléchargements) ; 299 tests + téléchargement par `curl` vérifié sur un vrai serveur (30 Mo, réseau local, proxy) |
| 2026-11-08 | 1.16 | Mise en ligne, étape 4 : **restauration** — `deploy/restore.sh` (vérification complète sans arrêter le serveur, lecture en flux depuis `borg export-tar … -`, confirmation, données actuelles mises de côté, redémarrage vérifié ; `--db-only`, `--force`, `--yes`, `--no-service`), `organizer/server/restore.py` (`prepare` / `swap`) ; `deploy/common.sh` : `org_probe_address`, `org_load_conf`, `ORG_WAIT_TRIES` ; script borg quotidien dans le README ; 318 tests + circuit complet essayé avec borg 1.4 et un vrai serveur (sauvegarde, dédoublonnage, restauration, cas d'échec) |
| 2026-11-08 | 1.16.1 | Correction : « 📎 Joindre un fichier » n'ouvrait pas le sélecteur dans la fenêtre du client bureau (WebKitGTK ; probablement aussi Safari et Chrome) — l'ordre faisait un aller-retour par le serveur et perdait le geste de l'utilisateur ; ouvert désormais directement dans le navigateur. Ajouts : plusieurs fichiers à la fois, **dépôt de fichiers** sur l'éditeur ou sur la carte d'une tâche (`components/file_drop.*`), repli par adresses `file://` lues par le client bureau, même fichier joignable deux fois ; 324 tests + vérifié dans WebKitGTK (sélecteur, dépôt, repli), Vivaldi (vrai glisser de fichier par CDP) et Firefox |
| 2026-11-08 | 1.16.2 | Dépôt de fichiers depuis Dolphin dans la fenêtre du client bureau : WebKitGTK masque fichiers et adresses à la page (constaté dans le journal de diagnostic) → adresses captées côté GTK et relayées à la page, fichiers lus sur le poste. **Redémarrage du serveur** : il attendait la fin du flux temps réel des clients bureau (jamais) jusqu'à l'arrêt forcé par systemd après 90 s → attente limitée à 3 s (`timeout_graceful_shutdown`) ; 326 tests |
| 2026-11-08 | 1.17 | **Version 0.9.0** du logiciel. Mise en ligne, étape 5 : guide **Cloudflare Tunnel** pas à pas dans le README (intitulés du tableau de bord vérifiés en novembre 2026 : Networking → Tunnels, Routes → Published application), réglages du domaine, vérifications, téléphones et client bureau par l'adresse publique. Chantier « mise en ligne » terminé |
| 2026-11-08 | 1.17.1 | **Client bureau plus réactif** à travers Internet (≈ 300 ms par requête par Cloudflare, contre ≈ 20 ms sur le réseau local ; diagnostic : 3 requêtes successives par clic) : mémoire des données qui changent rarement (`client/cache.py` : projets, tags, boards, utilisateurs, préférences ; oubliées sur événement temps réel, écriture du poste ou délai), état « annuler / rétablir » joint à la réponse de chaque écriture (en-tête `X-Organizer-Undo`), page derrière l'éditeur relue seulement à sa fermeture, dernier kanban enregistré seulement s'il change. Un clic dans l'éditeur : 3 requêtes → 1 ; 333 tests |
| 2026-11-08 | 1.18 | **Version 0.9.1** du logiciel. **Réseau local automatique** pour le client bureau (§10.1) : adresses locales et clé du compte données par le serveur, preuve d'identité réservée au réseau local avant tout envoi du jeton, bascule de toutes les pages, retour à l'adresse publique hors de la maison ; routes `/api/v1/local-access` et `/local-access/proof` ; état et réglage dans Réglages → 🔌 Connexion ; 345 tests + essai réel (découverte de l'adresse du poste, bascule) |
| 2026-11-08 | 1.18.1 | **Version 0.9.2**. Indicateur 🏠 réseau local / 🌍 Internet en bas à gauche de chaque page, avec infobulle explicative (client bureau : suit les bascules, clic → réglages de connexion ; web : selon l'adresse du visiteur) ; 350 tests + rendu vérifié dans Firefox |
| 2026-11-08 | 1.18.2 | **Tests lancés sur le Pi** (Python 3.11.2) : 345 / 350 ; corrections : `deploy/restore.sh` plantait à l'affichage du résumé sur un système réglé en Latin-1 (sortie de Python forcée en UTF-8 : `PYTHONUTF8=1` dans le script et dans le service systemd généré), test qui utilisait une option de `tarfile` absente de Python 3.11.2 ; tests du script lancés avec une sortie Latin-1 ; 351 tests |
| 2026-11-09 | 1.18.3 | **Premier essai sous Windows** : l'installeur prenait Python 3.15 (`py -3`), pour lequel pythonnet (requis par pywebview) n'existe pas et PyYAML n'a pas de wheel (compilation bloquée par le Contrôle intelligent des applications). `install.ps1` exige désormais Python 3.11 à 3.13 (`py -3.13`, `-3.12`, `-3.11`) et refait un venv d'une autre version |
| 2026-11-09 | 1.18.4 | **Version 0.9.3**. Client bureau : une adresse saisie sans protocole qui est un nom de domaine public (`organizer.blou.top`) devient `https://…` au lieu de `http://…:2603` (que Cloudflare ne sert pas : « ne répond pas » au premier essai sous Windows) ; adresses locales inchangées ; message « ne répond pas » adapté (réseau local / Internet). `is_local_host` partagé par `config.py` et `lan.py` |
| 2026-11-09 | 1.18.5 | **Version 0.9.4**. Suite de tests lancée sous **Windows** (Python 3.13) : 341 réussis, 10 sautés. Liens `file://` vers un disque Windows acceptés sous toutes leurs formes (`file:///C:/…`, mais aussi `file://C:/…` ou `file://C:\…`) ; tests rendus portables (`Path.as_uri()`, `USERPROFILE`), test des fichiers `.desktop` réservé à Linux |
| 2026-11-09 | 1.18.6 | **Version 0.9.5**. Client bureau sous **Windows** : raccourcis globaux captés par Organizer (`RegisterHotKey`, `winshell.py`) au lieu des `.lnk` du menu Démarrer (appuis perdus une fois sur deux : premier plan refusé par Windows) ; **icône dans la zone de notification** (clic : ouvrir ; clic droit : nouvelle tâche, quitter) ; mise au premier plan par `SetForegroundWindow` ; icône d'Organizer (et non de Python) dans les notifications ; 343 tests |
| 2026-11-09 | 1.19 | **🎉 Version 1.0.0**. Migrations de la base (§10.6) : numéro de schéma dans l'en-tête SQLite, étapes transactionnelles (structure comprise), copie de sécurité avant migration, base trop récente refusée, schéma 1 = point de départ ; numéro de schéma dans le manifeste des sauvegardes ; base créée par la 0.9.0 gardée comme référence de test (`tests/fixtures/organizer-0.9.0.db`) ; essai sur des copies des bases existantes du poste de développement ; 361 tests (+1 réservé à Windows) |
| 2026-11-09 | 1.20 | **📅 Calendrier** (§8.4 bis), première étape du chantier « événements » : module dans la colonne de gauche, page `/calendar` = grille du mois du lundi au dimanche, ‹ › et « Aujourd'hui », `?month=AAAA-MM` ; règles pures `rules.month_grid` / `rules.shift_month` ; noms complets des jours et des mois regroupés dans `ui/format.py` ; 369 tests + rendu vérifié dans Firefox (clair, sombre, téléphone) |
| 2026-11-09 | 1.21 | **Branche de test `cloclo`** (§10.3) : `deploy/install_test.sh` bascule le serveur sur `cloclo` (ou `--branch`), `--main` y revient ; copie de la base en quittant main, retour refusé si la base est plus récente que main ; 372 tests |
| 2026-11-10 | 1.22 | Calendrier : échéances des tâches en pastilles de la couleur de l'urgence, tâches en retard ramenées à aujourd'hui (pastille d'alerte), filtres « 📋 Tâches » et « Tâches de qui ? » mémorisés, sélection d'une case, double-clic = éditeur (pastille) ou case agrandie avec les cartes complètes ; `rules.calendar_days` / `rules.is_overdue`, `theme.readable_text`, `format.distance` ; 375 tests + parcours vérifié dans Firefox |
| 2026-11-10 | 1.23 | Calendrier : pourtour des pastilles = importance ; colonne « 📥 Sans échéance » (à droite, sous la grille sur petit écran) ; glisser-déposer des pastilles entre les jours et vers / depuis « Sans échéance » pour changer ou retirer l'échéance (zones `day:<date>` et `undated`) ; 376 tests + glisser réel vérifié dans Firefox |
| 2026-11-10 | 1.24 | Calendrier : colonne « 📥 Sans échéance » de largeur réglable (poignée à gauche ; `resize.js` : `data-resize-side="left"`) et repliable en bande étroite qui reste une zone de dépôt, mémorisé ; correction : deux dépôts rapides de suite sur la même tâche (le second était ignoré) ; 377 tests + vérifié à la souris dans Firefox |
| 2026-11-10 | 1.25 | **Événements, étape 1** (§4.7) : tables `event`, `event_tag`, `event_share` (modifiable ou lecture seule), `event_link` ; base commune tâches / événements (`ItemBase`, `LinkBase`, `ItemOut`, `ItemService`) ; `AgendaService` (période, portée, texte, projets, tags ; droits ; liens et pièces jointes ; conversion tâche ↔ événement) ; règles `event_span`, `event_days`, `event_times_from_due`, `maps_url`, `waze_url` ; API `/agenda` et `RemoteAgenda` ; correction : enregistrement de `client.json` par deux fils à la fois (le client pouvait perdre sa configuration) ; 392 tests |
| 2026-11-10 | 1.26 | **Événements, étape 2** (§6.0) : éditeur commun tâche / événement (`Editor` = panneau et aiguillage, `ItemEditor` = base, `TaskEditor`, `EventEditor`), bascule 📋 / 📅 (brouillon : champs communs gardés ; existant : conversion en une action, `extra` appliqué dans la même transaction), éditeur d'événement (journée entière, durée gardée, lieu + Maps / Waze, couleur, public, partage modifiable ou lecture seule, vue en lecture seule), `?event=` ; calendrier : sélection de plusieurs jours au clic-glisser (`day_select.js`), clic droit → nouvel événement / nouvelle tâche ; 397 tests + vérifié dans Firefox |
