#!/usr/bin/env bash
# Restauration d'une sauvegarde Organizer (archive .tar téléchargée depuis Réglages → 🗄️ Données, ou par
# GET /api/v1/admin/backup) sur le serveur.
#
#   deploy/restore.sh organizer-20261108-203451.tar       restaure la base et les pièces jointes
#   deploy/restore.sh --db-only organizer.tar               restaure la base seule (pièces jointes inchangées)
#   borg export-tar /chemin/depot::archive - | deploy/restore.sh -      (lit l'archive sur l'entrée standard)
#   deploy/restore.sh --yes organizer.tar                   sans demander de confirmation
#   deploy/restore.sh --force organizer.tar                 accepte une archive d'une version plus récente
#   deploy/restore.sh --data-dir /srv/organizer --no-service organizer.tar   (serveur hors service systemd,
#                                                            à arrêter vous-même avant)
#
# Rien n'est effacé : les données actuelles sont déplacées dans <données>/avant-restauration-<date>/ (avec un
# LISEZMOI.txt qui explique comment y revenir).
#
# ─────────────────────────────────────────────────────────────────────────────────────────────────────────
# VUE D'ENSEMBLE DES ÉTAPES
#   1. Vérification (serveur en marche) : l'archive est extraite dans <données>/.restauration-<date>/ et
#      contrôlée (contenu attendu, manifeste, empreintes SHA-256, intégrité de la base, version). Au moindre
#      problème, on s'arrête là : rien n'a changé.
#   2. Confirmation (résumé : date de la sauvegarde, nombre de tâches…).
#   3. Arrêt du service, échange des dossiers (données actuelles mises de côté), redémarrage.
#   4. Vérification que le serveur répond.
#
# Le travail sur les fichiers se fait sous VOTRE compte (comme le serveur, voir deploy/install.sh) ; seuls
# l'arrêt et le redémarrage du service passent par sudo.
# ─────────────────────────────────────────────────────────────────────────────────────────────────────────

set -euo pipefail
# Sorties de Python en UTF-8, quelle que soit la langue du système (un Pi réglé en Latin-1 faisait planter
# l'affichage du résumé sur le premier emoji).
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8

ORG_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=deploy/common.sh
source "$ORG_ROOT/deploy/common.sh"

usage() { sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0; }

# --- Ligne de commande -------------------------------------------------------------------------------------
archive="" data_dir="" db_only=0 assume_yes=0 force=0 use_service=1
while [[ $# -gt 0 ]]; do
    case "$1" in
        --db-only) db_only=1; shift ;;
        --yes|-y) assume_yes=1; shift ;;
        --force) force=1; shift ;;
        --data-dir) data_dir="${2:?--data-dir attend un dossier}"; shift 2 ;;
        --no-service) use_service=0; shift ;;
        -h|--help) usage ;;
        -) [[ -z "$archive" ]] || fail "Une seule archive à la fois."; archive="-"; shift ;;
        -*) fail "Option inconnue : $1 (voir --help)" ;;
        *) [[ -z "$archive" ]] || fail "Une seule archive à la fois."; archive="$1"; shift ;;
    esac
done
[[ -n "$archive" ]] || fail "Indiquez l'archive à restaurer (voir --help)."

ORG_USER="$(org_target_user)"
python="$ORG_ROOT/.venv/bin/python"
[[ -x "$python" ]] || fail "Environnement Python absent ($python) : lancez d'abord deploy/install.sh."

