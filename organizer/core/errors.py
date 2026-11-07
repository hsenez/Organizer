"""Erreurs métier. Le message est en français et peut être affiché tel quel à l'utilisateur."""

from __future__ import annotations


class OrganizerError(Exception):
    """Erreur métier générique."""

    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFound(OrganizerError):
    status_code = 404


class Forbidden(OrganizerError):
    status_code = 403


class InvalidOperation(OrganizerError):
    status_code = 422


class UndoConflict(OrganizerError):
    """L'action ne peut pas être annulée / rétablie : les données ont changé depuis."""

    status_code = 409
