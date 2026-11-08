"""Pages web simulées avec la fixture ``user`` de NiceGUI.

Le simulateur suit les redirections HTTP et garde les cookies : on teste le parcours réel
formulaire → ticket → cookie → page protégée, puis l'interface (cartes, éditeur, annuler).
"""

from __future__ import annotations

import asyncio

import pytest
from nicegui import app, ui
from nicegui.testing import User

from organizer.core.enums import Importance, Status, Urgency
from organizer.core.schemas import ProjectIn, TaskCreate, TaskFilter, TaskPatch


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ORGANIZER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ORGANIZER_PORT", "2699")
    return tmp_path


def state():
    return app.state.organizer


def fill(user: User, label: str, text: str) -> None:
    user.find(kind=ui.input, content=label).type(text)


def open_menu(user: User, marker: str) -> None:
    """Ouvre un menu (comme un clic sur son bouton dans le navigateur)."""
    with user.client:
        user.find(marker=marker).elements.pop().open()


async def login(user: User, name: str = "alice"):
    """Crée le compte (le premier est admin), se connecte, renvoie les services de l'utilisateur."""
    await user.open("/login")  # initialise l'application
    account = state().users.create_user(name, "motdepasse-12", name.capitalize())
    await user.open("/login")
    fill(user, "Identifiant", name)
    fill(user, "Mot de passe", "motdepasse-12")
    user.find("Se connecter").click()
    await user.should_see(f"Bonjour {name.capitalize()}")
    return state().services_for(account)


# --- connexion --------------------------------------------------------------------------------------------


async def test_first_visit_goes_to_setup_and_creates_admin(user: User):
    await user.open("/")
    await user.should_see("Créez le compte administrateur")
    fill(user, "Votre nom", "Alice")
    fill(user, "Identifiant de connexion", "alice")
    fill(user, "🔑 Mot de passe", "motdepasse-12")
    fill(user, "Confirmer le mot de passe", "motdepasse-12")
    user.find("🚀 Créer mon compte").click()
    await user.should_see("Bonjour Alice")
    assert state().users.get(1).is_admin


async def test_setup_rejects_mismatched_passwords(user: User):
    await user.open("/setup")
    fill(user, "Identifiant de connexion", "alice")
    fill(user, "🔑 Mot de passe", "motdepasse-12")
    fill(user, "Confirmer le mot de passe", "autre-chose")
    user.find("🚀 Créer mon compte").click()
    await user.should_see("ne correspondent pas")
    assert state().users.count() == 0


async def test_login_wrong_then_right_password(user: User):
    await user.open("/login")
    state().users.create_user("alice", "motdepasse-12", "Alice")
    await user.open("/tasks")
    await user.should_see("Connectez-vous")
    fill(user, "Identifiant", "alice")
    fill(user, "Mot de passe", "mauvais")
    user.find("Se connecter").click()
    await user.should_see("Identifiant ou mot de passe incorrect")
    fill(user, "Mot de passe", "motdepasse-12")
    user.find("Se connecter").click()
    await user.should_see(marker="list-sort")  # redirigé vers la page demandée au départ (/tasks)


async def test_logout(user: User):
    await login(user)
    open_menu(user, "account-menu")
    user.find(marker="logout-item").click()
    await user.should_see("Connectez-vous")
    await user.open("/")
    await user.should_see("Connectez-vous")  # le cookie a bien été révoqué


async def test_short_password_banner_until_changed(user: User, monkeypatch):
    """Un compte dont le mot de passe date d'avant le minimum de 12 caractères : connexion possible, bandeau
    jusqu'au changement."""
    from organizer.core.services import users as users_module

    await user.open("/login")
    monkeypatch.setattr(users_module, "MIN_PASSWORD_LENGTH", 6)
    state().users.create_user("alice", "ancien", "Alice")
    monkeypatch.undo()
    await user.open("/login")
    fill(user, "Identifiant", "alice")
    fill(user, "Mot de passe", "ancien")
    user.find("Se connecter").click()
    await user.should_see("Bonjour Alice")
    await user.should_see(marker="password-banner")
    await user.should_see("au moins 12 caractères")

    await user.open("/settings?tab=profile")
    fill(user, "Mot de passe actuel", "ancien")
    fill(user, "Nouveau mot de passe", "un-mot-de-passe-long")
    fill(user, "Confirmer", "un-mot-de-passe-long")
    user.find(marker="change-password").click()
    await user.should_not_see(marker="password-banner")  # retiré tout de suite de la page affichée
    assert state().users.get_pref(1, "security:weak_password") is None
    await user.open("/")
    await user.should_see("Bonjour Alice")
    await user.should_not_see(marker="password-banner")


