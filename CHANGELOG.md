# 📋 Organizer — notes de version

Détail de chaque étape : historique de [`specifications.md`](specifications.md) (§12).

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
