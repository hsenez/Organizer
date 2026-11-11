# Notes pour Claude — Notes et notifications

Complément de `CLAUDE.md` (à la racine), à lire avant de modifier ce domaine.

## Notes

- `core/services/notes.py` (`NoteService`, `sv.notes` / `ds.notes`, `RemoteNotes`) : sous-classe
  d'`ItemService` sans table de liens (`link_model = None`) ; texte de la note = colonne `notes` (héritée
  d'`ItemBase`). Droits comme `AgendaService` ; `NotePin` = épingle **par utilisateur** (hors `_ITEM_OF` :
  ne notifie pas). Tables `note*` dans `UNDOABLE_TABLES`, `_ITEM_OF` / `_MAIN` (notifications), et
  traitées par la suppression / fusion de tags et projets (`labels.py`).
- Liens internes : `rules.parse_ref`, `refs_in`, `ref_link`, `ref_pattern` ; `NoteService.resolve(refs)`
  (titre actuel pour le lecteur, `available=False` sinon) et `backlinks(ref)` (`LIKE` puis revérification).
  Routes `/refs/resolve`, `/refs/backlinks`. `ds.web_url(path)` : adresse web à copier (None côté web =
  `location.origin`).
- **Liens à partager** : `organizer/links.py` (bibliothèque standard seulement : importé par le lanceur) —
  `page_path`, `open_path`, `scheme_url`, `from_url` (miroir JS : `refFromUrl` dans `markdown_editor.js`,
  collage → `[](kind:id)`). `components/copy_link.py` (`install_copy_script` dans `app_frame`,
  `copy_link_button` : copie dans le navigateur au clic, `js_handler`). Adresse publique :
  `AccountService.public_url / set_public_url` (`UserService.get_setting / set_setting`, table
  `app_setting`), `ds.web_url`. Page `server/open_page.py` (`/open/<type>/<id>`, HTML statique). Client
  bureau : argument `link` du lanceur → `instance.forward(..., "open", {"ref"})` →
  `DesktopClient.open_item` ; démarrage direct : `start_url` = page de l'élément + `&launch=`. Installeurs :
  `install.py` (`MimeType`, `%u`, `register_scheme` → `xdg-mime default`), `install.ps1` (clé
  `HKCU:\Software\Classes\organizer`). Vérifier la déclaration Linux en bac à sable
  (`XDG_DATA_HOME` / `XDG_CONFIG_HOME` temporaires) pour ne pas toucher l'installation de l'utilisateur.
- Emojis proposés : `enums.DEFAULT_EMOJIS`, préférence `EMOJIS_PREF`, `rules.parse_emojis` ;
  `components/emoji_picker.py` (`emoji_choices` tolérant, `emoji_grid`, `emoji_button`) ; réglages →
  Apparence (`_emojis`) et dialogue des projets.
- Page `ui/pages/notes.py` (`NotesView`, `app_frame(wide=True)`) : liste `notes-list` + note `notes-view`
  (CSS `.notes-page.has-note` pour le téléphone). Un gestionnaire dont le bouton est détruit par
  `_render_view` doit passer par `with self.root:` pour `ui.*` (`_set_url`). `ctx.open_note` (UiContext)
  = ouvrir une note dans la page (None ailleurs : navigation vers `/notes?note=`). Modifiée ailleurs :
  `_on_refresh` met à jour si pas de frappe depuis `TYPING_SECONDS`, sinon bandeau `notes-stale`.
- **Éditeur markdown** (`markdown_editor.js`) : props `readonly` (Compartment), `sortChecks`
  (`sortedChecklist` : une transaction, `userEvent "input.check"`), `refPicker` (« [[ » → `ref-request`),
  `refs` (titres, posés sur `view.organizer` + effet `redraw` — y compris après la création de la vue) ;
  méthodes `format(kind)` (barre : `markdown_toolbar`, boutons en `js_handler` → `getElement(id).format`,
  `mousedown` sans action par défaut pour garder la sélection) et `insertRef(text)`. `RefWidget` (pastille,
  `ignoreEvent` faux pour que le clic arrive à `mousedown`), `openTarget` vide le texte (`flush`) avant
  `open-link`.
- `components/ref_links.py` : `RefLinks` (résout les nouveaux liens à chaque `update:value`), `RefPicker`
  (dialogue « Lier à… »), `open_ref`. Utilisé par la page Notes et `ItemEditor._notes` (notes des tâches /
  événements ; lecture seule d'un événement = `MarkdownEditor(readonly=True)`).
- Partagés : `components/sharing.py` (`public_switch`, `share_editor`, marqueurs `editor-shares`,
  `editor-share-<id>`), `item_editor.label_selects` / `tag_ids_from`.
- Tests : `tests/test_notes.py`, `tests/test_notes_pages.py` (le simulateur ne déclenche pas
  `update:model-value` avec `.type()` : le déclencher à la main ; `trigger("update:value", texte)` pour une
  frappe dans l'éditeur), `test_client.py::test_notes_through_api_match_local`. Le JS (tri, boutons, « [[ »,
  pastilles) se vérifie dans Firefox (BiDi : `getElement(document.querySelector('.note-text')).view`).

## Notifications

- `core/services/notifications.py` : `record(session, actor_id, label, changes)` est appelée par
  `BaseService.uow` (`UnitOfWork(before_commit=…)`, dans la transaction, après l'historique) pour **toute**
  action avec libellé : les lignes modifiées (`Change`) donnent les éléments touchés (`_ITEM_OF` : tables →
  type d'élément + colonne) ; concernés = propriétaire + partages (+ parent pour une sous-tâche), moins
  l'auteur. Nouvelle table liée à une tâche / un événement : l'ajouter à `_ITEM_OF`. Table `notification`
  **hors** historique (pas `__undoable__`). Annuler / rétablir (session directe) ne notifie pas.
- `NotificationService` (`ds.notifications`) : `list`, `unread_count`, `mark_read(ids | None)` (renvoie le
  nombre de non lues restantes). Client : `unread_count` en cache (`NOTIFICATIONS_KEY`, oublié à chaque
  événement temps réel). Bulle : `layout.update_notification_badge` (rafraîchissement léger), marqueur
  `notifications-badge` ; page `ui/pages/notifications.py` (marqueurs `notification-<id>`,
  `notifications-read-all`).
