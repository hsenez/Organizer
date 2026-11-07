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

- ⏰ Saisie de l'**heure** d'échéance dans l'éditeur (le modèle la gère déjà).
- 💻 **Appareils connectés** : de nouveau visibles dans les réglages (étape 5) — déconnecter un appareil.
- 📁 **Création des projets** depuis l'interface (réglages, étape 5) ; aujourd'hui seuls les tags se créent
  depuis l'éditeur.
- 📋 **Dupliquer** une tâche (menu ⋯ des cartes).
- 🐍 Faire tourner les tests sous **Python 3.11** (version du Pi) — jamais exécutés dans cette version.
- 🔔 Notifications système des rappels sur le client bureau (étape 7).
