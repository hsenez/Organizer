"""⚙️ Réglages : profil, apparence, rappels, projets, tags, appareils connectés, utilisateurs et données
(admin).

Onglet initial choisi par ``?tab=`` (profile, appearance, reminders, projects, tags, devices, users, data, et
sur le client bureau connection).
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import Response
from nicegui import run, ui
from pydantic import ValidationError

from organizer.core import rules
from organizer.core.enums import DEFAULT_EMOJIS, EMOJIS_PREF
from organizer.core.errors import OrganizerError
from organizer.core.schemas import (
    AdminUserPatch,
    PasswordChange,
    ProfilePatch,
    ProjectIn,
    ProjectPatch,
    TagIn,
    TagPatch,
    UserCreateIn,
)
from organizer.core.services.users import MIN_PASSWORD_LENGTH
from organizer.ui import format as fmt
from organizer.ui.components.emoji_picker import emoji_choices, emoji_grid
from organizer.ui.context import UiContext
from organizer.ui.layout import THEMES, app_frame, empty_state

TABS = {
    "profile": "👤 Profil",
    "appearance": "🎨 Apparence",
    "reminders": "🔔 Rappels",
    "projects": "📁 Projets",
    "tags": "🏷️ Tags",
    "devices": "💻 Appareils",
    "users": "👥 Utilisateurs",
    "data": "🗄️ Données",
}
ADMIN_TABS = {"users", "data"}


def page(make_context):
    def settings_page(request: Request):
        ctx = make_context(request)
        if isinstance(ctx, Response):
            return ctx
        with app_frame(ctx, "/settings", "Réglages"):
            with ui.row().classes("items-center gap-2"):
                ui.label("⚙️").classes("text-2xl")
                ui.label("Réglages").classes("text-2xl font-bold")
            tabs_shown = {k: v for k, v in TABS.items() if k not in ADMIN_TABS or ctx.user.is_admin}
            tabs_shown |= {key: label for key, (label, _) in ctx.extra_settings.items()}
            initial = request.query_params.get("tab")
            initial = initial if initial in tabs_shown else "profile"
            with (
                ui.tabs(value=initial)
                .props("inline-label outside-arrows mobile-arrows no-caps align=left")
                .classes("w-full") as tabs
            ):
                for key, label in tabs_shown.items():
                    ui.tab(key, label=label).mark(f"tab-{key}")
            with ui.tab_panels(tabs, value=initial).classes("w-full bg-transparent").props("animated=false"):
                builders = {
                    "profile": _profile,
                    "appearance": _appearance,
                    "reminders": _reminders,
                    "projects": _projects,
                    "tags": _tags,
                    "devices": _devices,
                    "users": _users,
                    "data": _data,
                    **{key: build for key, (_, build) in ctx.extra_settings.items()},
                }
                for key in tabs_shown:
                    with ui.tab_panel(key).classes("p-0 pt-2"):
                        builders[key](ctx)
        return None

    return settings_page


# ======================================================================================================
# Outils
# ======================================================================================================


def _card(title: str, subtitle: str | None = None) -> ui.card:
    card = ui.card().classes("w-full max-w-3xl rounded-xl gap-3 p-5")
    with card:
        ui.label(title).classes("text-lg font-semibold")
        if subtitle:
            ui.label(subtitle).classes("text-sm text-gray-500 -mt-2")
    return card


def _try(action, success: str | None = None) -> bool:
    """Exécute ``action`` ; une erreur (métier ou champ invalide) est affichée au lieu de planter."""
    try:
        action()
    except OrganizerError as exc:
        ui.notify(exc.message, type="negative", position="top")
        return False
    except ValidationError as exc:
        fields = ", ".join(str(err["loc"][-1]) for err in exc.errors())
        ui.notify(f"Champ manquant ou invalide : {fields}", type="negative", position="top")
        return False
    if success:
        ui.notify(success, type="positive", position="top")
    return True


def _set_user(ctx: UiContext, user) -> None:
    ctx.ds.user = user


# ======================================================================================================
# Profil, apparence, rappels
# ======================================================================================================


def _profile(ctx: UiContext) -> None:
    user = ctx.user
    with _card(
        "👤 Profil",
        f"Identifiant de connexion : {user.username}{' · 👑 administrateur' if user.is_admin else ''}",
    ):
        name = (
            ui.input("Nom affiché", value=user.display_name)
            .props("outlined dense")
            .classes("w-full max-w-md")
        )

        def save_name() -> None:
            def action():
                _set_user(ctx, ctx.ds.account.update_profile(ProfilePatch(display_name=name.value)))

            _try(action, "✔ Nom enregistré")

        ui.button("Enregistrer", on_click=save_name).props("unelevated no-caps").mark("save-name")

    with _card("🔑 Mot de passe", "Changer le mot de passe déconnecte vos autres appareils."):
        old = (
            ui.input("Mot de passe actuel", password=True).props("outlined dense").classes("w-full max-w-md")
        )
        new = (
            ui.input(
                f"Nouveau mot de passe ({MIN_PASSWORD_LENGTH} caractères min.)",
                password=True,
                password_toggle_button=True,
            )
            .props("outlined dense")
            .classes("w-full max-w-md")
        )
        confirm = ui.input("Confirmer", password=True).props("outlined dense").classes("w-full max-w-md")

        def change() -> None:
            if new.value != confirm.value:
                ui.notify(
                    "Les deux nouveaux mots de passe ne correspondent pas.", type="negative", position="top"
                )
                return
            change = PasswordChange(old_password=old.value or "", new_password=new.value or "")
            if _try(lambda: ctx.ds.account.change_password(change), "🔑 Mot de passe changé"):
                for field in (old, new, confirm):
                    field.set_value("")
                banner = ctx.banner_rows.pop("password-banner", None)  # « mot de passe trop court »
                if banner is not None:
                    banner.delete()

        ui.button("Changer le mot de passe", on_click=change).props("unelevated no-caps").mark(
            "change-password"
        )


def _appearance(ctx: UiContext) -> None:
    with _card("🎨 Apparence", "Le thème est mémorisé pour votre compte, sur tous vos appareils."):

        def changed(e) -> None:
            def action():
                _set_user(ctx, ctx.ds.account.update_profile(ProfilePatch(theme=e.value)))

            if _try(action):
                ctx.dark.set_value(THEMES[e.value])

        ui.toggle(
            {"auto": "🖥️ Comme le système", "light": "☀️ Clair", "dark": "🌙 Sombre"},
            value=ctx.user.theme,
            on_change=changed,
        ).props("no-caps unelevated").mark("theme-toggle")
    _emojis(ctx)


def _emojis(ctx: UiContext) -> None:
    with _card(
        "😀 Emojis proposés",
        "Ceux du choix d'emoji des notes et des projets (séparés par des espaces). Liste personnelle.",
    ):
        field = (
            ui.textarea(value=" ".join(emoji_choices(ctx)))
            .props("outlined autogrow")
            .classes("w-full text-xl")
            .mark("emojis-input")
        )

        def save(values) -> None:
            emojis = rules.parse_emojis(values)
            if _try(lambda: ctx.ds.account.set_pref(EMOJIS_PREF, emojis), "✔ Emojis enregistrés"):
                field.set_value(" ".join(emojis or DEFAULT_EMOJIS))

        with ui.row().classes("gap-2"):
            ui.button("💾 Enregistrer", on_click=lambda: save(field.value or "")).props("no-caps").mark(
                "emojis-save"
            )
            ui.button("↺ Liste par défaut", on_click=lambda: save(list(DEFAULT_EMOJIS))).props(
                "flat no-caps"
            ).mark("emojis-reset")


def _reminders(ctx: UiContext) -> None:
    with _card(
        "🔔 Rappels des suivis", "Pour une tâche de type 👁️ Suivi, le rappel tombe N jours avant l'échéance."
    ):

        def offset_changed(e) -> None:
            if e.value is None:
                return

            def action():
                _set_user(ctx, ctx.ds.account.update_profile(ProfilePatch(reminder_offset_days=int(e.value))))

            _try(action, "✔ Enregistré (pour les prochains suivis)")

        ui.number(
            "Décalage par défaut (jours avant l'échéance)",
            value=ctx.user.reminder_offset_days,
            min=0,
            max=365,
            step=1,
            precision=0,
            on_change=offset_changed,
        ).props("outlined dense debounce=600").classes("w-full max-w-md")

        def notifications_changed(e) -> None:
            def action():
                _set_user(
                    ctx, ctx.ds.account.update_profile(ProfilePatch(desktop_notifications=bool(e.value)))
                )

            _try(action)

        ui.switch(
            "Notifications système sur le client bureau",
            value=ctx.user.desktop_notifications,
            on_change=notifications_changed,
        )
        ui.label(
            "Le client bureau affiche une notification quand la date de rappel d'un suivi est atteinte "
            "(une fois par jour et par tâche)."
        ).classes("text-xs text-gray-500")


# ======================================================================================================
# Projets et tags
# ======================================================================================================


def _visibility_badge(is_public: bool) -> None:
    ui.label("🌍 Public" if is_public else "🔒 Privé").classes("chip").tooltip(
        "Visible et utilisable par tous" if is_public else "Visible uniquement par vous"
    )


def _reorder(ids: list[int], index: int, delta: int) -> list[int]:
    target = index + delta
    if not 0 <= target < len(ids):
        return ids
    ids = list(ids)
    ids[index], ids[target] = ids[target], ids[index]
    return ids


def _projects(ctx: UiContext) -> None:
    state = {"archived": False}

    @ui.refreshable
    def body() -> None:
        projects = ctx.ds.projects.list(include_archived=state["archived"])
        if not projects:
            empty_state("📁", "Aucun projet. Créez-en un pour regrouper vos tâches par sujet.")
        ids = [p.id for p in projects]
        for index, project in enumerate(projects):
            with ui.row().classes(
                "w-full items-center gap-2 no-wrap py-1 border-b border-gray-200 dark:border-gray-700"
            ):
                ui.label(project.emoji).classes("text-xl")
                with ui.column().classes("flex-1 min-w-0 gap-0"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(project.name).classes("font-medium").style(f"color: {project.color}")
                        _visibility_badge(project.is_public)
                        if project.archived:
                            ui.label("🗄️ Archivé").classes("chip")
                    if project.description:
                        ui.label(project.description).classes("text-xs text-gray-500 truncate w-full")
                if project.can_edit:
                    _row_button("arrow_upward", "Monter", lambda i=index: move(i, -1))
                    _row_button("arrow_downward", "Descendre", lambda i=index: move(i, 1))
                    _row_button("edit", "Modifier", lambda p=project: _project_dialog(ctx, p, body.refresh))
                    _row_button(
                        "merge",
                        "Fusionner dans un autre projet",
                        lambda p=project: _merge_dialog(ctx, p, body.refresh, kind="project"),
                    )
                    _row_button(
                        "unarchive" if project.archived else "archive",
                        "Désarchiver"
                        if project.archived
                        else "Archiver (masqué des listes, conservé sur les tâches)",
                        lambda p=project: toggle_archive(p),
                    )
                    _row_button(
                        "delete", "Supprimer (les tâches restent, sans projet)", lambda p=project: delete(p)
                    )
                else:
                    ui.label("👀 Lecture seule").classes("chip").tooltip(
                        "Projet public créé par un autre utilisateur"
                    )

        def move(index: int, delta: int) -> None:
            if _try(lambda: ctx.ds.projects.reorder(_reorder(ids, index, delta))):
                ctx.refresh()

    def toggle_archive(project) -> None:
        if _try(lambda: ctx.ds.projects.update(project.id, ProjectPatch(archived=not project.archived))):
            ctx.refresh()

    def delete(project) -> None:
        if _try(
            lambda: ctx.ds.projects.delete(project.id),
            f"🗑️ Projet « {project.name} » supprimé — Ctrl+Z pour annuler",
        ):
            ctx.refresh()

    with _card(
        "📁 Projets / sujets", "Un projet regroupe des tâches ; une tâche appartient à un projet au plus."
    ):
        with ui.row().classes("w-full items-center gap-3"):
            ui.button("➕ Nouveau projet", on_click=lambda: _project_dialog(ctx, None, body.refresh)).props(
                "unelevated no-caps"
            ).mark("new-project")
            ui.checkbox(
                "Afficher les projets archivés",
                on_change=lambda e: (state.update(archived=e.value), body.refresh()),
            )
        body()
    ctx.on_refresh(body.refresh)


def _row_button(icon: str, tooltip: str, on_click) -> None:
    ui.button(icon=icon, on_click=on_click).props("flat round dense size=sm").tooltip(tooltip)


def _emoji_field(ctx: UiContext, value: str) -> ui.input:
    field = ui.input("Emoji", value=value).props("outlined dense").classes("w-28")
    emoji_grid(emoji_choices(ctx), field.set_value)
    return field


def _project_dialog(ctx: UiContext, project, on_saved) -> None:
    with ui.dialog() as dialog, ui.card().classes("w-[520px] max-w-[95vw] gap-3").mark("project-dialog"):
        ui.label("✏️ Modifier le projet" if project else "➕ Nouveau projet").classes("text-lg font-semibold")
        name = (
            ui.input("Nom", value=project.name if project else "")
            .props("outlined dense autofocus")
            .classes("w-full")
        )
        emoji = _emoji_field(ctx, project.emoji if project else "📁")
        color = ui.color_input("Couleur", value=project.color if project else "#5c7cfa", preview=True).props(
            "outlined dense"
        )
        description = (
            ui.textarea("Description", value=project.description if project else "")
            .props("outlined dense autogrow")
            .classes("w-full")
        )
        public = ui.toggle(
            {False: "🔒 Privé (moi seul)", True: "🌍 Public (tout le monde)"},
            value=project.is_public if project else False,
        ).props("no-caps unelevated")

        def save() -> None:
            fields = {
                "name": (name.value or "").strip(),
                "emoji": emoji.value or "📁",
                "color": color.value or "#5c7cfa",
                "description": description.value or "",
                "is_public": bool(public.value),
            }
            if not fields["name"]:
                ui.notify("Le nom du projet est obligatoire.", type="negative", position="top")
                return
            if project:
                ok = _try(
                    lambda: ctx.ds.projects.update(project.id, ProjectPatch(**fields)), "✔ Projet enregistré"
                )
            else:
                ok = _try(lambda: ctx.ds.projects.create(ProjectIn(**fields)), "✔ Projet créé")
            if ok:
                dialog.close()
                on_saved()
                ctx.refresh()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Annuler", on_click=dialog.close).props("flat")
            ui.button("Enregistrer", on_click=save).props("unelevated").mark("project-save")
    dialog.open()


def _tags(ctx: UiContext) -> None:
    @ui.refreshable
    def body() -> None:
        tags = ctx.ds.tags.list()
        if not tags:
            empty_state("🏷️", "Aucun tag. Ils se créent ici ou directement dans l'éditeur d'une tâche.")
        ids = [t.id for t in tags]
        for index, tag in enumerate(tags):
            with ui.row().classes(
                "w-full items-center gap-2 no-wrap py-1 border-b border-gray-200 dark:border-gray-700"
            ):
                ui.element("span").classes("tag-dot").style(
                    f"background: {tag.color}; width: 14px; height: 14px"
                )
                ui.label(tag.name).classes("flex-1 font-medium")
                _visibility_badge(tag.is_public)
                if tag.can_edit:
                    _row_button("arrow_upward", "Monter", lambda i=index: move(i, -1))
                    _row_button("arrow_downward", "Descendre", lambda i=index: move(i, 1))
                    _row_button("edit", "Modifier", lambda t=tag: _tag_dialog(ctx, t, body.refresh))
                    _row_button(
                        "merge",
                        "Fusionner dans un autre tag",
                        lambda t=tag: _merge_dialog(ctx, t, body.refresh),
                    )
                    _row_button("delete", "Supprimer (retiré des tâches)", lambda t=tag: delete(t))
                else:
                    ui.label("👀 Lecture seule").classes("chip").tooltip(
                        "Tag public créé par un autre utilisateur"
                    )

        def move(index: int, delta: int) -> None:
            if _try(lambda: ctx.ds.tags.reorder(_reorder(ids, index, delta))):
                ctx.refresh()

    def delete(tag) -> None:
        if _try(lambda: ctx.ds.tags.delete(tag.id), f"🗑️ Tag « {tag.name} » supprimé — Ctrl+Z pour annuler"):
            ctx.refresh()

    with _card("🏷️ Tags", "Plusieurs tags par tâche ; une pastille de couleur les signale sur les cartes."):
        ui.button("➕ Nouveau tag", on_click=lambda: _tag_dialog(ctx, None, body.refresh)).props(
            "unelevated no-caps"
        ).mark("new-tag")
        body()
    ctx.on_refresh(body.refresh)


def _tag_dialog(ctx: UiContext, tag, on_saved) -> None:
    with ui.dialog() as dialog, ui.card().classes("w-[440px] max-w-[95vw] gap-3").mark("tag-dialog"):
        ui.label("✏️ Modifier le tag" if tag else "➕ Nouveau tag").classes("text-lg font-semibold")
        name = (
            ui.input("Nom", value=tag.name if tag else "").props("outlined dense autofocus").classes("w-full")
        )
        suggested = tag.color if tag else ctx.ds.tags.suggest_color()  # couleur distincte des autres tags
        color = ui.color_input("Couleur", value=suggested, preview=True).props("outlined dense")
        public = ui.toggle(
            {False: "🔒 Privé (moi seul)", True: "🌍 Public (tout le monde)"},
            value=tag.is_public if tag else False,
        ).props("no-caps unelevated")

        def save() -> None:
            fields = {
                "name": (name.value or "").strip(),
                "color": color.value or suggested,
                "is_public": bool(public.value),
            }
            if not fields["name"]:
                ui.notify("Le nom du tag est obligatoire.", type="negative", position="top")
                return
            if tag:
                ok = _try(lambda: ctx.ds.tags.update(tag.id, TagPatch(**fields)), "✔ Tag enregistré")
            else:
                ok = _try(lambda: ctx.ds.tags.create(TagIn(**fields)), "✔ Tag créé")
            if ok:
                dialog.close()
                on_saved()
                ctx.refresh()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Annuler", on_click=dialog.close).props("flat")
            ui.button("Enregistrer", on_click=save).props("unelevated").mark("tag-save")
    dialog.open()


def _merge_dialog(ctx: UiContext, tag, on_saved, kind: str = "tag") -> None:
    """Fusionner un tag (ou, ``kind="project"``, un projet) dans un autre."""
    service = ctx.ds.projects if kind == "project" else ctx.ds.tags
    items = service.list()
    names = rules.label_names(items)  # « x (privé) » / « x (public) » si même nom
    others = {t.id: names[t.id] for t in items if t.id != tag.id}
    with ui.dialog() as dialog, ui.card().classes("w-[440px] max-w-[95vw] gap-3").mark("merge-dialog"):
        ui.label(f"🔀 Fusionner « {tag.name} »").classes("text-lg font-semibold")
        if kind == "project":
            explanation = (
                "Ses tâches et ses événements passeront dans le projet choisi ; ce projet disparaîtra."
            )
        else:
            explanation = (
                "Les tâches et événements qui portent ce tag recevront le tag choisi ; ce tag disparaîtra."
            )
        ui.label(explanation).classes("text-sm")
        target = (
            ui.select(others, label="Fusionner dans…")
            .props("outlined dense")
            .classes("w-full")
            .mark("merge-target")
        )

        def merge() -> None:
            if target.value is None:
                return
            if _try(lambda: service.merge(tag.id, target.value), "🔀 Fusion faite — Ctrl+Z pour annuler"):
                dialog.close()
                on_saved()
                ctx.refresh()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Annuler", on_click=dialog.close).props("flat")
            ui.button("Fusionner", on_click=merge).props("unelevated")
    dialog.open()


# ======================================================================================================
# Appareils connectés, utilisateurs
# ======================================================================================================


def _devices(ctx: UiContext) -> None:
    @ui.refreshable
    def body() -> None:
        for session in ctx.ds.account.sessions():
            with ui.row().classes(
                "w-full items-center gap-3 no-wrap py-2 border-b border-gray-200 dark:border-gray-700"
            ):
                ui.label("🖥️" if session.kind == "api" else "🌐").classes("text-2xl")
                with ui.column().classes("flex-1 min-w-0 gap-0"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(
                            session.label or ("Client bureau" if session.kind == "api" else "Navigateur")
                        ).classes("font-medium")
                        if session.current:
                            ui.label("🟢 Cet appareil").classes("chip")
                        if session.persistent and session.kind == "web":
                            ui.label("🍪 Se souvenir de moi").classes("chip")
                    ui.label(
                        f"Connecté le {fmt.local_datetime(session.created_at)} · dernière activité le "
                        f"{fmt.local_datetime(session.last_seen_at)} · "
                        f"expire le {fmt.local_datetime(session.expires_at)}"
                    ).classes("text-xs text-gray-500")
                if not session.current:
                    ui.button("Déconnecter", on_click=lambda s=session: revoke(s.id)).props(
                        "flat no-caps color=negative"
                    )

    def revoke(session_id: int) -> None:
        if _try(lambda: ctx.ds.account.revoke_session(session_id), "🚪 Appareil déconnecté"):
            body.refresh()

    def revoke_others() -> None:
        if _try(lambda: ctx.ds.account.revoke_other_sessions(), "🚪 Autres appareils déconnectés"):
            body.refresh()

    with _card(
        "💻 Appareils connectés", "Navigateurs et clients bureau actuellement connectés à votre compte."
    ):
        body()
        ui.button("Déconnecter tous les autres appareils", on_click=revoke_others).props(
            "outline no-caps color=negative"
        )


def _users(ctx: UiContext) -> None:
    @ui.refreshable
    def body() -> None:
        for user in ctx.ds.account.all_users():
            me = user.id == ctx.user.id
            with ui.row().classes(
                "w-full items-center gap-3 no-wrap py-2 border-b border-gray-200 dark:border-gray-700"
            ):
                ui.label("👑" if user.is_admin else "👤").classes("text-2xl")
                with ui.column().classes("flex-1 min-w-0 gap-0"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(user.display_name).classes("font-medium")
                        ui.label(f"@{user.username}").classes("text-sm text-gray-500")
                        if not user.is_active:
                            ui.label("⛔ Désactivé").classes("chip")
                        if me:
                            ui.label("C'est vous").classes("chip")
                _row_button("key", "Réinitialiser le mot de passe", lambda u=user: _password_dialog(ctx, u))
                if not me:
                    _row_button(
                        "person_off" if user.is_active else "person",
                        "Désactiver (déconnecté partout)" if user.is_active else "Réactiver",
                        lambda u=user: update(u, AdminUserPatch(is_active=not u.is_active)),
                    )
                    _row_button(
                        "remove_moderator" if user.is_admin else "add_moderator",
                        "Retirer les droits admin" if user.is_admin else "Donner les droits admin",
                        lambda u=user: update(u, AdminUserPatch(is_admin=not u.is_admin)),
                    )

    def update(user, patch: AdminUserPatch) -> None:
        if _try(lambda: ctx.ds.account.admin_update(user.id, patch), "✔ Compte mis à jour"):
            body.refresh()

    with _card(
        "👥 Utilisateurs", "Réservé aux administrateurs. Pas d'inscription libre : vous créez les comptes."
    ):
        ui.button("➕ Nouvel utilisateur", on_click=lambda: _new_user_dialog(ctx, body.refresh)).props(
            "unelevated no-caps"
        ).mark("new-user")
        body()


def _new_user_dialog(ctx: UiContext, on_saved) -> None:
    with ui.dialog() as dialog, ui.card().classes("w-[440px] max-w-[95vw] gap-3").mark("user-dialog"):
        ui.label("➕ Nouvel utilisateur").classes("text-lg font-semibold")
        display = ui.input("Nom affiché").props("outlined dense autofocus").classes("w-full")
        username = ui.input("Identifiant de connexion").props("outlined dense").classes("w-full")
        password = (
            ui.input(
                f"Mot de passe ({MIN_PASSWORD_LENGTH} caractères min.)",
                password=True,
                password_toggle_button=True,
            )
            .props("outlined dense")
            .classes("w-full")
        )
        admin = ui.checkbox("👑 Administrateur")

        def save() -> None:
            login = (username.value or "").strip()
            if not login:
                ui.notify("L'identifiant est obligatoire.", type="negative", position="top")
                return
            data = UserCreateIn(
                username=login,
                password=password.value or "",
                display_name=display.value or "",
                is_admin=bool(admin.value),
            )
            if _try(lambda: ctx.ds.account.create_user(data), f"✔ Compte « {login} » créé"):
                dialog.close()
                on_saved()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Annuler", on_click=dialog.close).props("flat")
            ui.button("Créer", on_click=save).props("unelevated").mark("user-save")
    dialog.open()


def _password_dialog(ctx: UiContext, user) -> None:
    with ui.dialog() as dialog, ui.card().classes("w-[440px] max-w-[95vw] gap-3"):
        ui.label(f"🔑 Nouveau mot de passe pour {user.display_name}").classes("text-lg font-semibold")
        ui.label("La personne sera déconnectée de tous ses appareils.").classes("text-sm text-gray-500")
        password = (
            ui.input(
                f"Nouveau mot de passe ({MIN_PASSWORD_LENGTH} caractères min.)",
                password=True,
                password_toggle_button=True,
            )
            .props("outlined dense autofocus")
            .classes("w-full")
        )

        def save() -> None:
            if not password.value:
                ui.notify("Saisissez le nouveau mot de passe.", type="negative", position="top")
                return
            patch = AdminUserPatch(new_password=password.value)
            if _try(lambda: ctx.ds.account.admin_update(user.id, patch), "🔑 Mot de passe réinitialisé"):
                dialog.close()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Annuler", on_click=dialog.close).props("flat")
            ui.button("Enregistrer", on_click=save).props("unelevated")
    dialog.open()


# ======================================================================================================
# Données : sauvegarde (admin)
# ======================================================================================================


def _data(ctx: UiContext) -> None:
    with _card(
        "💾 Sauvegarde",
        "Archive .tar de tout le serveur : la base de données (copie cohérente, prise sans arrêter le "
        "serveur), les pièces jointes, et un manifeste (date, version, empreintes des fichiers).",
    ):
        uploads = ui.checkbox("📎 Inclure les pièces jointes", value=True).mark("backup-uploads")

        async def download() -> None:
            include = bool(uploads.value)
            if not ctx.ds.is_desktop:
                ui.download.from_url(ctx.ds.backup_url(include))  # le navigateur, avec le cookie de session
                return
            # Client bureau : enregistrée dans « Téléchargements », hors de la boucle de l'interface (archive
            # potentiellement volumineuse).
            button.disable()
            try:
                path = await run.io_bound(ctx.ds.save_backup, include)
            except OrganizerError as exc:
                ui.notify(exc.message, type="negative", position="top")
                return
            finally:
                button.enable()
            ui.notify(f"💾 Sauvegarde enregistrée : {path}", type="positive", position="top", timeout=10000)

        button = (
            ui.button("⬇️ Télécharger une sauvegarde", on_click=download)
            .props("unelevated no-caps")
            .mark("backup-download")
        )
        ui.label("Pour restaurer une archive sur le serveur : deploy/restore.sh (voir le README).").classes(
            "text-xs text-gray-500"
        )
    _backup_keys(ctx)


def _backup_keys(ctx: UiContext) -> None:
    @ui.refreshable
    def body() -> None:
        keys = ctx.ds.account.backup_keys()
        if not keys:
            ui.label("Aucun jeton pour l'instant.").classes("text-sm text-gray-500")
        for key in keys:
            with (
                ui.row()
                .classes(
                    "w-full items-center gap-3 no-wrap py-2 border-b border-gray-200 dark:border-gray-700"
                )
                .mark(f"backup-key-{key.id}")
            ):
                ui.label("🔑").classes("text-2xl")
                with ui.column().classes("flex-1 min-w-0 gap-0"):
                    ui.label(key.label or "Sauvegarde").classes("font-medium")
                    used = (
                        f"dernière utilisation le {fmt.local_datetime(key.last_used_at)}"
                        f"{f' depuis {key.last_used_ip}' if key.last_used_ip else ''}"
                        if key.last_used_at
                        else "jamais utilisé"
                    )
                    ui.label(f"Créé le {fmt.local_datetime(key.created_at)} · {used}").classes(
                        "text-xs text-gray-500"
                    )
                ui.button("Révoquer", on_click=lambda k=key: _revoke_key_dialog(ctx, k, body.refresh)).props(
                    "flat no-caps color=negative"
                ).mark(f"revoke-key-{key.id}")

    with _card(
        "🔑 Jetons de sauvegarde",
        "Pour un script de sauvegarde planifié (borg…) : un jeton permet seulement de télécharger "
        "l'archive, sans expiration, et uniquement depuis le réseau local. Il cesse de fonctionner si vous "
        "le révoquez ou si son créateur n'est plus administrateur.",
    ):
        body()
        ui.button("➕ Nouveau jeton", on_click=lambda: _new_key_dialog(ctx, body.refresh)).props(
            "unelevated no-caps"
        ).mark("new-backup-key")


def _new_key_dialog(ctx: UiContext, on_saved) -> None:
    with ui.dialog() as dialog, ui.card().classes("w-[560px] max-w-[95vw] gap-3").mark("backup-key-dialog"):
        ui.label("➕ Nouveau jeton de sauvegarde").classes("text-lg font-semibold")
        label = (
            ui.input("Nom (à quoi il sert)", value="Sauvegarde borg du Pi")
            .props("outlined dense autofocus maxlength=100")
            .classes("w-full")
            .mark("backup-key-label")
        )
        result = ui.column().classes("w-full gap-2")
        buttons = ui.row().classes("w-full justify-end gap-2")

        def create() -> None:
            created: list = []
            if not _try(lambda: created.append(ctx.ds.account.create_backup_key(label.value or ""))):
                return
            token = created[0].token
            on_saved()
            label.disable()
            buttons.clear()
            with result:
                ui.label(
                    "⚠️ Copiez ce jeton maintenant : il ne sera plus jamais affiché. Rangez-le comme un mot "
                    "de passe (fichier lisible par vous seul)."
                ).classes("text-sm text-orange-700 dark:text-orange-300")
                ui.input("Jeton", value=token).props("outlined dense readonly").classes(
                    "w-full font-mono"
                ).mark("backup-key-token")
                ui.label("Exemple, sur le Pi :").classes("text-sm text-gray-500")
                ui.code(
                    f'curl -fsS -H "Authorization: Bearer {token}" \\\n'
                    "     http://127.0.0.1:2603/api/v1/admin/backup -o organizer.tar",
                    language="bash",
                ).classes("w-full text-xs")
            with buttons:
                ui.button("📋 Copier le jeton", on_click=lambda: ui.clipboard.write(token)).props(
                    "flat no-caps"
                )
                ui.button("Fermer", on_click=dialog.close).props("unelevated")

        with buttons:
            ui.button("Annuler", on_click=dialog.close).props("flat")
            ui.button("Créer", on_click=create).props("unelevated").mark("backup-key-create")
    dialog.open()


def _revoke_key_dialog(ctx: UiContext, key, on_saved) -> None:
    with ui.dialog() as dialog, ui.card().classes("w-[440px] max-w-[95vw] gap-3"):
        ui.label(f"Révoquer « {key.label or 'Sauvegarde'} » ?").classes("text-lg font-semibold")
        ui.label(
            "Le script qui l'utilise ne pourra plus télécharger de sauvegarde. C'est définitif : il faudra "
            "créer un nouveau jeton."
        ).classes("text-sm text-gray-500")

        def revoke() -> None:
            if _try(lambda: ctx.ds.account.revoke_backup_key(key.id), "🔑 Jeton révoqué"):
                dialog.close()
                on_saved()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Annuler", on_click=dialog.close).props("flat")
            ui.button("Révoquer", on_click=revoke).props("unelevated color=negative").mark(
                "revoke-key-confirm"
            )
    dialog.open()
