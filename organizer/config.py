"""Configuration de l'application.

Tout se règle par variables d'environnement (préfixe ``ORGANIZER_``), avec des valeurs par défaut adaptées
au Raspberry Pi du réseau local.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    return os.environ.get(f"ORGANIZER_{name}", default)


@dataclass(frozen=True)
class Settings:
    """Paramètres globaux (immuables une fois chargés)."""

    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", str(PROJECT_ROOT / "data"))))
    host: str = field(default_factory=lambda: _env("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(_env("PORT", "2603")))
    # Décalage par défaut (en jours) entre l'échéance et le rappel d'une tâche de suivi.
    default_reminder_offset_days: int = 2
    # Nombre d'actions conservées dans l'historique annuler / rétablir de chaque utilisateur.
    undo_history_size: int = 50
    # Délai (secondes) en dessous duquel deux modifications du même champ sont fusionnées dans l'historique.
    undo_merge_window_seconds: float = 5.0
    # Durée de validité du cookie « se souvenir de moi » (prolongée à chaque utilisation).
    remember_me_days: int = 30
    # Session web sans « se souvenir de moi » : expire après cette inactivité ou à la fermeture du navigateur.
    web_session_hours: int = 24
    # Jeton du client bureau (prolongé à chaque utilisation).
    api_token_days: int = 90
    # Anti force brute : nombre d'échecs de connexion tolérés par (adresse IP, identifiant) et fenêtre.
    login_max_failures: int = 5
    login_failure_window_minutes: int = 10
    # Taille maximale d'une pièce jointe (Mo).
    max_upload_mb: int = 50

    @property
    def db_path(self) -> Path:
        return self.data_dir / "organizer.db"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"


def load_settings() -> Settings:
    return Settings()
