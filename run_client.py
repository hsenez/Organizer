"""Lance le client bureau Organizer (fenêtre native ; ``--browser`` pour l'ouvrir dans le navigateur)."""

from organizer.client.app import main

if __name__ in {"__main__", "__mp_main__"}:  # la fenêtre native tourne dans un sous-processus
    main()