async def test_no_password_banner_for_long_password(user: User):
    await login(user)
    await user.should_not_see(marker="password-banner")


# --- accueil et cartes ------------------------------------------------------------------------------------


async def test_home_sections_and_counts(user: User):
    sv = await login(user)
    sv.tasks.create(TaskCreate(title="Urgente et importante", importance=4, urgency=4))
    calm = sv.tasks.create(TaskCreate(title="Tranquille", importance=1, urgency=1))
    await user.open("/")
    await user.should_see("À faire maintenant")
    await user.should_see("Urgente et importante")
    await user.should_not_see(marker=f"task-card-{calm.id}")  # pas un point chaud
    await user.open("/tasks")
    await user.should_see("Tranquille")


async def test_placeholder_modules(user: User):
    await login(user)
    await user.open("/kanban")
    await user.should_see(marker="zone-status:in_progress")
    await user.open("/matrix")
    await user.should_see(marker="zone-q:do")


# --- ajout rapide, éditeur, annuler -----------------------------------------------------------------------


async def test_new_task_opens_full_editor_and_creates_on_title(user: User):
    sv = await login(user)
    await user.open("/tasks")
    user.find(marker="fab-add").click()
    await user.should_see("Nouvelle tâche")
    # Réglages faits avant le titre : gardés dans le brouillon, rien en base.
    user.find(marker="slider-importance-4").click()
    user.find(marker="slider-urgency-3").click()
    assert sv.tasks.list() == []
    user.find(marker="editor-title").type("Acheter du pain").trigger("blur")
    tasks = sv.tasks.list()
    assert [(t.title, t.importance, t.urgency) for t in tasks] == [("Acheter du pain", 4, 3)]
    # La tâche existe : les réglages suivants sont enregistrés directement.
    user.find(marker="slider-status-in_progress").click()
    assert sv.tasks.get(tasks[0].id).status is Status.IN_PROGRESS
    await user.should_see("Ajouter une sous-tâche")  # sections complètes disponibles
    # Une seule entrée « Créer » dans l'historique, puis la modification du statut.
    assert sv.undo.status().undo_label.startswith("Statut de")
    sv.undo.undo()
    assert sv.undo.status().undo_label == "Créer « Acheter du pain »"


async def test_new_task_without_title_creates_nothing(user: User):
    sv = await login(user)
    await user.open("/tasks")
    user.find(marker="fab-add").click()
    user.find(marker="slider-importance-1").click()
    with user.client:
        ctx_editor = user.find(marker="task-editor").elements.pop()
        dialog = next(a for a in ctx_editor.ancestors() if isinstance(a, ui.dialog))
        dialog.close()
    assert sv.tasks.list() == []


async def test_home_tiles_show_task_lists(user: User):
    sv = await login(user)
    sv.tasks.create(TaskCreate(title="Tranquille", importance=1, urgency=1))
    started = sv.tasks.create(
        TaskCreate(title="Commencée", status=Status.IN_PROGRESS, importance=1, urgency=1)
    )
    await user.open("/")
    await user.should_not_see(marker="tile-panel")
    user.find(marker="tile-open").click()
    await user.should_see(marker="tile-panel")
    with user.scope(marker="tile-panel"):
        await user.should_see("Tranquille")
        await user.should_see("Commencée")
    user.find(marker="tile-in_progress").click()
    await user.should_not_see("Tranquille")  # attend la reconstruction du panneau
    with user.scope(marker="tile-panel"):
        await user.should_see("Commencée")
    user.find(marker="tile-in_progress").click()  # second clic : replie
    await user.should_not_see(marker="tile-panel")
    assert started.status is Status.IN_PROGRESS


