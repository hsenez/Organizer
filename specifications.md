# 📋 Organizer — Spécifications

> Document de référence fonctionnel et technique. **Mis à jour à chaque changement.**
> Version : 0.6 — 2026-11-07

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
| Éditeur markdown (JS embarqué) | CodeMirror 6 (fichiers vendorisés dans `static/vendor/`) | 6.x |
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
    services/            # users, auth, labels (projets + tags), tasks, attachments, undo ; façade `Services`
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
    components/          # task_card, level_slider, task_editor, quick_add (filter_bar, markdown à venir)
    pages/               # accueil, toutes les tâches ; kanban / matrice / recherche / réglages à venir
  static/                # css, js, icônes, manifeste PWA, vendor/codemirror
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
  - **partager un board** donne accès aux tâches posées dessus ;
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

Pièces jointes : stockées dans `data/uploads/` (50 Mo max par fichier), accessibles au déposant et à quiconque
voit une tâche qui les référence. Seuls les types sûrs (PDF, images, texte brut, mp3/mp4) s'affichent dans le
navigateur ; tout le reste (HTML, SVG…) est forcé en téléchargement, avec `Content-Security-Policy: sandbox`.
Retirer le lien (annulable) conserve le fichier.

### 4.5 Projets et tags

- **Projet / sujet** : nom, emoji, couleur, description, archivé oui/non. Une tâche → zéro ou un projet.
- **Tag** : nom, couleur. Une tâche → plusieurs tags. Autocomplétion dans l'éditeur ; création à la volée
  possible depuis l'éditeur (ajoute le tag à la liste, privé par défaut).
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

### 5.1 Rattacher par glisser-déposer (Ctrl + drop)

Partout où des tâches apparaissent en cartes (liste, kanbans, matrice, accueil) :

- **Glisser-déposer** normal : déplace la carte (change colonne / quadrant / ordre).
- **Glisser avec Ctrl enfoncé au-dessus d'une autre carte** : la carte cible se met en **surbrillance** ;
  au relâchement, la tâche déposée **devient une sous-tâche de la cible**.
  - 🟢 Surbrillance verte : rattachement possible.
  - 🔴 Surbrillance rouge + infobulle : impossible, et rien ne se passe. Cas :
    la cible est elle-même une sous-tâche · la tâche déposée a déjà des sous-tâches · cible = elle-même.
  - Si la tâche déposée était déjà sous-tâche d'un autre parent, elle change de parent.
  - **Pas de confirmation** : l'action est immédiate et s'annule avec **Ctrl+Z** (voir §6.1).
- **Détacher** : bouton « Détacher du parent » dans l'éditeur et dans le menu de la carte.
- **Sur téléphone** (pas de touche Ctrl) : on glisse la carte (appui long) et on la **maintient ~1 s au-dessus
  d'une autre carte** : la cible se met en surbrillance (même code couleur), et le relâchement rattache.
  Alternative toujours disponible : menu de la carte → « 🌳 Rattacher à… » (sélecteur de tâche avec recherche).

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
- **Notes markdown façon Obsidian** (CodeMirror 6, *live preview*) :
  - la mise en forme s'applique pendant la frappe (titres, gras, italique, code, citations, liens) ; les
    symboles markdown s'estompent hors de la ligne en cours d'édition ;
  - **continuation automatique des listes** : Entrée sur `1. …` crée `2. `, sur `- …` crée `- `, sur
    `- [ ] …` crée `- [ ] ` ; Entrée sur un élément vide termine la liste ; Tab / Maj+Tab indente / désindente ;
    renumérotation automatique des listes numérotées ;
  - **cases à cocher cliquables** ;
  - **liens double-cliquables** : URL, chemin local, `[texte](url)` — comportement selon le §4.4.
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
- **Échéance** : champ date + raccourcis Aujourd'hui / Demain / +1 semaine / Aucune ; rappel de suivi :
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
| Pastilles colorées | tags |
| `▰▰▱ 2/3` | progression des sous-tâches |
| `↳ Parent` | c'est une sous-tâche |
| 📝 / 🔗 n / 👥 | a des notes / des liens / est partagée |

