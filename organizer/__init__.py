"""Organizer — organiseur de tâches multi-utilisateurs.

Versions (voir ``organizer/versioning.py``) :

- ``__version__`` : version du logiciel, ``MAJEUR.MINEUR.CORRECTIF`` (``0.<étape>.<correctif>`` jusqu'à la
  1.0.0, fin de l'étape 8) ; une étiquette git ``v<version>`` marque chaque version publiée ;
- ``API_VERSION`` : compatibilité entre client bureau et serveur, augmentée **seulement** quand un client
  plus ancien ne peut plus fonctionner avec le serveur (route supprimée ou modifiée…).
"""

__version__ = "0.7.0"
API_VERSION = 1
