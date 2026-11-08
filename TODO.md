# 📝 TODO — sujets à travailler

> Liste des sujets ouverts, hors feuille de route (`specifications.md` §11). Mise à jour à chaque changement.

---

## 📁 Liens vers des fichiers — à retravailler (demandé)

### Ce qui existe aujourd'hui

| Type | Ce qui est stocké | Web / téléphone | Client bureau (étape 7) |
|---|---|---|---|
| 📎 **Pièce jointe** (« Joindre un fichier ») | une **copie** du fichier, sur le Pi (`data/uploads/`) | ouvre / télécharge la copie | idem |
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
- 🐍 Faire tourner les tests sous **Python 3.11** (version du Pi) — jamais exécutés dans cette version
  (sur le Pi : `.venv/bin/pip install pytest pytest-asyncio && .venv/bin/pytest`).
- 📲 PWA jamais essayée sur un vrai téléphone (iPhone en HTTP, Android en HTTPS) : à faire une fois en ligne
  par Cloudflare Tunnel (mkcert devient inutile, sauf pour du HTTPS local).
- ✏️ Temps réel : si la tâche ouverte dans l'éditeur est modifiée ailleurs, l'éditeur ne se met pas à jour
  (volontairement : il ne doit pas changer sous les doigts) — afficher plutôt « modifiée ailleurs » ?
- 🪟 Client bureau : jamais essayé sous **Windows** (WebView2, `os.startfile`, notifications WinRT).
- 🖥️ Client bureau : glisser un fichier depuis l'explorateur sur une tâche pour l'ajouter en lien (pywebview
  fournit le chemin complet : événement `drop` de NiceGUI natif) — rejoint le sujet des liens de fichiers.
- 🔔 Si l'envoi d'une notification échoue (D-Bus absent…), la tâche est quand même notée « notifiée » pour
  la journée (desktop-notifier ne signale pas l'échec).
- 🔄 Scripts de mise à jour Windows (`update.ps1`) jamais exécutés.
- 🍓 `deploy/install.sh` et `deploy/update.sh` déroulés dans un bac à sable (faux sudo / systemctl) mais
  jamais sur un vrai Pi.
- 🧺 Client bureau : icône dans la zone de notification (« tray ») avec Ouvrir / Nouvelle tâche / Quitter —
  demanderait une dépendance (pystray + AppIndicator sous Linux).
- ⌨️ Raccourcis globaux GNOME (gsettings) écrits mais jamais essayés (poste de dev sous KDE).
- 🪟 Wayland : le jeton d'activation du lanceur est transmis pour ramener la fenêtre au premier plan ; à
  confirmer à l'usage (KDE peut se contenter de la faire clignoter dans la barre des tâches).
- 🗄️ Outil de **migration du schéma** de la base (ajout de colonnes) le jour où ce sera nécessaire.


### Ajoutés Manuellement

- En plus de taches publiques / privées, il y a des taches partagées avec une ou plusieurs personnes a choisir (parmi les autres comptes existants)
- Interface sur télégram pour envoyer une tache rapide
- Mettre une date de début optionnelle d'uen tache
- Mettre une date de rappel de mise à jour d'une tache obligatoire, par défaut 2 semaines après sa création
- Taches récurrentes
- Travail sur l'accueil pour display plus "straight to the point"
- Possibilité d'éditer la liste des emojis proposés dans la création de projets

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
  5. Guide Cloudflare Tunnel pas à pas dans le README (intitulés du tableau de bord vérifiés et datés).

#### Chantier important: Création d'événements. 

- Ils auront un début et une fin (date et heure) 
- Ils peuvent contenir des tâches (intéraction des attributs à définir clairement)
- Ils sont publics, privés ou partagés (comme les tâches)
- On aura en plus de kanban et compagnie dans le menu de gauche, un calendrier. 
  - Il affiche les événements, et optionnellement les dates critiques des taches (par défaut désactivé mais facilement ajoutable)
  - L'interface permet facilement d'éditer le début et la fin d'un événement (tiravec la souris)
  - Les événements et taches publics ou partagées spécifiquement avec moi sont potentiellement visibles aussi mais on peut filtrer poru ne pas les voir


### ✅ Faits récemment

- ⚡ Temps réel (web + client bureau), 📲 PWA, HTTPS facultatif, 🌳 « Rattacher à… », ↑ ↓ dans Ctrl+K,
  défilement automatique pendant un glisser, rappel par défaut à jour, compteur de filtres (étape 8).
- ⏰ Heure d'échéance dans l'éditeur · 💻 appareils connectés et 📁 projets dans les réglages ·
  📋 dupliquer une tâche (étape 5).
- 📊 Kanbans, 🎯 matrice, glisser-déposer souris / tactile et Ctrl+drop (étape 6).
- 📊 Kanbans pleine page, colonnes repliables / redimensionnables, reclassement = urgence affinée (v1.4).
- 🖥️ Client bureau : fenêtre native, connexion par jeton, liens et fichiers locaux, 🔔 notifications (étape 7).
- 🖥️ Client bureau en arrière-plan, raccourcis clavier globaux, installeurs Linux / Windows (v1.6).
- 🏷️ Versions (0.7.0, API 1), bandeau « mise à jour disponible », scripts de mise à jour (v1.7).
