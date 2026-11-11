# 📋 Organizer — notes de version

Détail de chaque étape : historique de [`specifications.md`](specifications.md) (§12).

## 1.2.0 — 11 novembre 2026

Notes, et liens à partager.

### Nouveautés

- **📝 Notes** (colonne de gauche) : liste à gauche (épinglées d'abord, recherche, « De qui ? »), note à
  droite ; sur téléphone, la liste puis la note en plein écran.
  - Titre, **emoji** (liste personnelle modifiable dans Réglages → Apparence, aussi utilisée pour les
    projets), projet, tags, **📌 épingle** (personnelle).
  - Texte en **markdown façon Obsidian** avec une **barre de boutons** : titres, gras, italique, barré,
    puces, numéros, **cases à cocher**, citation, code, lien, séparation.
  - **Cases à cocher rangées toutes seules** : cocher une case l'envoie en tête des cochées, décocher la
    remonte tout en haut ; les non cochées restent au-dessus (Ctrl+Z annule).
  - **Partage** avec chaque personne en « peut modifier » ou « lecture seule », ou **publique** (lecture
    seule pour tous). Mise à jour en direct si la note est modifiée ailleurs (bandeau si l'on est en train
    d'écrire).
- **Liens entre notes, tâches et événements** : taper `[[` (ou « 🔗 Lier à… ») pour chercher et insérer un
  lien, affiché en **pastille cliquable** au titre de l'élément (🔒 s'il est supprimé ou invisible pour le
  lecteur) ; aussi dans les notes des tâches et des événements. **« Cité dans »** en bas de chaque note.
- **🔗 Copier le lien** d'une note, d'une tâche ou d'un événement, à coller dans un mail ou un message :
  - construit sur l'**adresse publique** du serveur (Réglages → 🗄️ Données, admin), valable de partout ;
  - le lien propose d'ouvrir l'élément dans le **client bureau** (liens `organizer://`, déclarés par
    l'installeur du client) ou de **continuer dans le navigateur** (choix retenu par appareil ; un
    téléphone va directement au navigateur) ;
  - collé dans une note, il devient une pastille.
- **Recherche Ctrl+K** : trouve aussi les notes. **Notifications** : partage et modification des notes.
- **Compte désactivé** : ses tâches, événements et notes ne restent visibles que pour ceux qui peuvent les
  modifier, qui peuvent alors aussi les supprimer ; tout revient si le compte est réactivé.

### Corrections

- Client bureau : une commande transmise au client déjà lancé partait avec de mauvais paramètres (sans
  effet visible jusqu'ici ; nécessaire pour les liens `organizer://`).

### Mise à jour depuis la 1.1.0

Sur le Pi : `deploy/update.sh` (ou, si le Pi est sur la branche de test, `deploy/install_test.sh --main`).
Les nouvelles tables sont créées au démarrage ; le schéma de la base ne change pas. Puis chaque poste :
`install/linux/update.sh` ou `install\windows\update.bat` (qui déclarent aussi les liens `organizer://`).
Ensuite, un administrateur règle l'**adresse publique** (Réglages → 🗄️ Données).

### Limites connues

- Édition d'une même note à deux en même temps : pas de fusion (le dernier qui écrit l'emporte, un bandeau
  prévient).
- Liens `organizer://` pas encore essayés en conditions réelles sous Windows.

## 1.1.0 — 10 novembre 2026

Calendrier et événements.

### Nouveautés

- **📅 Calendrier** (colonne de gauche) : vues **mois**, **semaine** et **6 semaines** (défilement à la
  semaine), du lundi au dimanche ; aujourd'hui sur fond jaune.
  - **Échéances des tâches** (interrupteur « 📋 Tâches », masquées par défaut) : pastilles de la couleur de
    l'**urgence**, pourtour de la couleur de l'**importance** ; tâches **en retard** ramenées à aujourd'hui
    (pastille d'alerte) ; colonne **📥 Sans échéance** réglable et repliable ; glisser une pastille vers un
    autre jour change l'échéance (ou la retire).
  - **Événements** : **bandes** pour ceux qui durent toute la journée ou plusieurs jours, étiquettes
    horaires pour les autres ; glisser vers un autre jour (horaires et durée gardés).
  - Clic droit ou **clic-glisser** sur des jours → nouvel événement (toute la journée sur plusieurs jours)
    ou nouvelle tâche ; clic sur un élément pour le **sélectionner**, **Suppr** pour le supprimer.
  - **Vue d'un jour** (double-clic) : ses tâches + **agenda sur deux colonnes** (0-12 h, 12-24 h) où l'on
    glisse un événement ou ses bords (pas de 15 min) ; double-clic sur une heure libre pour créer.
  - Filtres « 📅 Événements », « 📋 Tâches » (mémorisés) et « De qui ? » (toujours « Tous » à l'ouverture).
- **Événements** : début / fin ou journée entière, **lieu** avec boutons **Google Maps** et **Waze**,
  couleur (celle du projet, une palette ou une couleur libre), projet, tags, liens et fichiers, notes ;
  **partage** avec chaque personne en « peut modifier » (modifier et supprimer) ou « lecture seule », ou
  **public** (lecture seule pour tous).
- **Un seul éditeur** pour les tâches et les événements, avec une **bascule 📋 / 📅** : en création, les
  champs communs sont gardés ; sur un élément existant, il est converti (Ctrl+Z annule).
- **🔔 Notifications** (colonne de gauche, bulle avec le nombre de non lues) : ce que les autres ont fait qui
  vous concerne — partage, modification, suppression ; clic pour ouvrir l'élément.
- **Pictogrammes de partage** partout : 👥 à vous et partagé, 🤝 partagé avec vous, 👁️ lecture seule.
- **Tags et projets du même nom** (votre privé, le public d'un autre) : affichés « x (privé) » / « x
  (public) » sans mélange de couleurs ; une notification propose de renommer le vôtre ou de le fusionner
  dans le public ; deux publics du même nom sont refusés. **Fusion de projets** dans les réglages.

### Corrections

- Client bureau : la configuration pouvait se perdre quand deux enregistrements avaient lieu en même temps.

### Mise à jour depuis la 1.0.0

Sur le Pi : `deploy/update.sh` (ou, si le Pi est sur la branche de test, `deploy/install_test.sh --main`).
Les nouvelles tables sont créées au démarrage ; le schéma de la base ne change pas. Puis chaque poste :
`install/linux/update.sh` ou `install\windows\update.bat`.

### Limites connues

- Agenda du jour : gestes à la souris seulement (pas encore au doigt).
- Tâches partagées : toujours modifiables (pas de « lecture seule » par personne pour les tâches).

## 1.0.0 — 9 novembre 2026

Première version stable.

### Ce que fait Organizer

- **Tâches** avec importance, urgence, statut, type (« à faire » / « suivi » avec rappel), échéance et heure,
  projet, tags colorés, notes en markdown (rendu en direct, cases à cocher), liens web, chemins de fichiers et
  pièces jointes, sous-tâches, partage avec d'autres comptes. **Annuler / rétablir** (Ctrl+Z) partout.
- **Vues** : accueil (points chauds), liste filtrable / triable / regroupable, recherche (Ctrl+K), kanbans
  (statut, échéance, type, projet, et boards personnalisés partagés), matrice d'Eisenhower 2×2 et 4×4 ;
  glisser-déposer à la souris et au doigt, Ctrl + dépôt pour faire une sous-tâche.
- **Plusieurs utilisateurs** : comptes créés par l'administrateur, projets et tags publics ou privés,
  appareils connectés, thème clair / sombre.
- **Temps réel** : une modification apparaît sur les autres écrans ouverts.
- **Partout** : site web adapté au téléphone, installable comme une application (PWA) ; **client bureau**
  Linux et Windows (fenêtre native, arrière-plan, raccourcis globaux, notifications des rappels, ouverture
  des fichiers locaux, icône de zone de notification sous Windows).

### Depuis la fin de la feuille de route (0.8)

- **En ligne** sur `https://organizer.blou.top` par Cloudflare Tunnel, sans port ouvert sur la box :
  cookie sécurisé, en-têtes de sécurité, vraie adresse des visiteurs, documentation de l'API réservée aux
  connectés, anti force brute par identifiant, journal des connexions, mots de passe de 12 caractères.
- **Sauvegarde** : archive complète téléchargeable (Réglages → 🗄️ Données) ou par un jeton réservé au
  réseau local, pour un script borg quotidien ; **restauration** vérifiée par `deploy/restore.sh`.
- **Pièces jointes** : bouton réparé dans le client bureau, **glisser-déposer** de fichiers sur l'éditeur ou
  sur une carte (y compris depuis le gestionnaire de fichiers dans le client bureau).
- **Client bureau plus réactif** à travers Internet (une requête par clic au lieu de trois) et **passage
  automatique par le réseau local** à la maison (≈ 20 ms au lieu de ≈ 300 ms), avec vérification de
  l'identité du serveur ; indicateur 🏠 / 🌍 en bas à gauche.
- **Windows** : installeur, raccourcis globaux fiables, icône de zone de notification ; tests verts.
- Redémarrage du serveur en 3 s (au lieu de 90) ; Pi réglé en Latin-1 pris en charge.
- **Migrations de la base** : les versions suivantes pourront faire évoluer la base (nouvelles colonnes)
  automatiquement au démarrage, après une copie de sécurité.

### Mise à jour depuis une version 0.9

Sur le Pi : `deploy/update.sh` (la base passe au schéma 1, sans modification). Puis chaque poste :
`install/linux/update.sh` ou `install\windows\update.bat`.

### Limites connues

- Sauvegarde borg et restauration : à essayer en conditions réelles sur le Pi.
- Application installée sur téléphone (PWA) : pas encore essayée sur un vrai téléphone.
- Pas de mode hors connexion (voir [`TODO.md`](TODO.md)).
