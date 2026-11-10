"""Dépôt de fichiers du système sur la page (voir ``file_drop.js``) : un composant par page, créé par
``app_frame``.

- Sur une zone déclarée par :func:`file_drop_zone` (l'éditeur de tâche ouvert) : les fichiers vont au
  ``ui.upload`` de cette zone.
- Sur une carte / ligne de tâche (:func:`organizer.ui.components.dnd.draggable`) : le composant enregistre la
  tâche visée, puis les fichiers partent par son propre ``ui.upload`` et sont joints à cette tâche.
- Ailleurs : message, et une ligne de diagnostic dans le journal.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

from nicegui import events, ui

if TYPE_CHECKING:
    from organizer.ui.context import UiContext

log = logging.getLogger("organizer.ui")
MISSED = "📎 Déposez le fichier sur une tâche : sa carte, ou son éditeur ouvert."


def reusable_upload(upload: ui.upload) -> ui.upload:
    """Vide la liste interne de ``upload`` une fois tous ses envois terminés : QUploader refuse sinon, en
    silence, un fichier identique à un fichier déjà envoyé (même nom, taille et date)."""
    upload.on("finish", js_handler=f"() => runMethod({upload.id}, 'reset', [])")
    return upload


class FileDrop(ui.element, component="file_drop.js"):
    def __init__(self, ctx: UiContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.target: int | None = None  # tâche visée par le dernier dépôt sur une carte
        with self:
            self.upload = reusable_upload(
                ui.upload(auto_upload=True, multiple=True, on_upload=self._uploaded)
                .classes("hidden")
                .mark("card-upload")
            )
        self._props["upload_id"] = self.upload.id
        # Navigateur : pas de fenêtre native pour relayer les adresses des fichiers (inutile d'attendre).
        self._props["web"] = not ctx.ds.is_desktop
        self.on("card-files", self._card_files)
        self.on("missed", self._missed)
        self.on("paths", self._paths)

    def _card_files(self, e: events.GenericEventArguments) -> None:
        self.target = int(e.args.get("task") or 0) or None
        self.run_method("flush")

    async def _uploaded(self, e: events.UploadEventArguments) -> None:
        if self.target is None:
            return
        data = await e.file.read()
        task = self.ctx.call(self.ctx.ds.tasks.get, self.target)
        if task is None:
            return
        link = self.ctx.call(
            self.ctx.ds.attachments.upload, task.id, e.file.name, io.BytesIO(data), e.file.content_type
        )
        if link is not None:
            ui.notify(f"📎 « {link.label} » joint à « {task.title} »", position="top")
            self.ctx.refresh()

    def _paths(self, e: events.GenericEventArguments) -> None:
        """Fichiers déposés connus seulement par leur adresse ``file://`` : lisibles par le client bureau."""
        args = e.args if isinstance(e.args, dict) else {}
        paths = [local_path(uri) for uri in args.get("uris") or []]
        log.info("Fichiers déposés reçus sous forme d'adresses (%s) : %d", args.get("kind"), len(paths))
        if not self.ctx.ds.is_desktop:
            ui.notify("Ce navigateur n'a pas transmis le contenu du fichier.", type="warning", position="top")
            return
        if args.get("kind") == "zone":
            if self.ctx.editor is not None:
                self.ctx.editor.attach_local_files(paths)
            return
        task = self.ctx.call(self.ctx.ds.tasks.get, int(args.get("task") or 0))
        if task is not None:
            names = attach_local_files(self.ctx, task.id, paths)
            if names:
                ui.notify(f"📎 {', '.join(names)} joint(s) à « {task.title} »", position="top")
                self.ctx.refresh()

    def _missed(self, e: events.GenericEventArguments) -> None:
        args = e.args if isinstance(e.args, dict) else {}
        log.info(
            "Fichier déposé sans cible : élément %s, types %s, %s fichier(s)",
            str(args.get("target", "?"))[:80],
            args.get("types"),
            args.get("files"),
        )
        ui.notify(MISSED, type="warning", position="top")


def local_path(uri: str) -> Path:
    """``file:///home/a/b%20c.txt`` → ``/home/a/b c.txt`` (``file:///C:/…`` sous Windows → ``C:/…``)."""
    path = unquote(urlparse(uri).path)
    if len(path) > 2 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return Path(path)


def attach_local_files(ctx: UiContext, item_id: int, paths: list[Path], upload=None) -> list[str]:
    """Joint des fichiers du poste à une tâche (ou, avec ``upload=ds.attachments.upload_event``, à un
    événement) ; renvoie les noms joints (erreurs affichées)."""
    upload = upload or ctx.ds.attachments.upload
    names = []
    for path in paths:
        try:
            with path.open("rb") as stream:
                link = ctx.call(upload, item_id, path.name, stream, None)
        except OSError as exc:
            ui.notify(f"📁 Lecture impossible : {path} ({exc.strerror})", type="negative", position="top")
            continue
        if link is not None:
            names.append(f"« {link.label} »")
    return names


def file_drop_zone(
    element: ui.element, upload: ui.upload, label: str = "📎 Déposer pour joindre"
) -> ui.element:
    """Les fichiers déposés sur ``element`` sont envoyés par ``upload`` (comme s'ils avaient été choisis
    dans le sélecteur de fichiers) ; ``label`` s'affiche pendant le survol."""
    element._props["data-file-drop"] = str(upload.id)
    element._props["data-file-drop-label"] = label
    element.update()
    return element


def open_file_picker(button: ui.button, upload: ui.upload) -> ui.button:
    """Le bouton ouvre le sélecteur de fichiers de ``upload``.

    Directement dans le navigateur (gestionnaire JavaScript), **sans aller-retour par le serveur** : un
    navigateur n'ouvre le sélecteur qu'en réponse immédiate à un geste de l'utilisateur. Après un
    aller-retour, WebKit (fenêtre du client bureau, Safari) et Chrome refusent en silence ; seul Firefox
    laissait passer.
    """
    button.on("click", js_handler=f"() => runMethod({upload.id}, 'pickFiles', [])")
    return button