Chaque élément a une **infobulle**. Clic → éditeur ; menu ⋯ → actions rapides (changer statut, détacher,
supprimer ; dupliquer et rattacher à venir). Supprimer est immédiat (Ctrl+Z annule) ; si la tâche a des
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

- Cartes en liste (ou vue compacte), **tri** : échéance, importance, urgence, priorité combinée, création,
  titre ; **regroupement** : aucun, projet, statut, type, échéance.
- Barre de filtres (voir 8.5).

### 8.3 📊 Kanbans

Boards **prédéfinis** (déplacer une carte modifie l'attribut correspondant) :

| Board | Colonnes | Effet du dépôt |
|---|---|---|
| 📊 Par statut | les 5 statuts | change le statut |
| 📅 Par échéance | ⚠️ En retard · 📅 Aujourd'hui · 🌅 Demain · 🗓️ Cette semaine · 🔭 Plus tard · ∅ Sans échéance | Aujourd'hui / Demain → cette date ; Cette semaine → vendredi ; Plus tard → +7 j ; Sans échéance → efface ; En retard → dépôt interdit |
| 🗂️ Par type | 📌 À faire · 👁️ Suivi | change le type |
| 📁 Par projet | un projet par colonne + « Sans projet » | change le projet |

Boards **personnalisés** : colonnes libres (nom, emoji, couleur), cartes rangées à la main par glisser-déposer,
une tâche peut figurer sur plusieurs boards, partageables.

- Option : masquer les tâches finies depuis plus de N jours.
- Barre de filtres sur tous les boards (voir 8.5) ; filtres mémorisés par board.

### 8.4 🎯 Matrice d'Eisenhower

Module indépendant, fonctionne comme un **kanban en 2D** :

- **Vue 2×2** (par défaut) — axes : important = importance ≥ 3, urgent = urgence ≥ 3 :
  🔥 **Faire** (important + urgent) · 📅 **Planifier** (important, pas urgent) ·
  🤝 **Déléguer** (urgent, pas important) · 🗑️ **Éliminer** (ni l'un ni l'autre).
- Déposer une carte dans un autre quadrant ajuste importance / urgence au **minimum nécessaire** pour
  entrer dans ce quadrant (ex. importance 2 → 3 ; une valeur déjà compatible n'est pas modifiée).
- **Vue détaillée 4×4** (bascule) : une case par combinaison exacte ; le dépôt fixe les deux valeurs.
- Mêmes filtres que les kanbans ; les tâches finies / annulées sont masquées par défaut.

### 8.5 Barre de filtres

- Champ texte général (titre, notes, tags, projet).
- Menus déroulants multi-sélection : importance, urgence, statut, type, projet, tags, échéance
  (en retard / aujourd'hui / cette semaine / sans échéance), propriétaire / partagées avec moi.
- Case « inclure les sous-tâches ». Bouton « réinitialiser ».

### 8.6 ⚙️ Réglages

- 👤 **Profil** : nom affiché, mot de passe.
- 🎨 **Apparence** : thème clair / sombre / auto.
- 🔔 **Rappels** : décalage par défaut (jours), notifications bureau oui/non.
- 📁 **Projets** et 🏷️ **Tags** : gestion des listes (voir 4.5).
- 📊 **Boards** : créer / renommer / supprimer / partager les boards personnalisés et leurs colonnes.
- 💻 **Appareils connectés** : sessions actives, révocation.
- 👥 **Utilisateurs** (admin) : créer, réinitialiser le mot de passe, désactiver, promouvoir admin.
- 🔌 **Connexion** (client bureau) : adresse du serveur, déconnexion.

---

## 9. Responsive / téléphone

- La colonne de gauche devient un tiroir (☰).
- Kanbans : colonnes en défilement horizontal au doigt ; matrice 2×2 empilée.
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
| 4 | Éditeur markdown CodeMirror (live preview, listes, cases, liens) |
| 5 | Modules : accueil, liste, filtres, recherche |
| 6 | Kanbans (prédéfinis + personnalisés), matrice, glisser-déposer, Ctrl+drop |
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
