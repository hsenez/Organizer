"""Pages web (connexion, création du premier compte, accueil), simulées avec la fixture ``user`` de NiceGUI.

Le simulateur suit les redirections HTTP et garde les cookies : on teste donc le parcours réel
formulaire → ticket → cookie → page protégée.
"""

from __future__ import annotations

import pytest
from nicegui import app, ui
from nicegui.testing import User

from organizer.core.schemas import TaskCreate


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ORGANIZER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ORGANIZER_PORT", "2699")
    return tmp_path


def state():
    return app.state.organizer


def fill(user: User, label: str, text: str) -> None:
    user.find(kind=ui.input, content=label).type(text)


async def test_first_visit_goes_to_setup_and_creates_admin(user: User):
    await user.open("/")
    await user.should_see("Créez le compte administrateur")
    fill(user, "Votre nom", "Alice")
    fill(user, "Identifiant de connexion", "alice")
    fill(user, "🔑 Mot de passe", "motdepasse")
    fill(user, "Confirmer le mot de passe", "motdepasse")
    user.find("🚀 Créer mon compte").click()
    await user.should_see("Bonjour Alice")
    assert state().users.get(1).is_admin


async def test_setup_rejects_mismatched_passwords(user: User):
    await user.open("/setup")
    fill(user, "Identifiant de connexion", "alice")
    fill(user, "🔑 Mot de passe", "motdepasse")
    fill(user, "Confirmer le mot de passe", "autre-chose")
    user.find("🚀 Créer mon compte").click()
    await user.should_see("ne correspondent pas")
    assert state().users.count() == 0


async def test_login_wrong_then_right_password(user: User):
    await user.open("/login")  # NiceGUI initialisé ; on crée le compte directement
    state().users.create_user("alice", "motdepasse", "Alice")
    await user.open("/")
    await user.should_see("Connectez-vous")
    fill(user, "Identifiant", "alice")
    fill(user, "Mot de passe", "mauvais")
    user.find("Se connecter").click()
    await user.should_see("Identifiant ou mot de passe incorrect")
    fill(user, "Mot de passe", "motdepasse")
    user.find("Se connecter").click()
    await user.should_see("Bonjour Alice")
    await user.should_see("Appareils connectés")


async def test_home_shows_counts_and_logout(user: User):
    await user.open("/login")
    alice = state().users.create_user("alice", "motdepasse", "Alice")
    sv = state().services_for(alice)
    sv.tasks.create(TaskCreate(title="Une"))
    sv.tasks.create(TaskCreate(title="Deux"))
    await user.open("/login")
    fill(user, "Identifiant", "alice")
    fill(user, "Mot de passe", "motdepasse")
    user.find("Se connecter").click()
    await user.should_see("Tâches ouvertes")
    await user.should_see("2")
    user.find("Déconnexion").click()
    await user.should_see("Connectez-vous")
    await user.open("/")
    await user.should_see("Connectez-vous")  # le cookie a bien été révoqué
