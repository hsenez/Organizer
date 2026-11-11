"""Page 📝 Notes (simulateur NiceGUI) : créer, écrire, épingler, supprimer, lecture seule, liens internes
(ouverture, recherche « [[ », liens retour), mises à jour venues d'ailleurs, liste d'emojis des réglages."""

from __future__ import annotations

import asyncio

from nicegui.testing import User

from organizer.core.enums import DEFAULT_EMOJIS, EMOJIS_PREF
from organizer.core.schemas import NoteCreate, NotePatch, ShareSpec, TaskCreate
from tests.test_pages import data_dir, login, state  # noqa: F401  (data_dir : fixture automatique)


def element(user: User, marker: str):
    return next(iter(user.find(marker=marker).elements))


def write_text(user: User, text: str) -> None:
    """Comme une frappe dans l'éditeur markdown (le simulateur ne peut pas taper dedans)."""
    with user.client:
        element(user, "note-text").value = text
    user.find(marker="note-text").trigger("blur")


async def test_create_write_title_and_list(user: User):
    sv = await login(user)
    await user.open("/notes")
    await user.should_see("Choisissez une note")
    user.find(marker="notes-new").click()
    await user.should_see(marker="note-text")
    [note] = sv.notes.list()
    assert note.title == "Sans titre"
    title = user.find(marker="note-title")
    with user.client:
        element(user, "note-title").value = "Courses"
    title.trigger("blur")
    write_text(user, "- [ ] lait\n- [ ] pain")
    again = sv.notes.get(note.id)
    assert (again.title, again.notes) == ("Courses", "- [ ] lait\n- [ ] pain")
    await user.should_see(marker=f"note-row-{note.id}")
    await user.should_see("lait")  # extrait dans la liste
    # Barre de boutons et tri des cases actifs dans une note modifiable.
    await user.should_see(marker="md-tool-task")
    assert element(user, "note-text")._props["sort-checks"] is True


async def test_open_by_url_pin_search_and_delete(user: User):
    sv = await login(user)
    first = sv.notes.create(NoteCreate(title="Recettes", notes="Tarte aux pommes"))
    second = sv.notes.create(NoteCreate(title="Vacances"))
    await user.open(f"/notes?note={first.id}")
    await user.should_see(marker="note-pin")
    user.find(marker="note-pin").click()
    assert sv.notes.get(first.id).pinned
    user.find(marker="notes-search").type("pomme").trigger("update:model-value")
    await asyncio.sleep(0.4)
    await user.should_see(marker=f"note-row-{first.id}")
    await user.should_not_see(marker=f"note-row-{second.id}")
    user.find(marker="note-delete").click()
    await user.should_see("supprimée")
    assert [n.id for n in sv.notes.list()] == [second.id]
    await user.should_see("Choisissez une note")


async def test_read_only_note_for_viewers(user: User):
    bob = await login(user, "bob")
    alice = state().services_for(state().users.create_user("alice", "motdepasse-12", "Alice", by=bob.actor))
    note = alice.notes.create(NoteCreate(title="Règlement", notes="- [ ] lire"))
    alice.notes.set_shares(note.id, [ShareSpec(user_id=bob.actor.id, can_edit=False)])
    await user.open(f"/notes?note={note.id}")
    await user.should_see(marker="note-read-only")
    await user.should_see("Règlement")
    await user.should_not_see(marker="md-tool-bold")
    await user.should_not_see(marker="note-delete")
    await user.should_not_see(marker="note-sharing")
    assert element(user, "note-text")._props["readonly"] is True
    await user.should_see("👤 Appartient à Alice")


async def test_sharing_section_for_owner(user: User):
    sv = await login(user)
    bob = state().users.create_user("bob", "motdepasse-12", "Bob", by=sv.actor)
    note = sv.notes.create(NoteCreate(title="Commune"))
    await user.open(f"/notes?note={note.id}")
    await user.should_see(marker="note-sharing")
    with user.client:
        element(user, "editor-shares").set_value([bob.id])
    assert [s.user_id for s in sv.notes.get(note.id).shares] == [bob.id]
    with user.client:
        element(user, "note-public").set_value(True)
    assert sv.notes.get(note.id).is_public