async def test_editor_slider_click_saves_and_ctrl_z_reverts(user: User):
    sv = await login(user)
    task = sv.tasks.create(TaskCreate(title="Ranger"))
    await user.open("/tasks")
    user.find(marker=f"task-card-{task.id}").click()
    await user.should_see(marker="task-editor")
    user.find(marker="slider-importance-4").click()  # clic sur l'emoji 🔴 Critique
    assert sv.tasks.get(task.id).importance is Importance.CRITICAL
    user.find(marker="slider-status-in_progress").click()
    assert sv.tasks.get(task.id).status is Status.IN_PROGRESS
    user.find(marker="undo-button").click()
    assert sv.tasks.get(task.id).status is Status.NOT_STARTED
    user.find(marker="undo-button").click()
    assert sv.tasks.get(task.id).importance is Importance.NORMAL


async def test_editor_adds_subtasks_and_notes(user: User):
    sv = await login(user)
    task = sv.tasks.create(TaskCreate(title="Déménager"))
    await user.open("/tasks")
    user.find(marker=f"task-card-{task.id}").click()
    user.find(marker="editor-new-subtask").type("Cartons").trigger("keydown.enter")
    await user.should_see("Cartons")
    subs = sv.tasks.subtasks(task.id)
    assert [s.title for s in subs] == ["Cartons"]
    notes = user.find(marker="editor-notes")
    with user.client:
        next(iter(notes.elements)).value = "1. réserver le camion"  # comme envoyé par l'éditeur markdown
    notes.trigger("blur")
    assert sv.tasks.get(task.id).notes == "1. réserver le camion"


async def test_notes_saved_when_editor_closes(user: User):
    sv = await login(user)
    task = sv.tasks.create(TaskCreate(title="Courses"))
    await user.open(f"/tasks?task={task.id}")
    editor = next(iter(user.find(marker="editor-notes").elements))
    with user.client:
        editor.value = "- [ ] lait"  # dernière frappe, pas encore enregistrée
    user.find(marker="task-editor-dialog").trigger("hide")  # fermeture côté navigateur
    assert sv.tasks.get(task.id).notes == "- [ ] lait"


async def test_double_click_on_note_link(user: User):
    sv = await login(user)
    task = sv.tasks.create(TaskCreate(title="Lire", notes="Voir /home/alice/doc.pdf"))
    await user.open(f"/tasks?task={task.id}")
    user.find(marker="editor-notes").trigger("open-link", {"target": "/home/alice/doc.pdf", "kind": "path"})
    await user.should_see("Chemin copié")


async def test_note_web_link_is_opened_not_copied(user: User, monkeypatch):
    from organizer.ui.components import task_editor

    opened = []
    monkeypatch.setattr(
        task_editor, "open_link", lambda kind, target, ds: opened.append((kind.value, target))
    )
    sv = await login(user)
    task = sv.tasks.create(TaskCreate(title="Lire", notes="[le site](google.fr) et https://example.org"))
    await user.open(f"/tasks?task={task.id}")
    notes = user.find(marker="editor-notes")
    notes.trigger("open-link", {"target": "google.fr", "kind": "link"})
    notes.trigger("open-link", {"target": "https://example.org", "kind": "url"})
    notes.trigger("open-link", {"target": "~/Documents", "kind": "path"})
    assert opened == [("url", "google.fr"), ("url", "https://example.org"), ("path", "~/Documents")]


async def test_editor_creates_tag_on_the_fly(user: User):
    sv = await login(user)
    task = sv.tasks.create(TaskCreate(title="Factures"))
    await user.open("/tasks")
    user.find(marker=f"task-card-{task.id}").click()
    select = user.find(marker="editor-tags").elements.pop()
    with user.client:
        select.value = ["papiers"]  # nouvelle valeur tapée dans le champ
    assert [t.name for t in sv.tasks.get(task.id).tags] == ["papiers"]
    assert [t.name for t in sv.tags.list()] == ["papiers"]


