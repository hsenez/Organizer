#!/usr/bin/env bash
# Mise à jour du serveur Organizer :
#   git pull → deploy/install.sh --reuse (dépendances, service systemd régénéré si besoin, redémarrage,
#   vérification de la version). Les données ne sont pas touchées ; les nouvelles tables sont créées au
#   démarrage.
#   deploy/update.sh          (ou sudo deploy/update.sh : git tourne quand même sous votre compte)
set -euo pipefail

# Tout est dans une fonction : « git pull » peut modifier ce fichier pendant qu'il s'exécute ; une fonction
# est lue en entier avant de démarrer.
main() {
    ORG_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    # shellcheck source=deploy/common.sh
    source "$ORG_ROOT/deploy/common.sh"
    ORG_USER="$(org_target_user)"
    local before after
    before="$(org_as_user git -C "$ORG_ROOT" rev-parse HEAD)"
    say "⬇️  Récupération de la nouvelle version (git pull)"
    org_as_user git -C "$ORG_ROOT" pull --ff-only \
        || fail "git pull a échoué (modifications locales ? autre branche ?). Rien n'a été changé."
    after="$(org_as_user git -C "$ORG_ROOT" rev-parse HEAD)"
    if [[ "$before" == "$after" ]]; then
        say "✅ Code déjà à jour (le service est quand même vérifié et relancé)."
    else
        org_as_user git -C "$ORG_ROOT" log --oneline "$before..$after" | sed 's/^/   /'
    fi
    # Nouvelle version de l'installeur, avec les options de la dernière installation.
    exec bash "$ORG_ROOT/deploy/install.sh" --reuse "$@"
}

main "$@"
