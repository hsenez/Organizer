#!/usr/bin/env bash
# Mise à jour du client bureau Organizer sous Linux :
#   1. arrête le client s'il tourne (il garde l'ancien code en mémoire) ;
#   2. récupère la nouvelle version (git pull) ;
#   3. relance l'installeur avec les options de la première installation (dépendances, lanceur, icônes,
#      raccourcis) ;
#   4. relance le client en arrière-plan s'il tournait.
set -euo pipefail

# Tout est dans une fonction : bash lit un script au fil de l'eau, or « git pull » peut modifier ce fichier
# pendant qu'il s'exécute ; une fonction est lue en entier avant de démarrer.
main() {
    local root python was_running=0 before after
    root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
    python="$root/.venv/bin/python"
    cd "$root"
    [[ -x "$python" ]] || { echo "❌ Organizer n'est pas installé ici : lancez install/linux/install.sh."; exit 1; }
    command -v git >/dev/null || { echo "❌ git est introuvable."; exit 1; }

    if "$python" -c 'import sys; from organizer.client import instance, system; sys.exit(0 if instance.forward(system.config_dir(), "ping") else 1)' 2>/dev/null; then
        was_running=1
        echo "⏻ Arrêt du client en cours d'exécution"
        "$python" run_client.py --quit || true
        sleep 2
    fi

    before="$(git rev-parse HEAD)"
    echo "⬇️  Récupération de la nouvelle version (git pull)"
    if ! git pull --ff-only; then
        echo "❌ git pull a échoué (modifications locales ? autre branche ?). Rien n'a été changé."
        [[ $was_running == 1 ]] && relaunch "$python"
        exit 1
    fi
    after="$(git rev-parse HEAD)"
    if [[ "$before" == "$after" ]]; then
        echo "✅ Déjà à jour."
    else
        echo "📝 Changements :"
        git log --oneline "$before..$after" | sed 's/^/   /'
    fi

    "$root/install/linux/install.sh" --reuse

    [[ $was_running == 1 ]] && relaunch "$python"
    echo "🏷️  Version installée : $("$python" -c 'import organizer; print(organizer.__version__)')"
}

relaunch() {
    echo "▶️  Relance du client en arrière-plan (Ctrl+Alt+O pour l'ouvrir)"
    setsid "$1" run_client.py --hidden >/dev/null 2>&1 < /dev/null &
}

main "$@"