async def test_editor_link_path_is_copied_on_web(user: User):
    sv = await login(user)
    task = sv.tasks.create(TaskCreate(title="Doc"))
    await user.open("/tasks")
    user.find(marker=f"task-card-{task.id}").click()
    user.find(marker="editor-new-link").type("/home/alice/rapport.pdf").trigger("keydown.enter")
    await user.should_see("/home/alice/rapport.pdf")
    link = sv.tasks.get(task.id).links[0]
    user.find(marker=f"link-{link.id}").click()
    await user.should_see("Chemin copié")
    assert [link.kind.value for link in sv.tasks.get(task.id).links] == ["path"]


def _upload_files(user: User, *files: tuple[str, bytes]):
    """Simule la fin d'un envoi de fichiers (choisis dans le sélecteur ou déposés sur l'éditeur)."""
    from nicegui.elements.upload_files import SmallFileUpload

    upload = user.find(marker="editor-upload").elements.pop()
    return upload.handle_uploads([SmallFileUpload(name, "text/plain", data) for name, data in files])


async def test_editor_attachments_button_and_drop_zone(user: User):
    sv = await login(user)
    task = sv.tasks.create(TaskCreate(title="Facture"))
    await user.open("/tasks")
    user.find(marker=f"task-card-{task.id}").click()
    await user.should_see(marker="editor-attach")

    upload = user.find(marker="editor-upload").elements.pop()
    # Le bouton ouvre le sélecteur dans le navigateur même, sans passer par le serveur (sinon WebKit — fenêtre
    # du client bureau —, Safari et Chrome refusent de l'ouvrir : le geste de l'utilisateur est perdu).
    (button,) = user.find(marker="editor-attach").elements
    listeners = [lst for lst in button._event_listeners.values() if lst.type == "click"]
    assert [(lst.handler, lst.js_handler) for lst in listeners] == [
        (None, f"() => runMethod({upload.id}, 'pickFiles', [])")
    ]
    # Les fichiers déposés n'importe où sur l'éditeur vont à ce même composant d'envoi.
    (card,) = user.find(marker="task-editor").elements
    assert card.props["data-file-drop"] == str(upload.id)
    assert user.find(marker="file-drop").elements  # composant de dépôt présent sur la page

    await _upload_files(user, ("devis.txt", b"devis"), ("plan.txt", b"plan"))
    await user.should_see("plan.txt")
    links = sv.tasks.get(task.id).links
    assert sorted(link.label for link in links) == ["devis.txt", "plan.txt"]
    assert {link.kind.value for link in links} == {"attachment"}


async def test_files_dropped_on_a_card_are_attached_to_its_task(user: User):
    from nicegui.elements.upload_files import SmallFileUpload

    sv = await login(user)
    task = sv.tasks.create(TaskCreate(title="Devis"))
    await user.open("/tasks")
    await user.should_see(marker=f"task-card-{task.id}")
    drop = user.find(marker="file-drop")
    # Le navigateur annonce la carte visée, puis envoie les fichiers par le composant d'envoi de la page.
    drop.trigger("card-files", {"task": task.id, "names": ["devis.txt"]})
    upload = user.find(marker="card-upload").elements.pop()
    await upload.handle_uploads([SmallFileUpload("devis.txt", "text/plain", b"devis")])
    await user.should_see("joint à « Devis »")
    assert [link.label for link in sv.tasks.get(task.id).links] == ["devis.txt"]


async def test_dropped_file_paths_need_the_desktop_client(user: User):
    """Moteur qui ne donne que l'adresse file:// d'un fichier déposé : seul le client bureau peut le lire."""
    sv = await login(user)
    task = sv.tasks.create(TaskCreate(title="Devis"))
    await user.open("/tasks")
    user.find(marker="file-drop").trigger(
        "paths", {"kind": "card", "task": task.id, "uris": ["file:///etc/hosts"]}
    )
    await user.should_see("n'a pas transmis le contenu")
    assert sv.tasks.get(task.id).links == []
    user.find(marker="file-drop").trigger("missed", {"target": "div", "types": ["Files"], "files": 0})
    await user.should_see("Déposez le fichier sur une tâche")