# Dossier des données, port, adresse et HTTPS : ceux de la dernière installation (deploy/server.conf).
org_load_conf
data_dir="${data_dir:-${SAVED_DATA_DIR:-$ORG_ROOT/data}}"
[[ "$data_dir" == /* ]] || data_dir="$PWD/$data_dir"
port="${SAVED_PORT:-2603}" host="${SAVED_HOST:-0.0.0.0}"
https=0; [[ -n "${SAVED_SSL_CERT:-}" ]] && https=1
if [[ "$archive" != "-" ]]; then
    [[ -f "$archive" ]] || fail "Archive introuvable : $archive"
    [[ "$archive" == /* ]] || archive="$PWD/$archive"
fi
[[ -d "$data_dir" ]] || fail "Dossier des données introuvable : $data_dir (voir --data-dir)."
# Sans confirmation possible (archive lue sur l'entrée standard et pas de terminal), il faut --yes.
if [[ $assume_yes == 0 ]] && ! { : </dev/tty; } 2>/dev/null; then
    fail "Pas de terminal pour confirmer : ajoutez --yes."
fi

stamp="$(date +%Y%m%d-%H%M%S)"
staging="$data_dir/.restauration-$stamp"
# Quoi qu'il arrive (erreur, Ctrl+C, refus), le dossier de travail ne doit pas rester.
cleanup() { [[ -d "$staging" ]] && rm -rf "$staging"; return 0; }
trap cleanup EXIT

# Le module Python s'exécute depuis le dossier du projet (python -m organizer… doit trouver le paquet).
restore_py() { (cd "$ORG_ROOT" && org_as_user "$python" -m organizer.server.restore "$@"); }

# ═════════════════════════════════════════════════════════════════════════════════════════════════════════
# 1. VÉRIFICATION
# ═════════════════════════════════════════════════════════════════════════════════════════════════════════
say "🔎 Vérification de l'archive ($([[ "$archive" == "-" ]] && echo "entrée standard" || echo "$archive"))…"
prepare_args=(prepare --staging "$staging")
[[ $db_only == 1 ]] && prepare_args+=(--db-only)
[[ $force == 1 ]] && prepare_args+=(--force)
restore_py "${prepare_args[@]}" "$archive" || fail "Restauration abandonnée : rien n'a été modifié."

# ═════════════════════════════════════════════════════════════════════════════════════════════════════════
# 2. CONFIRMATION
# ═════════════════════════════════════════════════════════════════════════════════════════════════════════
say ""
say "Les données actuelles ($data_dir) vont être remplacées par cette sauvegarde. Elles sont mises de côté"
say "dans $data_dir/avant-restauration-$stamp/ (rien n'est effacé)."
if [[ $use_service == 1 ]]; then
    say "Le serveur sera arrêté quelques secondes : les modifications faites depuis la sauvegarde seront perdues."
fi
if [[ $assume_yes == 0 ]]; then
    printf 'Restaurer ? [o/N] '
    read -r answer </dev/tty || answer=""
    [[ "$answer" =~ ^[oOyY] ]] || { say "Abandon : rien n'a été modifié."; exit 0; }
fi

# ═════════════════════════════════════════════════════════════════════════════════════════════════════════
# 3. ARRÊT, ÉCHANGE, REDÉMARRAGE
# ═════════════════════════════════════════════════════════════════════════════════════════════════════════
if [[ $use_service == 1 ]]; then
    say "⏸️  Arrêt du service $ORG_SERVICE"
    org_as_root systemctl stop "$ORG_SERVICE"
fi
swap_args=(swap --data-dir "$data_dir" --staging "$staging" --stamp "$stamp")
[[ $db_only == 1 ]] && swap_args+=(--db-only)
if ! aside="$(restore_py "${swap_args[@]}")"; then
    [[ $use_service == 1 ]] && org_as_root systemctl start "$ORG_SERVICE"
    fail "Échange impossible ; voir $data_dir/avant-restauration-$stamp/ s'il a été créé."
fi
say "📦 Données précédentes mises de côté : $aside"
if [[ $use_service == 0 ]]; then
    say "✅ Restauration terminée. Démarrez le serveur."
    exit 0
fi
say "▶️  Redémarrage du service $ORG_SERVICE"
org_as_root systemctl start "$ORG_SERVICE"

# ═════════════════════════════════════════════════════════════════════════════════════════════════════════
# 4. VÉRIFICATION
# ═════════════════════════════════════════════════════════════════════════════════════════════════════════
if version="$(org_wait_server "$port" "$https" "$(org_probe_address "$host")")"; then
    say "✅ Restauration terminée : Organizer $version répond."
    say "   Une fois vérifié, vous pouvez supprimer $aside"
else
    say "⚠️  Le serveur ne répond pas : journalctl -u $ORG_SERVICE -n 50"
    say "   Pour revenir aux données précédentes : voir $aside/LISEZMOI.txt"
    exit 1
fi