async def test_internal_links_open_resolve_and_backlinks(user: User):
    sv = await login(user)
    task = sv.tasks.create(TaskCreate(title="Acheter du pain"))
    target = sv.notes.create(NoteCreate(title="Recettes", emoji="🍳"))
    note = sv.notes.create(
        NoteCreate(title="Menu", notes=f"- [ ] [pain](task:{task.id})\n- voir [](note:{target.id})")
    )
    await user.open(f"/notes?note={note.id}")
    await user.should_see(marker="note-text")
    refs = element(user, "note-text")._props["refs"]
    assert refs[f"note:{target.id}"] == {"title": "Recettes", "emoji": "🍳", "available": True}
    assert refs[f"task:{task.id}"]["title"] == "Acheter du pain"
    # Lien vers une tâche : son éditeur s'ouvre par-dessus la note.
    user.find(marker="note-text").trigger("open-link", {"target": f"task:{task.id}", "kind": "ref"})
    await user.should_see(marker="editor-title")
    # Lien vers une note : elle s'ouvre dans la page, avec « Cité dans » la note de départ.
    user.find(marker="note-text").trigger("open-link", {"target": f"note:{target.id}", "kind": "ref"})
    await user.should_see(marker=f"backlink-note-{note.id}")
    user.find(marker=f"backlink-note-{note.id}").click()
    await asyncio.sleep(0.05)
    assert element(user, "note-text").value.startswith("- [ ] [pain]")  # retour sur « Menu »


async def test_ref_picker_inserts_a_link(user: User, monkeypatch):
    from organizer.ui.components.markdown_editor import MarkdownEditor

    inserted = []
    monkeypatch.setattr(MarkdownEditor, "insert_ref", lambda self, text: inserted.append(text))
    sv = await login(user)
    task = sv.tasks.create(TaskCreate(title="Réserver [le] camion"))
    note = sv.notes.create(NoteCreate(title="Déménagement"))
    await user.open(f"/notes?note={note.id}")
    user.find(marker="note-text").trigger("ref-request")  # « [[ » tapé
    await user.should_see(marker="ref-picker")
    user.find(marker="ref-picker-input").type("camion").trigger("update:model-value")
    await asyncio.sleep(0.4)
    await user.should_see(marker=f"ref-pick-task-{task.id}")
    await user.should_not_see(marker=f"ref-pick-note-{note.id}")  # pas la note elle-même
    user.find(marker=f"ref-pick-task-{task.id}").click()
    assert inserted == [f"[Réserver (le) camion](task:{task.id})"]


async def test_task_editor_notes_open_internal_links(user: User):
    sv = await login(user)
    target = sv.notes.create(NoteCreate(title="Plan"))
    task = sv.tasks.create(TaskCreate(title="Préparer", notes=f"Voir [le plan](note:{target.id})"))
    await user.open(f"/tasks?task={task.id}")
    assert element(user, "editor-notes")._props["refs"][f"note:{target.id}"]["title"] == "Plan"
    user.find(marker="editor-notes").trigger("open-link", {"target": f"note:{target.id}", "kind": "ref"})
    await user.should_see(marker="note-text")  # page Notes, sur la note citée
    await user.should_see(marker=f"backlink-task-{task.id}")


async def test_note_follows_changes_made_elsewhere(user: User):
    sv = await login(user)
    note = sv.notes.create(NoteCreate(title="Partagée", notes="avant"))
    elsewhere = state().services_for(state().users.get(sv.actor.id), origin="autre-appareil")
    await user.open(f"/notes?note={note.id}")
    await user.should_see(marker="note-text")
    elsewhere.notes.update(note.id, NotePatch(notes="après"))
    await asyncio.sleep(0.6)
    assert element(user, "note-text").value == "après"  # on ne tapait pas : mise à jour
    # Pendant la frappe : bandeau au lieu de remplacer le texte.
    user.find(marker="note-text").trigger("update:value", "je tape")  # comme envoyé par l'éditeur
    elsewhere.notes.update(note.id, NotePatch(notes="encore ailleurs"))
    await asyncio.sleep(0.6)
    await user.should_see("modifiée ailleurs")
    assert element(user, "note-text").value == "je tape"


async def test_settings_emoji_list(user: User):
    sv = await login(user)
    await user.open("/settings?tab=appearance")
    field = user.find(marker="emojis-input")
    with user.client:
        element(user, "emojis-input").value = "🐱  🐶 🐱"
    field.trigger("blur")
    user.find(marker="emojis-save").click()
    assert state().users.get_pref(sv.actor.id, EMOJIS_PREF) == ["🐱", "🐶"]
    user.find(marker="emojis-reset").click()
    assert state().users.get_pref(sv.actor.id, EMOJIS_PREF) == list(DEFAULT_EMOJIS)
    # La liste personnelle est proposée pour l'emoji d'une note.
    state().users.set_pref(sv.actor.id, EMOJIS_PREF, ["🦊"])
    note = sv.notes.create(NoteCreate(title="Animaux"))
    await user.open(f"/notes?note={note.id}")
    await user.should_see(marker="emoji-🦊")
    user.find(marker="emoji-🦊").click()
    assert sv.notes.get(note.id).emoji == "🦊"


