# 📝 TODO — sujets à travailler

> Liste des sujets ouverts, hors feuille de route (`specifications.md` §11). Mise à jour à chaque changement.

---

## 📁 Liens vers des fichiers — à retravailler (demandé)

### Ce qui existe aujourd'hui

| Type | Ce qui est stocké | Web / téléphone | Client bureau (étape 7) |
|---|---|---|---|
| 📎 **Pièce jointe** (« Joindre un fichier », ou fichier déposé sur l'éditeur) | une **copie** du fichier, sur le Pi (`data/uploads/`) | ouvre / télécharge la copie | idem |
| 📁 **Chemin local** (collé dans le champ des liens) | seulement le **chemin** (`/home/…`, `C:\…`) | **copie le chemin** dans le presse-papiers | ouvrira le fichier d'origine |

Limites constatées :

- La pièce jointe est une **copie figée** : modifier l'original ne met pas la copie à jour (et inversement).
- Un navigateur **ne peut ni ouvrir un fichier local, ni connaître son chemin** : le sélecteur de fichiers
  du navigateur donne le contenu, jamais l'emplacement. Le chemin doit donc être collé à la main.
- Un chemin n'est valable que sur **une machine** : `/home/hubert/…` sous Linux n'existe pas sous Windows,
  ni sur le téléphone.
- Dans l'interface, la différence « copie » / « lien » n'est pas assez visible.

### Pistes pour gérer ça efficacement

1. **Clarifier l'interface** (simple, rapide) : deux actions distinctes avec explication en infobulle :
   « 📎 Envoyer une copie sur le serveur » et « 📁 Lier un fichier (sans le copier) ». Afficher sur chaque
   lien s'il s'agit d'une copie ou d'un lien, et sur quelle machine il a été créé.
2. **Client bureau : vrai sélecteur de fichier** : la fenêtre native (pywebview) peut ouvrir le sélecteur du
   système et récupérer le **vrai chemin** → bouton « 📁 Lier un fichier… » sans copier-coller, ouverture
   avec l'application par défaut, **glisser-déposer** d'un fichier sur une tâche avec choix « lier » ou
   « copier ».
3. **Dossiers partagés (« racines »)** : déclarer dans les réglages des dossiers communs, par exemple un
   partage réseau du Pi (Samba) ou un NAS, avec leur chemin sur chaque machine :
   `Documents partagés` = `/mnt/partage` (Linux) = `\\raspberrypi\partage` ou `P:\` (Windows).
   Un lien est alors enregistré **relativement à la racine** (`{Documents partagés}/factures/2026.pdf`) et
   chaque client le traduit en chemin local → un même lien fonctionne sur tous les PC.
4. **Pièces jointes « vivantes »** : stocker les pièces jointes dans un dossier partagé du Pi (Samba) plutôt
   que dans `data/uploads/` caché : on peut alors ouvrir et **modifier le fichier sur place** depuis le
   réseau, sans copie figée. Option : garder les anciennes versions quand on remplace un fichier.
5. **Vérifier les liens** : sur le client bureau, signaler les fichiers introuvables (🔴 lien cassé) ;
   proposer de « relier » (chercher le fichier déplacé).
6. **Ménage des pièces jointes** : supprimer du disque les fichiers qui ne sont plus référencés par aucun
   lien (après expiration de l'historique annuler / rétablir).

À décider ensemble : faut-il un partage réseau sur le Pi (Samba) ? Quelles machines doivent ouvrir les
fichiers (PC Linux, PC Windows, téléphone) ?

---

## 🧩 Autres points en attente (relevés pendant le développement)

- ↕️ Réordonner les sous-tâches par glisser-déposer dans l'éditeur (le service le permet déjà).
- 📊 Boards personnalisés : réordonner les boards eux-mêmes ; choisir les colonnes de départ à la création.
- 🎯 Matrice : reclasser les cartes dans une case (comme au kanban) ; pleine largeur comme les kanbans ?
- 📊 Boards personnalisés : l'ordre y est libre (il ne touche pas l'urgence) — à confirmer à l'usage.

- 📋 **Vue compacte** de la liste (une ligne par tâche, comme les résultats de Ctrl+K).
- 🐍 Tests sous **Python 3.11** (version du Pi) : lancés une première fois (5 échecs, corrigés : option
  `tarfile` absente de 3.11.2, Pi réglé en Latin-1) ; à relancer sur le Pi après la mise à jour
  (`.venv/bin/pytest`).
- 📲 PWA jamais essayée sur un vrai téléphone (iPhone en HTTP, Android en HTTPS) : à faire une fois en ligne
  par Cloudflare Tunnel (mkcert devient inutile, sauf pour du HTTPS local).
- ✏️ Temps réel : si la tâche ouverte dans l'éditeur est modifiée ailleurs, l'éditeur ne se met pas à jour
  (volontairement : il ne doit pas changer sous les doigts) — afficher plutôt « modifiée ailleurs » ?
- 🪟 Client bureau sous **Windows** : installé et lancé (Python 3.13, novembre 2026) ; reste à essayer
  WebView2 à l'usage, `os.startfile` (ouvrir un lien vers un fichier local), notifications WinRT. La suite
  de tests passe sous Windows (version 0.9.4).
- 🖥️ Client bureau : glisser un fichier depuis l'explorateur sur une tâche pour l'ajouter en lien (pywebview
  fournit le chemin complet : événement `drop` de NiceGUI natif) — rejoint le sujet des liens de fichiers.
- 🔔 Si l'envoi d'une notification échoue (D-Bus absent…), la tâche est quand même notée « notifiée » pour
  la journée (desktop-notifier ne signale pas l'échec).
- 🔄 Scripts de mise à jour Windows (`update.ps1`) jamais exécutés.
- 🍓 `deploy/install.sh` et `deploy/update.sh` déroulés dans un bac à sable (faux sudo / systemctl) mais
  jamais sur un vrai Pi.
- 🧺 Client bureau : icône dans la zone de notification (« tray ») — faite sous **Windows** (`winshell.py`) ;
  sous Linux, demanderait une dépendance (pystray + AppIndicator).
- 🪟 Windows : raccourcis globaux et icône de zone de notification vérifiés par un appui simulé
  (`keybd_event`), pas encore dans le vrai client à l'usage ; sans démarrage avec la session
  (`-NoAutostart`), plus de raccourci global pour lancer Organizer à froid.
- ⌨️ Raccourcis globaux GNOME (gsettings) écrits mais jamais essayés (poste de dev sous KDE).
- 🪟 Wayland : le jeton d'activation du lanceur est transmis pour ramener la fenêtre au premier plan ; à
  confirmer à l'usage (KDE peut se contenter de la faire clignoter dans la barre des tâches).


### Ajoutés Manuellement

- En plus de taches publiques / privées, il y a des taches partagées avec une ou plusieurs personnes a choisir (parmi les autres comptes existants)
- Interface sur télégram pour envoyer une tache rapide
- Mettre une date de début optionnelle d'uen tache
- Mettre une date de rappel de mise à jour d'une tache obligatoire, par défaut 2 semaines après sa création
- Taches récurrentes
- Travail sur l'accueil pour display plus "straight to the point"
- Possibilité d'éditer la liste des emojis proposés dans la création de projets
- Dans les réglages une référence à la base de donnée utilisée (admin seulement)

#### Support HTTPS & reverse proxy

- mettre en ligne sur https://organizer.blou.top
- **Décidé** : **Cloudflare Tunnel** (`cloudflared` sur le Pi, paquet et non Docker), sans nginx ni certbot ;
  le serveur reste sur `0.0.0.0` pour l'instant (accès local direct conservé). Voir `specifications.md` §10.4.
- Plan :
  1. ✅ Derrière un proxy : cookie `Secure` selon le visiteur, en-têtes de sécurité (HSTS…), IP réelle testée.
  2. ✅ Durcissement : `/docs` réservé aux connectés, limite d'échecs par identifiant (20 / h toutes IP),
     journal des connexions, option `--host` de `deploy/install.sh`, mots de passe de 12 caractères.
  3. ✅ Sauvegarde : `GET /api/v1/admin/backup` (`.tar` non compressé : base cohérente + `uploads/` +
     `manifest.json`), jetons de sauvegarde (table `api_key`, réseau local seulement), onglet 🗄️ Données.
  4. ✅ Restauration : `deploy/restore.sh` (archive ou flux `borg export-tar … -`), script borg dans le README.
     ⚠️ **À tester en vrai (Hubert, plus tard)** : créer le jeton de sauvegarde, installer le script borg
     quotidien du README sur le Pi (cron), vérifier les archives (`borg list`), puis faire un **exercice
     de restauration** (`borg export-tar … - | deploy/restore.sh -`) et contrôler que tout est revenu.
  5. ✅ Guide Cloudflare Tunnel pas à pas dans le README (section « Accès depuis Internet »).

#### Chantier important: Création d'événements. 

- Ils auront un début et une fin (date et heure) 
- Ils peuvent contenir des tâches (intéraction des attributs à définir clairement)
- Ils sont publics, privés ou partagés (comme les tâches)
- On aura en plus de kanban et compagnie dans le menu de gauche, un calendrier. 
  - Il affiche les événements, et optionnellement les dates critiques des taches (par défaut désactivé mais facilement ajoutable)
  - L'interface permet facilement d'éditer le début et la fin d'un événement (tiravec la souris)
  - Les événements et taches publics ou partagées spécifiquement avec moi sont potentiellement visibles aussi mais on peut filtrer poru ne pas les voir

#### Chantier : client bureau plus fluide et mode hors connexion (demandé, « un jour »)

Idée de départ : réécrire le client bureau en Qt (PyQt / PySide6), toutes les actions passant par l'API, avec
un mode **hors connexion** (coupure réseau) et une **synchronisation** au retour de la connexion.

- **Faisable, mais deux projets à séparer** :
  1. **Hors connexion + synchronisation** (le plus utile, le plus difficile ; indépendant de la bibliothèque
     graphique, faisable dans le client actuel) : copie locale (SQLite) lue et modifiée par le client, file
     des modifications à envoyer. Points durs : identifiants des tâches créées hors connexion (provisoires,
     ou passage à des UUID dans le modèle), conflits (même champ modifié sur deux appareils : règle à
     choisir, ex. dernier qui écrit gagne, champ par champ), annuler / rétablir (historique aujourd'hui sur
     le serveur), pièces jointes envoyées plus tard, partage / droits, beaucoup de tests de synchronisation.
  2. **Interface Qt** : préférer **PySide6** (LGPL) à PyQt (GPL ou licence commerciale). Coût : deux
     interfaces à maintenir (aujourd'hui le site et le client partagent les mêmes pages) ; tout à refaire
     (éditeur, markdown façon Obsidian, kanbans et glisser-déposer, matrice, réglages…), et chaque nouvelle
     fonctionnalité deux fois ensuite.
- **Fluidité sans changer de bibliothèque** : appels à l'API en arrière-plan (aujourd'hui chaque clic attend
  la réponse du serveur), affichage mis à jour tout de suite puis envoi au serveur ; avec la copie locale
  du point 1, toutes les lectures deviennent instantanées.
- **Ordre conseillé** : (1) copie locale + synchronisation dans le client actuel ; (2) affichage immédiat ;
  (3) interface Qt seulement si ce n'est pas assez fluide, en s'appuyant sur cette copie locale.

### ✅ Faits récemment

- 🧬 **Migrations de la base** (version 1.0.0) : numéro de schéma, étapes transactionnelles, copie avant
  migration, base trop récente refusée.

- ⚡ Temps réel (web + client bureau), 📲 PWA, HTTPS facultatif, 🌳 « Rattacher à… », ↑ ↓ dans Ctrl+K,
  défilement automatique pendant un glisser, rappel par défaut à jour, compteur de filtres (étape 8).
- ⏰ Heure d'échéance dans l'éditeur · 💻 appareils connectés et 📁 projets dans les réglages ·
  📋 dupliquer une tâche (étape 5).
- 📊 Kanbans, 🎯 matrice, glisser-déposer souris / tactile et Ctrl+drop (étape 6).
- 📊 Kanbans pleine page, colonnes repliables / redimensionnables, reclassement = urgence affinée (v1.4).
- 🖥️ Client bureau : fenêtre native, connexion par jeton, liens et fichiers locaux, 🔔 notifications (étape 7).
- 🖥️ Client bureau en arrière-plan, raccourcis clavier globaux, installeurs Linux / Windows (v1.6).
- 🏷️ Versions (0.7.0, API 1), bandeau « mise à jour disponible », scripts de mise à jour (v1.7).
