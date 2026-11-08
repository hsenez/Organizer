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
    rules.py             # règles pures : échéances, rappels, matrice, Ctrl+drop, recherche
    unit_of_work.py      # transactions + capture automatique de l'historique annuler / rétablir
    services/            # users, auth, account, labels (projets + tags), tasks, boards, attachments, undo ;
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
    pages/               # home, tasks (+ recherche), kanban, matrix, settings
  assets/                # icônes (SVG source, PNG, ICO, maskable, apple-touch) — scripts/make_icons.sh
tests/
scripts/demo.py          # démo terminal + données d'exemple (base data/demo.db)
deploy/                 # install.sh (serveur : venv + service systemd généré), update.sh, common.sh
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

## 6. Éditeur de tâche

S'ouvre en panneau latéral (bureau) ou en plein écran (téléphone).

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
- **Liens** : saisie libre (hyperlien ou chemin détecté automatiquement), bouton « 📎 Joindre un fichier ».

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
5. 🔍 **Recherche** (aussi accessible partout par `Ctrl+K`)
6. ⚙️ **Réglages**

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
  et le port 2603 sont ajoutés), identifiant, mot de passe → **jeton API** (90 jours glissants) enregistré
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
  pendant le développement (0.7.0 = étape 7, 0.8.0 = étape 8), **1.0.0** une fois validé sur le Pi et les téléphones ; ensuite MINEUR pour une
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
  nouvelles tables sont créées au démarrage (une nouvelle colonne demanderait une migration).
- Ordre conseillé : **le serveur d'abord**, puis les postes (le bandeau les y invite).
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
- **Sauvegarde** : voir §10.5.
- À venir (`TODO.md`) : restauration (`deploy/restore.sh`), guide Cloudflare (README).

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

---

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