async def test_editor_drop_on_draft_asks_for_a_title(user: User):
    sv = await login(user)
    await user.open("/tasks")
    user.find(marker="fab-add").click()
    await user.should_see("Nouvelle tâche")
    await _upload_files(user, ("devis.txt", b"devis"))
    await user.should_see("Donnez d'abord un titre")
    assert sv.tasks.list() == []


async def test_card_menu_changes_status(user: User):
    sv = await login(user)
    task = sv.tasks.create(TaskCreate(title="Lessive"))
    await user.open("/tasks")
    open_menu(user, f"card-menu-{task.id}")
    user.find(marker=f"card-status-{task.id}-done").click()
    assert sv.tasks.get(task.id).status is Status.DONE
    await user.should_see("Terminées et annulées (1)")
    assert sv.tasks.list(TaskFilter(status=[Status.DONE]))[0].title == "Lessive"


# --- étape 5 : filtres, tri, recherche, réglages ----------------------------------------------------------


def select_value(user: User, marker: str, value) -> None:
    """Choisit une valeur dans un ui.select (comme un clic sur une option)."""
    with user.client:
        next(iter(user.find(marker=marker).elements)).set_value(value)


async def test_filters_are_applied_and_remembered(user: User):
    sv = await login(user)
    hot = sv.tasks.create(TaskCreate(title="Urgent", importance=4))
    calm = sv.tasks.create(TaskCreate(title="Calme", importance=1))
    await user.open("/tasks")
    await user.should_see(marker=f"task-card-{calm.id}")
    user.find(marker="filter-toggle").click()  # déplie le panneau des filtres
    select_value(user, "filter-Importance", [4])
    await user.should_not_see(marker=f"task-card-{calm.id}")
    await user.should_see(marker=f"task-card-{hot.id}")
    await user.should_see("🎛️ Filtres (1)")
    await user.open("/tasks")  # rechargement : le filtre est mémorisé
    await user.should_not_see(marker=f"task-card-{calm.id}")
    user.find(marker="filter-reset").click()
    await user.should_see(marker=f"task-card-{calm.id}")


async def test_grouping_by_project(user: User):
    sv = await login(user)
    project = sv.projects.create(ProjectIn(name="Jardin", emoji="🌱"))
    sv.tasks.create(TaskCreate(title="Tondre", project_id=project.id))
    sv.tasks.create(TaskCreate(title="Lire"))
    await user.open("/tasks")
    select_value(user, "list-group", "project")
    await user.should_see("Sans projet")
    await user.should_see("Jardin")


async def test_quick_search_opens_editor(user: User):
    sv = await login(user)
    task = sv.tasks.create(TaskCreate(title="Réparer le vélo"))
    sv.tasks.create(TaskCreate(title="Autre chose"))
    await user.open("/")
    user.find(marker="search-button").click()
    user.find(marker="search-input").type("velo").trigger("keydown.enter")  # sans accent
    await user.should_see(marker="task-editor")
    await user.should_see("Réparer le vélo")
    assert task.id


async def test_quick_search_keyboard(user: User):
    sv = await login(user)
    sv.tasks.create(TaskCreate(title="Vélo : pneus", importance=Importance(4)))
    second = sv.tasks.create(TaskCreate(title="Vélo : chaîne", importance=Importance(1)))
    await user.open("/")
    user.find(marker="search-button").click()
    search = user.find(marker="search-input").type("velo")
    search.trigger("keydown.down")
    await user.should_see(marker="search-result-1")
    row = next(iter(user.find(marker="search-result-1").elements))
    assert "search-selected" in row.classes
    search.trigger("keydown.enter")
    await user.should_see(marker="task-editor")
    await user.should_see("Vélo : chaîne")
    assert second.id


async def test_search_page_includes_closed_tasks(user: User):
    sv = await login(user)
    done = sv.tasks.create(TaskCreate(title="Pain acheté", status=Status.DONE))
    other = sv.tasks.create(TaskCreate(title="Fromage"))
    await user.open("/search?q=pain")
    await user.should_see(marker=f"task-card-{done.id}")
    await user.should_not_see(marker=f"task-card-{other.id}")


