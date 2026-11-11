# Notes pour Claude — Serveur, mise en ligne, sauvegarde, migrations, versions

Complément de `CLAUDE.md` (à la racine), à lire avant de modifier ce domaine.

## Architecture du serveur (étape 2)

- `organizer/server/app.py` : `build()` installe tout sur l'application NiceGUI (`install()` de `wiring.py`
  + `register_pages()`), puis `main()` appelle `ui.run()`. Les tests de l'API utilisent `create_api_app()`
  (FastAPI nue, même `install()`).
- **Authentification** : `AuthMiddleware` (`security.py`) résout le cookie ou le jeton Bearer une fois par
  requête → `request.state.auth` (`ResolvedSession` ou None). Dans l'API : dépendances `get_user`,
  `get_admin`, `get_services` (`api/deps.py`). Dans une page : `guard(request)` renvoie une redirection
  si besoin.
- Une page NiceGUI **ne peut pas poser de cookie** : connexion = ticket à usage unique (`TicketStore`) puis
  redirection vers `/auth/complete`, route HTTP qui pose le cookie.
- Les pages s'enregistrent via `register_pages()` (pas de `@ui.page` à l'import) : le simulateur de test
  NiceGUI réinitialise l'application entre deux tests et doit pouvoir les réenregistrer.
- Routes API en `def` synchrones (FastAPI les exécute dans un thread : SQLite synchrone sans bloquer la boucle).
- Erreurs métier (`OrganizerError`) → JSON `{"detail": …}` avec le code HTTP de l'exception.

## Mise en ligne (Cloudflare Tunnel)

