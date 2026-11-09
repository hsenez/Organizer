#!/usr/bin/env bash
# Version de test du serveur Organizer : bascule l'installation sur la branche « cloclo » (travail en
# cours, pas encore validé), ou la ramène sur « main ».
#
#   deploy/install_test.sh            passe sur cloclo (ou la met à jour), puis deploy/install.sh --reuse
#   deploy/install_test.sh --main     revient sur main, puis deploy/install.sh --reuse
#   deploy/install_test.sh --branch autre-branche
#   (les autres options sont transmises à deploy/install.sh ; sudo accepté comme pour install.sh)
#
# C'est le même service, sur le même port, avec les MÊMES DONNÉES : seule la version du code change.
# Ensuite, deploy/update.sh met à jour la branche active (cloclo reste cloclo jusqu'au retour sur main).
#
# Précautions :
#   - avant de quitter main, une copie de la base est faite dans le dossier des données
#     (avant-<branche>-<date>.db) : la version de test peut faire évoluer la base (migrations) ;
#   - au retour sur main, si la base a été migrée par la version de test et que main ne la connaît pas
#     encore, le script refuse et laisse le serveur sur la version de test (main refuserait de démarrer).
#     Il suffit d'attendre que la version de test soit passée sur main, ou de remettre la copie.
set -euo pipefail

# Tout est dans une fonction : changer de branche modifie ce fichier pendant qu'il s'exécute ; une
# fonction est lue en entier avant de démarrer.
main() {
    ORG_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    # shellcheck source=deploy/common.sh
    source "$ORG_ROOT/deploy/common.sh"
    ORG_USER="$(org_target_user)"

    local branch="cloclo" passthrough=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --main) branch="main"; shift ;;
            --branch) branch="${2:?--branch attend un nom de branche}"; shift 2 ;;
            -h|--help) sed -n '2,19p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
            *) passthrough+=("$1"); shift ;;
        esac
    done

    local git=(org_as_user git -C "$ORG_ROOT")
    local current remote
    current="$("${git[@]}" rev-parse --abbrev-ref HEAD)"
    # Dépôt d'où vient la branche actuelle (souvent « origin ») ; à défaut, origin.
    remote="$("${git[@]}" config "branch.$current.remote" 2>/dev/null || echo origin)"

    # Des fichiers suivis modifiés à la main sur le Pi seraient emportés (ou bloqueraient) le changement.
    [[ -z "$("${git[@]}" status --porcelain --untracked-files=no)" ]] \
        || fail "Fichiers modifiés localement (git status) : rien n'a été changé."

    say "⬇️  Récupération de « $branch » depuis $remote"
    "${git[@]}" fetch --quiet "$remote" "$branch" \
        || fail "La branche « $branch » est introuvable sur $remote. Rien n'a été changé."

    org_load_conf
    local data_dir="${SAVED_DATA_DIR:-$ORG_ROOT/data}"
    if [[ "$current" == "main" && "$branch" != "main" ]]; then
        backup_database "$data_dir" "$branch"
    fi

    switch_to "$branch" "$remote"
    if [[ "$branch" == "main" && "$current" != "main" ]] && ! schema_supported "$data_dir"; then
        switch_to "$current" "$remote"
        fail "La base a été migrée par la version de test et « main » ne la connaît pas encore : le serveur reste sur « $current ». Attendez que cette version passe sur main, ou remettez la copie avant-*.db de $data_dir (service arrêté)."
    fi
    say "   $("${git[@]}" log -1 --format='%h %s (%cr)')"

    # Nouvelle version de l'installeur, avec les options de la dernière installation.
    exec bash "$ORG_ROOT/deploy/install.sh" --reuse "${passthrough[@]}"
}

# Se place sur la branche $1, alignée sur celle du dépôt $2 (sans jamais écraser un travail local).
switch_to() {
    local branch="$1" remote="$2"
    local git=(org_as_user git -C "$ORG_ROOT")
    if "${git[@]}" show-ref --verify --quiet "refs/heads/$branch"; then
        "${git[@]}" switch --quiet "$branch"
        "${git[@]}" merge --quiet --ff-only "$remote/$branch" \
            || fail "« $branch » a divergé de $remote/$branch sur ce Pi : à régler à la main (git status)."
    else
        "${git[@]}" switch --quiet -c "$branch" --track "$remote/$branch"
    fi
    say "🔀 Branche active : $branch"
}

# Copie cohérente de la base (API de sauvegarde de SQLite : correcte même service en marche).
backup_database() {
    local data_dir="$1" branch="$2" db="$1/organizer.db"
    [[ -f "$db" ]] || return 0
    local target
    target="$data_dir/avant-$branch-$(date +%Y%m%d-%H%M%S).db"
    org_as_user "${PYTHON:-python3}" - "$db" "$target" <<'PY'
import sqlite3, sys
source, target = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
with target:
    source.backup(target)
target.close(), source.close()
PY
    say "💾 Copie de la base : $target"
}

# Vrai si le code actuellement extrait sait ouvrir la base (numéro de schéma ≤ celui du code). Sans
# .venv (première installation) ou sans base, rien à vérifier.
schema_supported() {
    local db="$1/organizer.db" python="$ORG_ROOT/.venv/bin/python"
    [[ -f "$db" && -x "$python" ]] || return 0
    org_as_user env PYTHONPATH="$ORG_ROOT" "$python" - "$db" <<'PY'
import sqlite3, sys
from organizer.core.migrations import SCHEMA_VERSION
version = sqlite3.connect(sys.argv[1]).execute("PRAGMA user_version").fetchone()[0]
sys.exit(0 if version <= SCHEMA_VERSION else 1)
PY
}

main "$@"