async def test_duplicate_from_card_menu(user: User):
    sv = await login(user)
    task = sv.tasks.create(TaskCreate(title="Modèle"))
    await user.open("/tasks")
    open_menu(user, f"card-menu-{task.id}")
    user.find(marker=f"card-duplicate-{task.id}").click()
    await user.should_see("Modèle (copie)")
    assert sorted(t.title for t in sv.tasks.list()) == ["Modèle", "Modèle (copie)"]


async def test_settings_create_project_and_tag(user: User):
    sv = await login(user)
    await user.open("/settings?tab=projects")
    user.find(marker="new-project").click()
    with user.scope(marker="project-dialog"):
        fill(user, "Nom", "Vacances")
    user.find(marker="project-save").click()
    assert [p.name for p in sv.projects.list()] == ["Vacances"]
    await user.open("/settings?tab=tags")
    user.find(marker="new-tag").click()
    with user.scope(marker="tag-dialog"):
        fill(user, "Nom", "urgent")
    user.find(marker="tag-save").click()
    assert [t.name for t in sv.tags.list()] == ["urgent"]


async def test_settings_theme_devices_and_users(user: User):
    await login(user)
    await user.open("/settings?tab=appearance")
    select_value(user, "theme-toggle", "dark")
    assert state().users.get(1).theme == "dark"
    await user.open("/settings?tab=devices")
    await user.should_see("Cet appareil")
    await user.open("/settings?tab=users")
    user.find(marker="new-user").click()
    with user.scope(marker="user-dialog"):
        fill(user, "Identifiant de connexion", "bob")
        fill(user, "Mot de passe", "motdepasse-12")
    user.find(marker="user-save").click()
    assert sorted(u.username for u in state().users.list()) == ["alice", "bob"]


async def test_data_tab_download_and_backup_keys(user: User):
    """Onglet 🗄️ Données (admin) : télécharger la sauvegarde avec le cookie, créer / révoquer un jeton."""
    import io
    import tarfile

    sv = await login(user)
    sv.tasks.create(TaskCreate(title="Sauvegardée"))
    await user.open("/settings?tab=data")
    user.find(marker="backup-download").click()
    response = await user.download.next()
    assert response.status_code == 200
    names = tarfile.open(fileobj=io.BytesIO(response.content)).getnames()
    assert names[0] == "organizer.db" and names[-1] == "manifest.json"

    await user.should_see("Aucun jeton pour l'instant.")
    user.find(marker="new-backup-key").click()
    with user.scope(marker="backup-key-dialog"):
        user.find(marker="backup-key-label").clear().type("Borg du Pi")
    user.find(marker="backup-key-create").click()
    await user.should_see(marker="backup-key-token")
    token = user.find(marker="backup-key-token").elements.pop().value
    (key,) = state().auth.list_api_keys()
    await user.should_see(marker=f"backup-key-{key.id}")
    await user.should_see("jamais utilisé")
    assert key.label == "Borg du Pi" and state().auth.resolve_api_key(token, "backup") is not None

    user.find(marker=f"revoke-key-{key.id}").click()
    user.find(marker="revoke-key-confirm").click()
    assert state().auth.list_api_keys() == []
    assert state().auth.resolve_api_key(token, "backup") is None


async def test_data_tab_hidden_from_non_admin(user: User):
    await user.open("/login")
    alice = state().users.create_user("alice", "motdepasse-12", "Alice")
    state().users.create_user("bob", "motdepasse-12", "Bob", by=state().users.actor_for(alice.id))
    await user.open("/login")
    fill(user, "Identifiant", "bob")
    fill(user, "Mot de passe", "motdepasse-12")
    user.find("Se connecter").click()
    await user.should_see("Bonjour Bob")
    await user.open("/settings?tab=data")
    await user.should_see(marker="tab-profile")
    await user.should_not_see(marker="tab-data")
    await user.should_not_see(marker="backup-download")


# --- étape 6 : kanbans, matrice, glisser-déposer ----------------------------------------------------------
# Le geste lui-même (souris, doigt, Ctrl) est testé dans un vrai navigateur ; ici on simule les événements que
# le composant de glisser-déposer envoie au serveur.


