"""Organizer — organiseur de tâches multi-utilisateurs.

Versions (voir ``organizer/versioning.py``) :

- ``__version__`` : version du logiciel, ``MAJEUR.MINEUR.CORRECTIF`` (``0.<étape>.<correctif>`` jusqu'à la
  1.0.0, fin de l'étape 8) ; une étiquette git ``v<version>`` marque chaque version publiée ;
- ``API_VERSION`` : compatibilité entre client bureau et serveur, augmentée **seulement** quand un client
  plus ancien ne peut plus fonctionner avec le serveur (route supprimée ou modifiée…).
"""

from pathlib import Path

__version__ = "1.2.0"
API_VERSION = 1

# Icônes de l'application (générées par scripts/make_icons.sh) : fenêtre, lanceurs, favicon, PWA.
ASSETS_DIR = Path(__file__).parent / "assets"
FAVICON = ASSETS_DIR / "organizer.svg"
