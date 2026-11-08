# 📋 Organizer — Spécifications

> Document de référence fonctionnel et technique. **Mis à jour à chaque changement.**
> Version : 1.4 — 2026-11-08

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
   bureau       │  │   WebSocket /api/v1/events ◀──────┘ (diffusion des changements)         │
                │  │   Pièces jointes : data/uploads/                                        │
                │  └─────────────────────────────────────────────────────────────────────────┘
```

- **Une seule interface**, écrite une fois avec NiceGUI (pages, composants, cartes, éditeur).
  - Côté **serveur**, elle accède aux données via les services métier directement (`LocalDataSource`).
  - Côté **client bureau**, la même interface tourne localement dans une fenêtre native (pywebview) et accède
    aux données via l'API REST du serveur (`RemoteDataSource`, httpx).
  - Les deux implémentent la même interface `DataSource` : le code UI ne sait pas où sont les données.
- **Temps réel** : toute modification est diffusée (bus d'événements interne + WebSocket pour les clients bureau)
  pour que les autres écrans se rafraîchissent.
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
| Notifications système (client bureau) | desktop-notifier *(à installer à l'étape concernée)* | — |
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
    datasource.py        # interface DataSource + LocalDataSource (serveur) ; RemoteDataSource à l'étape 7
  server/                # ✅ étape 2
    app.py               # point d'entrée serveur : build() + ui.run()
    state.py             # état global : base, services, anti force brute, tickets de connexion
    security.py          # middleware d'authentification (cookie / Bearer), cookies
    wiring.py            # assemblage : middleware, erreurs, routes (partagé avec les tests)
    web_auth.py          # /auth/complete (ticket → cookie), /auth/logout
    pages.py             # /login, /setup + branchement des pages de l'UI sur LocalDataSource
    api/                 # routes REST /api/v1 (auth, users, labels, tasks, undo) ; WebSocket à venir
  client/
    main.py              # point d'entrée client bureau (fenêtre native)
    remote.py            # RemoteDataSource (httpx)
    system.py            # ouverture de fichiers/liens, notifications
  ui/                    # ✅ étape 3
    theme.py             # couleurs Quasar dérivées des enums (imp0…, urg0…, st0…), CSS des cartes, sombre
    context.py           # UiContext : source de données, rafraîchissement, Ctrl+Z, erreurs → toasts
    format.py            # dates en français (« Aujourd'hui », « lun. 9 nov. », « dans 3 j »)
    layout.py            # en-tête (☰, ↩️ ↪️, compte), colonne de gauche, raccourcis clavier, bouton ➕
    components/          # task_card, level_slider, task_editor, markdown_editor, filter_bar, task_list,
                         # search_dialog, tag_chips, dnd (.py + .js : glisser-déposer),
                         # resizer (.py + resize.js : largeur des colonnes)
    pages/               # home, tasks (+ recherche), kanban, matrix, settings
  static/                # icônes, manifeste PWA (à venir)
tests/
scripts/demo.py          # démo terminal + données d'exemple (base data/demo.db)
deploy/organizer.service # service systemd pour le Raspberry Pi
run_server.py
run_client.py
```

---

## 3. Utilisateurs, authentification, partage

- **Comptes** : le **premier compte créé est admin** (écran d'initialisation au premier lancement). L'admin crée
  les autres comptes ; pas d'inscription libre.
- **Connexion web** : identifiant + mot de passe, case « 🍪 Se souvenir de moi » → cookie de session
  (HttpOnly, SameSite=Lax) valable **30 jours** ; sinon cookie de session de navigateur.
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
  - **anti force brute** : 5 échecs en 10 min pour un couple (adresse IP, identifiant) → blocage temporaire ;
  - changer son mot de passe déconnecte les autres appareils ; désactiver un compte ou réinitialiser son
    mot de passe (admin) le déconnecte partout ;
  - les redirections après connexion n'acceptent que des chemins internes (pas de redirection ouverte).
- **API REST** `/api/v1`, documentée sur **`/docs`** : authentification par `Authorization: Bearer <jeton>`
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
- Réseau local uniquement, **HTTP simple** en v1 (pas de HTTPS).

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
  code couleur), et le relâchement rattache. *À venir : menu de la carte → « 🌳 Rattacher à… » (sélecteur
  de tâche avec recherche).*
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

Page `/settings` à onglets (onglet initial : `?tab=profile|appearance|reminders|projects|tags|devices|users`) :

- 👤 **Profil** : nom affiché ; changement de mot de passe (déconnecte les autres appareils).
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
- *À venir* : 📊 **Boards** (étape 6), 🔌 **Connexion** du client bureau (étape 7).

Toutes les modifications de projets et de tags sont annulables (Ctrl+Z).

---

## 9. Responsive / téléphone

- La colonne de gauche devient un tiroir (☰).
- Kanbans : colonnes en défilement horizontal au doigt (repliables, redimensionnables) ; matrice 2×2 empilée.
- Éditeur en plein écran ; curseurs utilisables au doigt.
- Glisser-déposer tactile (appui long pour saisir une carte).
- Manifeste **PWA** : ajout à l'écran d'accueil, icône, plein écran.

---

## 10. Déploiement

- **Serveur** : Raspberry Pi 5, Python 3.11, écoute sur `0.0.0.0:2603`. Données dans `data/`
  (`organizer.db`, `uploads/`), chemin configurable par variable d'environnement.
- **Service systemd** fourni (`deploy/organizer.service`) : démarrage automatique, redémarrage en cas d'erreur.
- **Client bureau** : Linux (GTK/WebKit) et Windows (Edge WebView2), lancé par `run_client.py`.
- Le code reste **compatible Python 3.11** (contrôlé par ruff, `target-version = py311`).

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
| 7 | Client bureau : fenêtre native, RemoteDataSource, ouverture de liens, notifications |
| 8 | Temps réel, PWA, finitions |

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
