# Notes pour Claude — Client bureau, temps réel, PWA

Complément de `CLAUDE.md` (à la racine), à lire avant de modifier ce domaine.

## Étape 7 : client bureau

- `organizer/client/` : **aucune** dépendance au serveur (`organizer.server`) hors tests. `app.py`
  (`DesktopClient` : `/connect`, `context()` = fabrique des pages sur `RemoteDataSource`, onglet de
  réglages via `UiContext.extra_settings`, `LaunchGuard`, notifier, `main()`), `api.py` (`ApiClient`,
  `error_from` : code HTTP → erreur métier ; `ServerUnreachable` / `NotAuthenticated` dans `core/errors.py`),
  `remote.py`, `config.py`, `system.py`, `notifications.py`.
- **Contrat** : chaque méthode de service utilisée par l'UI doit exister dans `remote.py` avec la même
  signature. Ajouter une méthode de service utilisée par l'UI = ajouter sa route API **et** sa version
  distante **et** un test dans `tests/test_client.py` (comparaison avec le service local quand c'est possible).
  Liste des appels de l'UI : `grep -rhoE "ds\.[a-z_]+\.[a-z_]+" organizer/ui | sort -u`.
- `ConfigStore.save` : fichier temporaire unique (`mkstemp`, 600) + verrou — plusieurs fils enregistrent
  `client.json` (bascule réseau local en arrière-plan).
- Envoi : `_sent()` = `exclude_unset` (patchs partiels, héritage des sous-tâches) ; `ApiClient.call(...,
  json=None)` envoie `null` (``NO_BODY`` = pas de corps).
- Liens côté bureau : `open_link` (task_editor) délègue à `ds.open_url / open_path / open_attachment` quand
  `ds.is_desktop` ; erreurs (fichier absent) → toast via `ctx.call`.
- Fenêtre native : NiceGUI lance pywebview dans un **sous-processus qui réimporte** `run_client.py`
  (garde `__main__` / `__mp_main__`) ; secret et port passent par l'environnement (`ORGANIZER_CLIENT_LAUNCH`,
  `ORGANIZER_CLIENT_PORT`) pour être identiques ; `app.native.window_args["url"]` = URL de départ avec le
  secret ; GTK forcé sous Linux (`start_args["gui"]`), sinon pywebview tente Qt.
- Tests des pages du client : `tests/test_client_pages.py` (marqueur `nicegui_main_file("tests/client_main.py")`,
  serveur de test en mémoire passé par `tests/client_harness.HTTP`, `ORGANIZER_CLIENT_DIR` fixé par une
  fixture autouse **avant** le simulateur).
- Essais manuels sans rien ouvrir sur le bureau : `PATH=<faux xdg-open>:$PATH BROWSER="<script> %s"`
  `DBUS_SESSION_BUS_ADDRESS=unix:path=/nonexistent ORGANIZER_CLIENT_DIR=<dossier> run_client.py --browser`.
