"""Ligne de commande du client bureau (``run_client.py``).

Si un client tourne déjà pour cet utilisateur, la commande lui est transmise (``instance.forward``) et ce
lancement s'arrête aussitôt : c'est ce qu'exécutent le lanceur et les raccourcis clavier globaux, d'où
l'importation tardive de NiceGUI (plusieurs centaines de millisecondes) seulement s'il faut démarrer.

Un lien ``organizer://note/5`` (protocole déclaré au système par les installeurs) arrive en argument : il
est transmis au client lancé (commande ``open``), ou le client démarre directement sur l'élément.
"""

from __future__ import annotations

import argparse
import multiprocessing
import os

from organizer import links
from organizer.client import instance, system


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="run_client.py", description="Organizer — client bureau")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--show", action="store_true", help="afficher Organizer (comportement par défaut)")
    action.add_argument("--new-task", action="store_true", help="ouvrir l'éditeur sur une nouvelle tâche")
    action.add_argument("--quit", action="store_true", help="arrêter le client lancé")
    action.add_argument(
        "--hidden", action="store_true", help="démarrer en arrière-plan (ouverture de session)"
    )
    parser.add_argument(
        "link", nargs="?", default=None, help="lien organizer://note/5 (task, event, note) à ouvrir"
    )
    parser.add_argument("--browser", action="store_true", help="dans le navigateur au lieu d'une fenêtre")
    parser.add_argument("--port", type=int, default=None, help="port local (par défaut : un port libre)")
    return parser.parse_args(argv)


def link_ref(args: argparse.Namespace) -> str | None:
    """Élément à ouvrir (``note:5``) d'après le lien passé en argument (``organizer://note/5``)."""
    return links.from_url(args.link) if args.link else None


def command(args: argparse.Namespace) -> str:
    """Commande à transmettre au client déjà lancé."""
    if link_ref(args):
        return "open"
    if args.new_task:
        return "new-task"
    if args.quit:
        return "quit"
    return "ping" if args.hidden else "show"


def run(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    # Dans le sous-processus de la fenêtre (``__mp_main__``), on démarre toujours (rien à transmettre).
    if multiprocessing.current_process().name == "MainProcess" and instance.ENV_SECRET not in os.environ:
        data = {"ref": link_ref(args)} if link_ref(args) else None
        if instance.forward(system.config_dir(), command(args), data) or args.quit:
            return
    from organizer.client.app import main

    main(args)