def drop(user: User, task_id: int, zone: str, index: int | None = None) -> None:
    user.find(marker="dnd").trigger("drop", {"task": task_id, "zone": zone, "index": index})


async def settle() -> None:
    """Laisse passer le rafraîchissement de la page (``refresh()`` s'exécute en tâche de fond)."""
    await asyncio.sleep(0.05)


async def test_status_board_drop_changes_status(user: User):
    sv = await login(user)
    task = sv.tasks.create(TaskCreate(title="À ranger"))
    await user.open("/kanban?board=status")
    await user.should_see(marker="zone-status:in_progress")
    drop(user, task.id, "status:done")
    assert sv.tasks.get(task.id).status is Status.DONE
    sv.undo.undo()
    assert sv.tasks.get(task.id).status is Status.NOT_STARTED


async def test_reorder_in_column_tunes_urgency(user: User):
    sv = await login(user)
    top = sv.tasks.create(TaskCreate(title="Urgent", urgency=Urgency(4)))
    low = sv.tasks.create(TaskCreate(title="Tranquille", urgency=Urgency(1)))
    await user.open("/kanban?board=status")
    await user.should_see(marker="zone-status:not_started")
    drop(user, low.id, "status:not_started", 0)  # remontée en tête de sa colonne
    assert sv.tasks.get(low.id).urgency == 4 and sv.tasks.get(low.id).status is Status.NOT_STARTED
    # Vers une autre colonne, à une position : statut ET urgence en une seule action.
    sv.tasks.update(top.id, TaskPatch(status=Status.IN_PROGRESS, urgency=Urgency(2)))
    await user.open("/kanban?board=status")
    drop(user, low.id, "status:in_progress", 1)  # sous « Urgent » (urgence 2)
    moved = sv.tasks.get(low.id)
    assert moved.status is Status.IN_PROGRESS and moved.urgency == 2
    sv.undo.undo()
    back = sv.tasks.get(low.id)
    assert back.status is Status.NOT_STARTED and back.urgency == 4


async def test_collapse_and_resize_columns(user: User):
    sv = await login(user)
    sv.tasks.create(TaskCreate(title="Carte"))
    await user.open("/kanban?board=status")
    user.find(marker="collapse-status:done").click()
    await user.should_see(marker="expand-status:done")
    assert sv.users.get_pref(sv.actor.id, "board:status")["collapsed"] == ["status:done"]
    user.find(marker="resizer").trigger("resize", {"key": "status:not_started", "width": 400})
    assert sv.users.get_pref(sv.actor.id, "board:status")["widths"] == {"status:not_started": 400}
    await user.open("/kanban?board=status")  # mémorisé
    await user.should_see(marker="expand-status:done")
    zone = next(iter(user.find(marker="zone-status:not_started").elements))
    assert zone._style.get("width") == "400px"
    user.find(marker="expand-status:done").click()
    await user.should_see(marker="collapse-status:done")
    user.find(marker="resizer").trigger("resize", {"key": "status:not_started", "width": None})
    assert sv.users.get_pref(sv.actor.id, "board:status")["widths"] == {}


async def test_due_and_project_boards(user: User):
    from datetime import date, timedelta

    sv = await login(user)
    project = sv.projects.create(ProjectIn(name="Jardin"))
    task = sv.tasks.create(TaskCreate(title="Tondre"))
    await user.open("/kanban?board=due")
    drop(user, task.id, "due:tomorrow")
    assert sv.tasks.get(task.id).due_date == date.today() + timedelta(days=1)
    await settle()
    drop(user, task.id, "due:overdue")  # refusé : l'échéance ne change pas
    assert sv.tasks.get(task.id).due_date == date.today() + timedelta(days=1)
    await user.open("/kanban?board=project")
    drop(user, task.id, f"project:{project.id}")
    assert sv.tasks.get(task.id).project.name == "Jardin"
    await settle()
    drop(user, task.id, "project:0")
    assert sv.tasks.get(task.id).project is None


