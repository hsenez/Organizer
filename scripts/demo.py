"""Démonstration du cœur métier dans le terminal (en attendant l'interface).

    .venv/bin/python scripts/demo.py       # déroule un scénario commenté
    .venv/bin/python -i scripts/demo.py    # idem, puis console Python pour jouer soi-même

Utilise une base séparée, ``data/demo.db``, recréée à chaque lancement (tes vraies données ne sont pas
touchées).
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from organizer.config import PROJECT_ROOT, Settings
from organizer.core import rules
from organizer.core.db import init_db, make_engine
from organizer.core.enums import (
    DueBucket,
    Importance,
    LinkKind,
    Quadrant,
    Status,
    TaskKind,
    Urgency,
)
from organizer.core.errors import OrganizerError
from organizer.core.schemas import (
    LinkIn,
    ProjectIn,
    TagIn,
    TaskCreate,
    TaskFilter,
    TaskOut,
    TaskPatch,
    TaskSort,
)
from organizer.core.services import Services, UserService

TODAY = date.today()


# --- Affichage ----------------------------------------------------------------------------------------------


def card(t: TaskOut) -> str:
    """Une « carte » sur une ligne : importance, urgence, statut, type, titre, échéance, projet, tags…"""
    parts = [
        t.importance.meta.emoji,
        t.urgency.meta.emoji,
        t.status.meta.emoji,
        t.kind.meta.emoji,
        f"{'↳ ' if t.is_subtask else ''}{t.title}",
    ]
    if t.due_date:
        bucket = rules.due_bucket(t.due_date, TODAY)
        flag = {DueBucket.OVERDUE: "🔴", DueBucket.TODAY: "🟠", DueBucket.TOMORROW: "🟡"}.get(bucket, "")
        parts.append(f"📅{flag} {t.due_date:%d/%m}")
    if t.reminder_date:
        parts.append(f"🔔 {t.reminder_date:%d/%m}")
    if t.project:
        parts.append(f"{t.project.emoji} {t.project.name}")
    if t.tags:
        parts.append("🏷️ " + ", ".join(tag.name for tag in t.tags))
    if t.subtask_total:
        bar = "▰" * t.subtask_done + "▱" * (t.subtask_total - t.subtask_done)
        parts.append(f"{bar} {t.subtask_done}/{t.subtask_total}")
    if t.due_after_parent:
        parts.append("⚠️ après le parent")
    if t.notes:
        parts.append("📝")
    if t.links:
        parts.append(f"🔗{len(t.links)}")
    if t.shared_with:
        parts.append("👥")
    return "  ".join(parts)


def title(text: str) -> None:
    print(f"\n\033[1;36m━━━ {text} {'━' * max(0, 70 - len(text))}\033[0m")


def show(tasks: list[TaskOut], indent: str = "  ") -> None:
    if not tasks:
        print(f"{indent}(rien)")
    for t in tasks:
        print(indent + card(t))


def show_list(sv: Services, **filters) -> None:
    show(sv.tasks.list(TaskFilter(**filters), TaskSort(key="priority")))


def show_kanban_status(sv: Services) -> None:
    tasks = sv.tasks.list(sort=TaskSort(key="priority"))
    for status in Status:
        column = [t for t in tasks if t.status is status]
        print(f"  {status.meta.text} ({len(column)})")
        show(column, indent="      ")


def show_matrix(sv: Services) -> None:
    tasks = [t for t in sv.tasks.list(sort=TaskSort(key="priority")) if not t.status.is_closed]
    for quadrant in Quadrant:
        column = [t for t in tasks if rules.quadrant_of(t.importance, t.urgency) is quadrant]
        print(f"  {quadrant.meta.text} — {quadrant.meta.tooltip}")
        show(column, indent="      ")


def show_due_board(sv: Services) -> None:
    tasks = sv.tasks.list(sort=TaskSort(key="due"))
    for bucket in DueBucket:
        column = [t for t in tasks if rules.due_bucket(t.due_date, TODAY) is bucket]
        print(f"  {bucket.meta.text}")
        show(column, indent="      ")


def legend() -> None:
    title("Légende")
    for enum, name in (
        (Importance, "Importance"),
        (Urgency, "Urgence"),
        (Status, "Statut"),
        (TaskKind, "Type"),
    ):
        print(f"  {name:<11}" + "   ".join(m.meta.text for m in enum))


# --- Scénario -----------------------------------------------------------------------------------------------


def build() -> tuple[Services, Services]:
    db = PROJECT_ROOT / "data" / "demo.db"
    for suffix in ("", "-wal", "-shm"):
        Path(f"{db}{suffix}").unlink(missing_ok=True)
    engine = make_engine(db)
    init_db(engine)
    settings = Settings(undo_merge_window_seconds=0)
    users = UserService(engine)
    a = users.create_user("alice", "motdepasse-12", "Alice")
    b = users.create_user("bob", "motdepasse-12", "Bob", by=users.actor_for(a.id))
    return Services.for_user(engine, a.id, settings=settings), Services.for_user(
        engine, b.id, settings=settings
    )


def scenario(alice: Services, bob: Services) -> None:
    d = timedelta
    maison = alice.projects.create(ProjectIn(name="Maison", emoji="🏠", is_public=True))
    boulot = alice.projects.create(ProjectIn(name="Boulot", emoji="💼"))
    client = alice.tags.create(TagIn(name="client", color="#fa5252", is_public=True))
    perso = alice.tags.create(TagIn(name="perso"))

    facture = alice.tasks.create(
        TaskCreate(
            title="Payer la facture d'électricité",
            importance=Importance.CRITICAL,
            urgency=Urgency.IMMEDIATE,
            due_date=TODAY - d(days=1),
            project_id=maison.id,
        )
    )
    devis = alice.tasks.create(
        TaskCreate(
            title="Envoyer le devis",
            importance=Importance.IMPORTANT,
            urgency=Urgency.PRESSING,
            due_date=TODAY,
            project_id=boulot.id,
            tag_ids=[client.id],
            status=Status.IN_PROGRESS,
            notes="## Contenu\n1. Prestations\n2. Délais\n- [ ] relire",
        )
    )
    alice.tasks.add_link(devis.id, LinkIn(kind=LinkKind.URL, target="https://example.org/devis"))
    alice.tasks.add_link(devis.id, LinkIn(kind=LinkKind.PATH, target="/home/alice/devis.odt"))
    cuisine = alice.tasks.create(
        TaskCreate(title="Refaire la cuisine", importance=Importance.IMPORTANT, due_date=TODAY + d(days=30))
    )
    for name, extra in (
        ("Choisir le carrelage", {"status": Status.DONE}),
        ("Demander 3 devis", {}),
        ("Acheter la peinture", {"due_date": TODAY + d(days=40)}),
        ("Poser une étagère", {"status": Status.CANCELLED}),
    ):
        alice.tasks.create(TaskCreate(title=name, parent_id=cuisine.id, **extra))
    alice.tasks.create(
        TaskCreate(
            title="Suivre la livraison du colis",
            kind=TaskKind.FOLLOWUP,
            due_date=TODAY + d(days=2),
            tag_ids=[perso.id],
        )
    )
    alice.tasks.create(
        TaskCreate(
            title="Relancer le plombier",
            kind=TaskKind.FOLLOWUP,
            due_date=TODAY + d(days=10),
            urgency=Urgency.WHENEVER,
            project_id=maison.id,
        )
    )
    alice.tasks.create(
        TaskCreate(title="Lire « Le Petit Prince »", importance=Importance.MINOR, urgency=Urgency.WHENEVER)
    )
    alice.tasks.create(TaskCreate(title="Ranger le garage", urgency=Urgency.PRESSING, status=Status.PAUSED))

    legend()

    title("📋 Liste d'Alice (triée par priorité, sous-tâches masquées)")
    show_list(alice)

    title("🌳 Avec les sous-tâches")
    show_list(alice, include_subtasks=True)

    title("📊 Kanban par statut")
    show_kanban_status(alice)

    title("🎯 Matrice d'Eisenhower")
    show_matrix(alice)

    title("📅 Board par échéance")
    show_due_board(alice)

    title("🔍 Recherche « electricite » (sans accent) puis « client » (tag)")
    show_list(alice, text="electricite")
    show_list(alice, text="client")

    title("🔔 Rappels de suivi atteints aujourd'hui")
    show(alice.tasks.reminders_due())

    title("🌳 Ctrl+drop : « Ranger le garage » déposé sur « Refaire la cuisine »")
    garage = next(t for t in alice.tasks.list() if t.title == "Ranger le garage")
    alice.tasks.attach(garage.id, cuisine.id)
    show(alice.tasks.subtasks(cuisine.id))
    print("  Tentative : déposer « Refaire la cuisine » sur « Payer la facture »…")
    try:
        alice.tasks.attach(cuisine.id, facture.id)
    except OrganizerError as exc:
        print(f"  🔴 Refusé : {exc.message}")

    title("👥 Partage : Bob avant / après qu'Alice lui partage « Refaire la cuisine »")
    print("  Avant :")
    show(bob.tasks.list(TaskFilter(include_subtasks=True)), indent="      ")
    alice.tasks.set_shares(cuisine.id, [bob.actor.id])
    print("  Après :")
    show(bob.tasks.list(TaskFilter(include_subtasks=True)), indent="      ")
    print(f"  Projets visibles par Bob : {[p.name for p in bob.projects.list()]}  (« Boulot » est privé)")

    title("↩️ Ctrl+Z : Alice supprime « Refaire la cuisine » et ses sous-tâches, puis annule")
    alice.tasks.delete(cuisine.id, with_subtasks=True)
    print("  Après suppression :")
    show_list(alice, include_subtasks=True)
    result = alice.undo.undo()
    print(f"  ↩️ Annulé : {result.label}")
    show_list(alice, include_subtasks=True)
    print(f"  Prochain Ctrl+Z annulerait : {alice.undo.status().undo_label}")

    title("⚔️ Conflit : Alice renomme, Bob renomme ensuite, Alice tente Ctrl+Z")
    alice.tasks.update(cuisine.id, TaskPatch(title="Rénover la cuisine"))
    bob.tasks.update(cuisine.id, TaskPatch(title="Cuisine (version Bob)"))
    try:
        alice.undo.undo()
    except OrganizerError as exc:
        print(f"  🔴 {exc.message}")
    print(f"  Titre actuel : {alice.tasks.get(cuisine.id).title}")


HELP = """
\033[1mConsole interactive\033[0m — objets disponibles :
  alice, bob                  services de chaque utilisateur
  show_list(alice)            liste (filtres : text="…", include_subtasks=True, status=[Status.DONE]…)
  show_kanban_status(alice)   show_matrix(alice)   show_due_board(alice)
  alice.tasks.create(TaskCreate(title="…", importance=Importance.CRITICAL, due_date=TODAY))
  alice.tasks.update(id, TaskPatch(status=Status.DONE))
  alice.undo.undo()   alice.undo.redo()   alice.undo.status()
  Importance, Urgency, Status, TaskKind, TaskCreate, TaskPatch, TaskFilter, ProjectIn, TagIn, TODAY
"""

if __name__ == "__main__":
    alice, bob = build()
    scenario(alice, bob)
    if sys.flags.interactive:
        print(HELP)
