"""Lance le client bureau Organizer (fenêtre native).

Options : ``--new-task`` (nouvelle tâche), ``--quit`` (arrêter), ``--hidden`` (démarrer en arrière-plan),
``--browser`` (dans le navigateur). Si le client tourne déjà, la commande lui est transmise.
"""

from organizer.client.launcher import run

if __name__ in {"__main__", "__mp_main__"}:  # la fenêtre native tourne dans un sous-processus
    run()