async def test_ctrl_drop_attaches_subtask(user: User):
    sv = await login(user)
    parent = sv.tasks.create(TaskCreate(title="Parent"))
    child = sv.tasks.create(TaskCreate(title="Enfant"))
    await user.open("/tasks")
    user.find(marker="dnd").trigger("attach", {"task": child.id, "parent": parent.id})
    assert sv.tasks.get(child.id).parent_id == parent.id
    await user.should_see("sous-tâche de")


async def test_custom_board_from_ui(user: User):
    sv = await login(user)
    task = sv.tasks.create(TaskCreate(title="Peindre"))
    await user.open("/kanban")
    user.find(marker="new-board").click()
    with user.scope(marker="board-dialog"):
        fill(user, "Nom", "Rénovation")
    user.find(marker="board-save").click()
    await user.should_see(marker="board-add-tasks")
    board = sv.boards.list()[0]
    todo, doing, _ = (c.id for c in board.columns)
    drop(user, task.id, f"col:{todo}")
    drop(user, task.id, f"col:{doing}", 0)
    content = sv.boards.content(board.id)
    assert [t.title for t in content.columns[doing]] == ["Peindre"]


async def test_matrix_drop_quadrant_and_cell(user: User):
    sv = await login(user)
    task = sv.tasks.create(TaskCreate(title="Classer", importance=1, urgency=1))
    await user.open("/matrix")
    await user.should_see(marker="zone-q:do")
    drop(user, task.id, "q:do")
    t = sv.tasks.get(task.id)
    assert (t.importance, t.urgency) == (3, 3)
    select_value(user, "matrix-mode", "4x4")
    await user.should_see(marker="zone-cell:4:2")
    drop(user, task.id, "cell:4:2")
    t = sv.tasks.get(task.id)
    assert (t.importance, t.urgency) == (4, 2)


# --- temps réel ---------------------------------------------------------------------------------------------


async def test_page_follows_changes_made_elsewhere(user: User):
    sv = await login(user)
    elsewhere = state().services_for(state().users.get(sv.actor.id), origin="autre-appareil")
    await user.open("/tasks")
    elsewhere.tasks.create(TaskCreate(title="Ajoutée sur le téléphone"))
    await asyncio.sleep(0.6)
    await user.should_see("Ajoutée sur le téléphone")

    # Pendant un glisser-déposer, la page attend la fin du geste.
    user.find(marker="dnd").trigger("dragstate", {"active": True})
    elsewhere.tasks.create(TaskCreate(title="Pendant le glisser"))
    await asyncio.sleep(0.6)
    await user.should_not_see("Pendant le glisser")
    user.find(marker="dnd").trigger("dragstate", {"active": False})
    await asyncio.sleep(0.6)
    await user.should_see("Pendant le glisser")


async def test_attach_from_card_menu(user: User):
    sv = await login(user)
    parent = sv.tasks.create(TaskCreate(title="Grand ménage"))
    child = sv.tasks.create(TaskCreate(title="Vitres"))
    await user.open("/tasks")
    await user.should_see(marker=f"task-card-{child.id}")
    open_menu(user, f"card-menu-{child.id}")
    user.find(marker=f"card-attach-{child.id}").click()
    await user.should_see(marker="attach-dialog")
    await user.should_see(marker=f"attach-to-{parent.id}")
    await user.should_not_see(marker=f"attach-to-{child.id}")  # pas elle-même
    user.find(marker=f"attach-to-{parent.id}").click()
    await user.should_see("sous-tâche de")
    assert sv.tasks.get(child.id).parent_id == parent.id


async def test_matrix_default_filter_is_not_counted(user: User):
    await login(user)
    await user.open("/matrix")
    await user.should_see("🎛️ Filtres")
    await user.should_not_see("🎛️ Filtres (1)")


def test_local_path_from_file_uri():
    from pathlib import Path

    from organizer.ui.components.file_drop import local_path

    assert local_path("file:///home/alice/devis%20sign%C3%A9.pdf") == Path("/home/alice/devis signé.pdf")
    assert local_path("file:///C:/Users/Alice/a.txt") == Path("C:/Users/Alice/a.txt")