async def test_notification_opens_the_note(user: User):
    bob = await login(user, "bob")
    alice = state().services_for(state().users.create_user("alice", "motdepasse-12", "Alice", by=bob.actor))
    note = alice.notes.create(NoteCreate(title="Idées"))
    alice.notes.set_shares(note.id, [ShareSpec(user_id=bob.actor.id)])
    [notification] = bob.notifications.list()
    await user.open("/notifications")
    user.find(marker=f"notification-{notification.id}").click()
    await user.should_see(marker="note-text")
    await user.should_see("Idées")


async def test_quick_search_finds_notes(user: User):
    sv = await login(user)
    note = sv.notes.create(NoteCreate(title="Recette du gâteau"))
    sv.tasks.create(TaskCreate(title="Acheter un gâteau"))
    await user.open("/")
    user.find(marker="search-button").click()
    user.find(marker="search-input").type("gateau").trigger("keydown.enter")  # le premier : la note
    await user.should_see(marker="note-text")
    await user.should_see("Recette du gâteau")
    assert note.id


async def test_copy_link_buttons_and_organizer_urls_in_notes(user: User):
    sv = await login(user)
    task = sv.tasks.create(TaskCreate(title="Plombier"))
    note = sv.notes.create(NoteCreate(title="Travaux"))
    await user.open(f"/tasks?task={task.id}")
    await user.should_see(marker="editor-copy-link")  # aussi pour les tâches (et les événements)
    await user.open(f"/notes?note={note.id}")
    await user.should_see(marker="note-copy-link")
    # Une adresse d'Organizer cliquée dans une note ouvre l'élément dans l'application.
    url = f"https://organizer.exemple.fr/open/task/{task.id}"
    user.find(marker="note-text").trigger("open-link", {"target": url, "kind": "url"})
    await user.should_see(marker="editor-title")


async def test_settings_public_url(user: User):
    sv = await login(user)
    await user.open("/settings?tab=data")
    with user.client:
        element(user, "public-url").value = "organizer.exemple.fr"
    user.find(marker="public-url-save").click()
    await user.should_see("Adresse publique enregistrée")
    assert state().users.get_setting("public_url") == "https://organizer.exemple.fr"
    assert sv.actor.is_admin


async def test_fab_menu_creates_a_note_here_or_on_the_notes_page(user: User):
    sv = await login(user)
    await user.open("/")
    user.find(marker="fab-new-note").click()  # ailleurs : on va sur la page Notes, note créée
    await user.should_see(marker="note-text")
    [note] = sv.notes.list()
    assert note.title == "Sans titre"
    user.find(marker="fab-new-note").click()  # dans la page Notes : créée sur place
    await user.should_see(marker="note-title")
    assert len(sv.notes.list()) == 2


async def test_fab_menu_opens_an_event_draft(user: User):
    sv = await login(user)
    await user.open("/tasks")
    user.find(marker="fab-new-event").click()
    await user.should_see("✨ Nouvel événement")
    assert sv.agenda.list() == []


async def test_phone_writing_zone_and_details_toggle(user: User):
    sv = await login(user)
    note = sv.notes.create(NoteCreate(title="Courses", notes="- [ ] lait"))
    await user.open(f"/notes?note={note.id}")
    await user.should_see(marker="note-text")
    # Texte + barre : zone du mode écriture (viewport.js), uniquement pour une note modifiable.
    zone = element(user, "note-text").parent_slot.parent
    assert "writing-zone" in zone.classes and "data-writing" in zone.props
    # Téléphone : projet, tags et partage repliés derrière un bouton (CSS), qui les déplie.
    details = next(e for e in user.client.layout.descendants() if "note-details" in e.classes)
    assert "note-details-open" not in details.classes
    user.find(marker="note-details-toggle").click()
    assert "note-details-open" in details.classes
    # Viewport : la page rapetisse avec le clavier (Chrome Android).
    assert "interactive-widget=resizes-content" in user.client.page.resolve_viewport()