- **Arrière-plan / instance unique** : `launcher.py` (ligne de commande, **sans importer NiceGUI** avant de
  savoir s'il faut démarrer : la transmission doit rester ≈ 0,07 s) → `instance.forward` → route
  `/_organizer/control/<action>` (secret dans l'en-tête, exemptée du `LaunchGuard`) → `DesktopClient.control`.
  `window.py` tourne **dans le sous-processus de la fenêtre** (`start_args["func"]`) : fermer = cacher
  (`events.closing` renvoie False), méthodes `organizer_present` / `organizer_quit` ajoutées à la fenêtre et
  appelées par `nicegui.native.native.method_queue` (elles doivent renvoyer None). `app.shutdown()` passerait
  par la fermeture annulée : pour quitter, toujours `organizer_quit`.
- **Latence** : chaque appel de l'UI est une requête bloquante (≈ 20 ms en local, ≈ 300 ms par Cloudflare).
  `client/cache.py` (`RemoteCache`, attaché à `ApiClient.cache`, partagé par les copies `with_headers`) garde
  projets, tags, boards (oubliés si leurs tables changent : `DesktopClient._dispatch_change` →
  `cache.on_change`), utilisateurs, `me`, préférences (délai court, pas d'événement), état d'annulation
  (`UNDO_KEY`, rempli par l'en-tête `X-Organizer-Undo` que `security.add_undo_status` joint aux écritures
  en Bearer). `cache.on_write(path)` à chaque écriture du poste (table `WRITES` ; annuler / rétablir oublie
  projets, tags, boards). Les valeurs rendues sont des copies (préférences : copie profonde). Une méthode de
  `remote.py` qui lit une donnée gardée en mémoire doit déclarer ses tables. L'éditeur appelle
  `_page_changed()` (rafraîchissement **léger** : `ctx.refresh(light=True)` = boutons annuler / rétablir) ;
  la page est relue à la fermeture (`_on_hide`). Mesure : client lancé par un script qui enveloppe
  `ApiClient.request` (durée, chemin) + clics rejoués dans Firefox.
- **Réseau local automatique** : `server/local_access.py` (`instance_key` dans `<données>/instance.key`,
  `user_key`, `proof`, `local_urls`) + routes `api/local.py` (`/local-access` avec session ;
  `/local-access/proof` seulement si `security.is_local_address(client_ip)`). Client : `client/lan.py`
  (`LanSwitch` : `refresh_info`, `verify` **sans jeton**, `check`, `before_request` installé comme
  `Route.checker`, fil `tick` toutes les 60 s ; partage l'objet `DesktopClient.config` via
  `get_config` / `save_config`). `ApiClient.route` (`Route` : `server_url` / `base_url`, `http`, `local`,
  `use_local` / `use_server`), partagée par les copies `with_headers` ; `ApiClient.request` revient à
  l'adresse configurée et retente une fois si le réseau local échoue ; `live.py` revient aussi à l'adresse
  configurée sur coupure du flux. `DesktopClient.api` compare `route.server_url` (pas `base_url`, qui
  change). Tests : `tests/test_lan.py` (classe `Net` : deux `TestClient` vus depuis une IP publique / privée,
  serveur imposteur, réseau local coupé par `httpx.MockTransport`). Les tests de pages du client passent
  `install(lan=False)`.
- Indicateur de connexion : `UiContext.connection` (fonction → `Connection(local, tooltip, target)`) et
  `connection_live` ; `components/connection_badge.py` (`page_sticky` bas gauche, `ui.button(color=None)`
  sinon le fond reste « primary », `ui.tooltip` créé une fois + `set_text`, `ui.timer` si `connection_live`).
  Fourni par `server_context` (`web_connection` : `is_local_address(client_ip)`) et
  `DesktopClient.connection_info` (`desktop_connection`, `lan.is_lan_url`).
- Pages ouvertes mémorisées (`DesktopClient._pages`) : « nouvelle tâche » ouvre l'éditeur dans la page
  affichée (`_in_page`), sinon charge `/?task=new`.
- Linux : `GLib.set_prgname("organizer")` dans le sous-processus = identifiant Wayland = nom du `.desktop`.
- Raccourcis globaux : impossibles à capter soi-même sous Wayland → déclarés au bureau par
  `organizer/client/install.py`. KDE : composant `organizer.desktop`, actions `_launch` (ouvrir) et
  `new-task`, par `doRegister` + **`setShortcutKeys(..., SetPresent | NoAutoloading)`**. ⚠️ Avec
  `setForeignShortcutKeys`, le raccourci est enregistré et répond à `invokeShortcut` (D-Bus) mais Plasma 6
  l'ignore sur un vrai appui clavier (bug rencontré : Ctrl+Alt+O inopérant). `invokeShortcut` ne prouve donc
  rien : tester avec un **vrai appui**, par un clavier virtuel `uinput` (`/dev/uinput` accessible à
  l'utilisateur ; script Python stdlib : `UI_DEV_SETUP` / `UI_DEV_CREATE`, événements `EV_KEY` ; codes
  Ctrl 29, Alt 56, O 24, N 49). Le journal de KWin (`journalctl --user`) signale les actions inconnues
  (« failed to find an action matching… »). Fermer la fenêtre dans un test : script KWin filtré sur le
  **pid** du sous-processus (`workspace.windowList()`).
- **Windows** : `client/winshell.py` (`ctypes` seulement), lancé par `window._start_windows_shell` dans le
  sous-processus de la fenêtre : fil avec fenêtre cachée + boucle de messages ; raccourcis globaux par
  `RegisterHotKey` (le processus qui reçoit `WM_HOTKEY` a le droit de passer au premier plan), icône de zone
  de notification (`Shell_NotifyIconW`, menu Ouvrir / Nouvelle tâche / Quitter, remise sur `TaskbarCreated`),
  `bring_to_front` (`SetForegroundWindow`, repli `AttachThreadInput` ; jamais `Form.Activate` : hors du fil
  de l'interface). ⚠️ Les raccourcis ne sont **plus** posés sur les `.lnk` (`install.ps1` les efface) :
  l'Explorateur les garderait (`RegisterHotKey` → erreur 1409) et la chaîne lnk → nouveau `pythonw` →
  transmission → premier plan refusé échouait une fois sur deux. `instance.forward` appelle
  `AllowSetForegroundWindow(ASFW_ANY)`. Notifications : `Icon(path=organizer-256.png)`, sinon Windows
  affiche l'icône de Python (clé `HKCU\Software\Classes\AppUserModelId\Organizer`, écrite par
  desktop-notifier). Test réel : `keybd_event` simule l'appui (`tests/test_client_desktop.py`).
- **macOS** (⚠️ jamais essayé sur un vrai Mac : écrit d'après les API, testé sous Linux pour la partie
  pure) : `client/macshell.py`, lancé par `window._start_macos_shell` dans le sous-processus de la fenêtre,
  `Shell.start` sur le **fil principal** (`PyObjCTools.AppHelper.callAfter` : exécuté une fois la boucle
  Cocoa lancée, donc après la création de la fenêtre et du délégué de pywebview). Délégué
  `OrganizerAppDelegate` (sous-classe de `BrowserView.AppDelegate`, posé à la place de celui de pywebview) :
  `applicationShouldTerminate_` → `QUIT.set()` + `NSTerminateNow` (⌘Q quitte ; la fermeture de fenêtre
  reste « cacher »), `applicationShouldHandleReopen_hasVisibleWindows_` → réaffiche. Raccourcis : Carbon
  `RegisterEventHotKey` + `InstallEventHandler` sur `GetEventDispatcherTarget()` par `ctypes` (aucune
  autorisation, contrairement à `NSEvent` / CGEventTap) ; codes kVK_ANSI (positions QWERTY) ; le rappel
  lance l'action dans un fil. `rename_app` (CFBundleName dans `NSBundle.mainBundle().infoDictionary()`)
  appelé par `app.main` dans le sous-processus **avant** l'import de `webview.platforms.cocoa` (qui crée
  `NSApplication`) ; icône du Dock par `start_args["icon"]`. Notifications : desktop-notifier tombe sur
  son backend muet hors d'une application signée → `osascript` (`notifications.osascript_command`).
  Installation : `client/install_macos.py` — `Organizer.app` = applet AppleScript (`osacompile -e …`,
  source passé ligne à ligne : pas de souci de codage), gestionnaires `run` et `open location` (les liens
  `organizer://` arrivent par événement Apple, jamais en argument : un script shell ne les verrait pas),
  `do shell script "… &"` puis l'applet s'arrête (`LSUIElement`) ; `Info.plist` complété
  (`bundle_info` : identifiant, `CFBundleURLTypes`, `CFBundleIconFile`, sans `CFBundleIconName` ni
  `Assets.car`, sinon icône d'AppleScript), `.icns` par `iconutil`, `codesign --force --deep -s -`,
  `lsregister -f`. Agent launchd (`launch_agent`) jamais chargé par `launchctl` : lu à la session
  suivante (un `bootout` tuerait le client lancé par launchd). Scripts : bash **3.2** (`${1+"$@"}` avec
  `set -u`, pas de `setsid` → `nohup`). Tests : `tests/test_client_macos.py` (faux `osacompile`,
  `iconutil`, `codesign` dans le PATH, `sys.platform` forcé).
- Installeurs : `install/linux/install.sh`, `install/windows/install.ps1` (UTF-8 **avec BOM** et fins de
  ligne CRLF, sinon Windows PowerShell 5.1 abîme les accents), `install/macos/install.sh`. Python 3.11 à
  3.13 sous Windows (pythonnet).
- Icône : `scripts/make_icons.sh <svg> <svg plein>` régénère `organizer/assets/` (rsvg-convert + ImageMagick,
  outils de développement seulement ; les fichiers produits sont versionnés).

## Étape 8 : temps réel, PWA

- **Temps réel** : `core/events.py` (`EventBus`, `ChangeEvent` = tables + auteur + origine). Publié par
  `UnitOfWork` après commit (`on_commit`, seulement si l'historique a capté des changements : opérations
  avec libellé) et par `UndoService`. `Services(..., events=, origin=)` ; `AppState.events`,
  `services_for(user, origin)`. Pages web : `server_context` crée une `LiveRefresh` (`ui/live.py`) abonnée
  au bus (désabonnement `client.on_delete`). API : `GET /api/v1/events` (SSE, `api/events.py`, `HEARTBEAT`) ;
  client bureau : `client/live.py` (`EventListener` dans un fil, `parse_sse`), origine envoyée par
  `RemoteDataSource(origin=)` (en-tête `X-Organizer-Origin`, `ApiClient.with_headers`).
- `LiveRefresh` : rafraîchit après 0,4 s, ignore les événements de sa propre origine, attend la fin d'un
  glisser (`dnd.js` émet `dragstate`, `UiContext.set_dragging`). L'éditeur de tâche n'est **pas** abonné à
  `refresh()` (il ne doit pas changer sous les doigts).
- **PWA** : `server/pwa.py` (routes manifeste + `sw.js` dans `wiring.install` ; `add_static` `/icons` et
  `add_head` en-têtes partagés dans `app.build`). Icônes : `organizer/assets/` (`ASSETS_DIR`, `FAVICON` dans
  `organizer/__init__.py`), régénérées par `scripts/make_icons.sh icone.svg icone-pleine.svg`.
- HTTPS : `Settings.ssl_cert` / `ssl_key` (`ORGANIZER_SSL_*`) → `ui.run(ssl_*)`, cookie `Secure` ; client :
  `ORGANIZER_CA_FILE`.
- `dnd.js` : défilement automatique près des bords (`autoScroll`, rAF) ; l'aimantation (`snap-x`) est
  coupée pendant un glisser (CSS `body.dnd-active *`), sinon chaque petit pas est annulé.
- Tests du temps réel : `tests/test_live.py` (vrai serveur uvicorn dans un fil pour le flux SSE) ; dans les
  tests de pages, `asyncio.sleep(0.6)` laisse passer le délai de `LiveRefresh`.
