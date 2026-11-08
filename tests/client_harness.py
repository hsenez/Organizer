"""Lien entre les tests des pages du client bureau et leur fichier principal (``client_main.py``) : le test
y dépose le client HTTP du serveur de test."""

from __future__ import annotations

import httpx

HTTP: httpx.Client | None = None