- Guide utilisateur : README, section « Accès depuis Internet » (tableau de bord vérifié en novembre 2026 ;
  à revérifier si Cloudflare change ses menus). Route du tunnel vers `http://127.0.0.1:2603`, jamais
  `localhost` (peut être `::1`, où le serveur n'écoute pas). Bot fight mode bloquerait le client bureau.

- `cloudflared` sur le Pi → `http://localhost:2603`. Uvicorn (`ProxyHeadersMiddleware`, actif par défaut,
  confiance à 127.0.0.1 / ::1) réécrit `request.client.host` et `request.url.scheme` d'après
  `X-Forwarded-For` / `-Proto` : **toujours** les utiliser pour l'IP et le protocole du visiteur, jamais
  `settings.https` (qui dit seulement si uvicorn a lui-même un certificat). `security.is_https(request)`.
- `SecurityHeadersMiddleware` (ASGI pur, pour laisser passer le SSE) : en-têtes ajoutés seulement s'ils sont
  absents de la réponse. Tests : `tests/test_proxy.py` passe par `uvicorn.Config(...).load()` pour avoir la
  même pile qu'en vrai (`TestClient(..., client=("127.0.0.1", port))` simule le proxy).
- Documentation de l'API refusée aux non connectés dans `AuthMiddleware` (`is_api_docs` lit `docs_url`,
  `redoc_url`, `openapi_url` sur l'application : NiceGUI les fixe dans `ui.run(fastapi_docs=True)`).
- Anti force brute (`LoginThrottle`) : niveau (IP, identifiant) remis à zéro par une réussite, niveau
  identifiant seul (toutes IP) **jamais** remis à zéro par une réussite. `check_credentials`
  (`server/api/auth.py`, partagé par l'API et la page /login) écrit chaque tentative dans le journal.
- Arrêt du serveur : `ui.run(timeout_graceful_shutdown=SHUTDOWN_GRACE_SECONDS)` (3 s) — sinon uvicorn attend
  la fin des flux SSE des clients bureau, qui ne finissent jamais, et `systemctl restart` durait 90 s (arrêt
  forcé par systemd). Mesure : serveur + `curl -N …/api/v1/events`, puis SIGTERM.
- Journal du serveur : `configure_logging()` (dans `main()` seulement, pas dans `build()` : les tests
  utilisent `caplog`) ; loggers `organizer.*`.
- Mots de passe : `MIN_PASSWORD_LENGTH = 12` (`core/services/users.py`). `authenticate` pose / retire la
  préférence `WEAK_PASSWORD_PREF` ; changement ou réinitialisation la retire. Bandeaux : `ctx.banners`
  (`Banner(text, tone, action, target, mark)`) + ceux calculés par `layout.page_banners` (mot de passe court,
  lu par `ds.account.get_pref` : marche aussi sur le client bureau) ; `ctx.banner_rows` pour en retirer un.
- Avec `nosniff`, un script servi sous un mauvais type est bloqué : après une mise à jour de NiceGUI ou un
  nouveau fichier statique, vérifier les `Content-Type` des ressources d'une page.

## Sauvegarde

- `organizer/server/backup.py` : `BackupArchive(settings, include_uploads)` prend l'image de la base **à la
  création** (`sqlite3` `backup()` → fichier temporaire `.backup-*.db` du dossier des données, journal
  `DELETE`, `integrity_check`) ; `chunks()` produit le `.tar` à la main (en-têtes `TarInfo.tobuf`, blocs de
  512 o, fin à un multiple de `RECORDSIZE`) sans copie complète, et supprime l'image (`finally` + tâche de
  fond de la réponse). `manifest.json` **en dernier** (une archive tronquée n'en a pas).
- Route `server/api/admin.py` : `backup_access` = session admin **ou** jeton `orgbk_…`
  (`AuthService.resolve_api_key`, table `api_key`, jamais accepté par `resolve` comme session), jeton
  limité aux adresses privées / de bouclage (`is_local_address`). Attention : `ipaddress` classe aussi les
  plages de documentation (`203.0.113.0/24`…) comme privées → adresse publique de test : `86.245.12.7`.
- Interface : `ds.backup_url(uploads)` (web : `ui.download.from_url`, avec le cookie) ;
  `ds.save_backup(uploads, folder)` (client bureau seulement : `ApiClient.save` en flux vers
  `system.downloads_dir()`, appelé par `run.io_bound`). Jetons : `ds.account.backup_keys / create_backup_key
  / revoke_backup_key`.
- Restauration : `organizer/server/restore.py` (`prepare` en un passage `tarfile` mode `r|*` → dossier
  `.restauration-<date>` vérifié ; `swap` = renommages, anciennes données dans `avant-restauration-<date>/`)
  piloté par `deploy/restore.sh` (arrêt / redémarrage du service entre les deux). Pas de
  `tarfile` `filter=` (absent de Python 3.11.2 du Pi) : les noms admis sont vérifiés un par un et chaque
  fichier est écrit à la main.
- Tests : `tests/test_backup.py`, `tests/test_restore.py` (script de bout en bout avec faux `systemctl` /
  `sudo` en tête du `PATH`, `ORG_WAIT_TRIES=1`) ; simulateur : `await user.download.next()` récupère le
  téléchargement.
- ⚠️ Faux service pour un essai manuel : enregistrer le PID **du programme python** (`nohup … &` sur sa
  propre ligne, pas `cd … && nohup … &`, dont `$!` est un sous-shell) ; sinon « stop » ne l'arrête pas et
  l'ancien serveur continue de servir les fichiers déplacés (faux échec de restauration constaté).

## Migrations de la base (1.0.0)

- `organizer/core/migrations.py` : `init_db(engine)` → `migrate(engine)`. Numéro de schéma = `PRAGMA
  user_version` (0 = avant 1.0.0, 1 = 1.0.0, point de départ `_baseline`). Base neuve : `create_all` +
  dernier numéro. Base existante : `create_all` (tables nouvelles), copie de sécurité si une étape a
  `changes_data`, puis chaque étape dans **sa** transaction avec le numéro. `SchemaTooNew` si la base est
  plus récente que le code.
- ⚠️ Le pilote `sqlite3` n'ouvre pas de transaction avant un `ALTER TABLE` : un `engine.begin()` ordinaire
  ne l'annule **pas** (constaté par `test_failed_step_is_rolled_back`). Les étapes passent donc par
  `_transactional_engine` (`isolation_level = None` + `BEGIN` émis sur l'événement `begin`, recette de la
  documentation de SQLAlchemy), réservé aux migrations.
- Ajouter une colonne : modèle + `Migration(n + 1, "…", lambda conn: add_column(conn, "task", "x", "DATE"))`
  à la fin de `MIGRATIONS` ; `NOT NULL` exige un `DEFAULT` en SQL. Ne jamais modifier une étape publiée ;
  une étape doit tolérer une table déjà au dernier schéma.
- Garde-fou : `tests/fixtures/organizer-0.9.0.db`, créée par le **vrai code de la v0.9.0** (`git worktree`
  sur l'étiquette, script hors dépôt) ; `test_old_database_reaches_the_current_schema` compare son schéma
  migré (`table_columns`) à celui d'une base neuve. Ne jamais modifier ce fichier.

## Versions et mises à jour

- `organizer/__init__.py` : `__version__` (**1.2.0** depuis le 11/11/2026 — notes, liens à partager ; 1.1.0 le 10/11/2026 — calendrier, événements,
  notifications ; 1.0.0 le 9/11/2026 ; ensuite MINEUR = nouveauté,
  CORRECTIF = correction, MAJEUR = incompatibilité) et `API_VERSION`.
  **À chaque version livrée** (passage sur `main` approuvé par l'utilisateur) : augmenter `__version__`, l'indiquer dans
  l'historique de `specifications.md`, proposer l'étiquette git `v<version>`. Augmenter `API_VERSION`
  seulement si un client plus ancien ne peut plus fonctionner (route supprimée / modifiée de façon
  incompatible) — préférer des changements compatibles (champs ajoutés avec valeur par défaut).
- Comparaison et messages : `organizer/versioning.py` ; route publique `GET /api/v1/version` ; bandeau du
  client : `DesktopClient.version_check` (cache 10 min) → `UiContext.banners` → `app_frame`. Le client
  compare aussi la version **sur le disque** (`installed_version()`, lue dans `organizer/__init__.py`) à
  celle **en mémoire** : un client qui tourne depuis avant un `git pull` affiche « quittez puis relancez »
  (cas rencontré : bandeau trompeur après la mise à jour du Pi).
- **Serveur** : `deploy/install.sh` (+ `deploy/common.sh` : `org_target_user` = `SUDO_USER` sous sudo, sinon
  `id -un`, refus en root direct ; `org_as_user` / `org_as_root`). Le service systemd est **généré**
  (`--print-service` pour le voir), plus de fichier statique. Tests : `tests/test_deploy.py`
  (`ORG_EUID=0` simule sudo, `ORG_UNIT_PATH` déplace le fichier de service). Essai complet sans droits
  administrateur : faux `sudo` / `systemctl` en tête du `PATH` (le faux `systemctl restart` lance le serveur
  d'après le fichier généré). ⚠️ Pour arrêter un serveur de test, viser le **programme** python
  (`ps -eo pid,args | awk '$2 ~ /python/ && /motif/'`), jamais `pkill -f motif` (tue son propre shell).
- **Version de test** : `deploy/install_test.sh` (Pi) bascule la même installation (même service, mêmes
  données) sur `cloclo` (ou `--branch x`), `--main` y revient ; copie de la base `avant-<branche>-<date>.db`
  en quittant main ; refuse de revenir sur main si la base a un schéma plus récent que celui de main
  (`SCHEMA_VERSION`), et reste alors sur la branche de test. Ensuite `deploy/update.sh` suit la branche
  active. Tests : `tests/test_deploy.py` (dépôt distant + clone temporaires, faux paquet `migrations`).
- Scripts : `install/linux/update.sh`, `install/windows/update.ps1` (+ `.bat`), `deploy/update.sh` (Pi). Les
  scripts bash sont enveloppés dans une fonction `main` (git pull peut les modifier pendant leur exécution).
  L'installeur retient ses options (`install.json`, `--reuse`).
- `install.sh` fait `cd "$ROOT"` : `python -m organizer…` doit trouver le paquet d'où qu'on le lance.

## Historique détaillé (ancien « État actuel » de CLAUDE.md)

- ✅ Étape 0 : venv, dépendances, spécification.
- ✅ Étape 1 : cœur métier (`organizer/core/`).
- ✅ Étape 2 : serveur (`organizer/server/`) — sessions, API REST, pièces jointes, pages provisoires
  /login, /setup, service systemd.
- 474 tests au total (+1 réservé à Windows).
- ✅ Étape 3 : interface (`organizer/ui/`) — thème, layout, cartes, éditeur, accueil, liste.
- ✅ Étape 4 : éditeur markdown façon Obsidian (`components/markdown_editor.*`).
- ✅ Étape 5 : liste filtrable / triable / regroupable, recherche Ctrl+K, réglages, dupliquer, heure.
- ✅ Étape 6 : boards personnalisés, pages `/kanban` et `/matrix`, glisser-déposer souris / tactile,
  Ctrl+drop ; puis kanbans pleine page, colonnes repliables / redimensionnables, reclassement (urgence +
  rang).
- ✅ Étape 7 : client bureau (fenêtre native, `RemoteDataSource` via l'API, connexion par jeton, ouverture
  des fichiers locaux, notifications des rappels). Vérifié sous Linux (GTK) ; **Windows** : installé et lancé (Python 3.13 ; 3.14+ refusé par l'installeur, faute de pythonnet), suite de tests verte ; usage réel encore peu essayé.
  Puis : arrière-plan, instance unique, raccourcis globaux, installeurs, icône « Post-it en vrac »
  (source : `organizer/assets/organizer.svg`).
- ✅ Étape 8 : temps réel (SSE), PWA, HTTPS facultatif, finitions. Feuille de route terminée.
- ✅ Mise en ligne (version 0.9.0) : derrière Cloudflare Tunnel (cookie `Secure`, en-têtes, vraie IP),
  durcissement (docs, anti force brute par identifiant, journal, `--host`, mots de passe de 12), sauvegarde
  / restauration (borg), guide dans le README. Pièces jointes : sélecteur réparé, dépôt de fichiers.
- Tests lancés sur le Pi (**Python 3.11.2**) : 345 / 350 au premier passage ; deux causes corrigées :
  `tarfile` `extract(filter=…)` absent avant 3.11.4 (ne jamais l'utiliser, même dans un test) ; **langue du
  Pi en Latin-1** → sortie de Python en Latin-1, plantage sur le premier emoji (`deploy/restore.sh`). D'où
  `PYTHONUTF8=1` dans le service généré et dans `restore.sh` (+ `PYTHONIOENCODING=utf-8`),
  `restore._utf8_output()`, et les tests du script lancés avec `PYTHONIOENCODING=latin-1`. Tout nouveau
  programme Python lancé en ligne de commande sur le Pi doit en faire autant.
- ✅ **Version 1.2.0** (11/11/2026) : 📝 notes (markdown, cases triées, liens internes, liens retour, partage),
  liens à partager (adresse publique, page `/open`, protocole `organizer://`), règle des comptes désactivés.
- ✅ **Version 1.1.0** (10/11/2026) : calendrier, événements (agenda, partage modifiable / lecture seule,
  bascule tâche ↔ événement), notifications, pictogrammes de partage, conflits de noms tags / projets.
- ✅ **Version 1.0.0** (9/11/2026) : migrations de la base en place ; client bureau validé sous Linux et
  Windows. Reste à faire par l'utilisateur : essai réel de la sauvegarde borg et d'une restauration (TODO).
- Feuille de route complète : `specifications.md` §11.
