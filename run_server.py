"""Lance le serveur Organizer (voir README.md)."""

from organizer.server.app import main

if __name__ in {"__main__", "__mp_main__"}:
    main()
