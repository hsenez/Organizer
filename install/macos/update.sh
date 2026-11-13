#!/usr/bin/env bash
# Mise à jour du client bureau Organizer sous macOS :
#   1. arrête le client s'il tourne (il garde l'ancien code en mémoire) ;
#   2. récupère la nouvelle version (git pull) ;
#   3. relance l'installeur avec les options de la première installation (dépendances, application,
#      démarrage automatique, raccourcis) ;
#   4. relance le client en arrière-plan s'il tournait.
# Compatible avec le bash 3.2 livré avec macOS.
set -euo pipefail

# Tout est dans une fonction : bash lit un script au fil de l'eau, or « git pull » peut modifier ce fichier
# pendant qu'il s'exécute ; une fonction est lue en entier avant de démarrer.
main() {
    local root python was_running=0 before after
    root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
    python="$root/.venv/bin/python"
    cd "$root"
    export PYTHONUTF8=1
    [[ -x "$python" ]] || { echo "❌ Organizer n'est pas installé ici : lancez install/macos/install.sh."; exit 1; }
    command -v git >/dev/null || { echo "❌ git est introuvable (xcode-select --install)."; exit 1; }

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
        if [[ $was_running == 1 ]]; then relaunch "$python"; fi
        exit 1
    fi
    after="$(git rev-parse HEAD)"
    if [[ "$before" == "$after" ]]; then
        echo "✅ Déjà à jour."
    else
        echo "📝 Changements :"
        git log --oneline "$before..$after" | sed 's/^/   /'
    fi

    "$root/install/macos/install.sh" --reuse

    if [[ $was_running == 1 ]]; then relaunch "$python"; fi
    echo "🏷️  Version installée : $("$python" -c 'import organizer; print(organizer.__version__)')"
}

relaunch() {
    echo "▶️  Relance du client en arrière-plan (Ctrl+Alt+O ou Organizer dans le Launchpad pour l'ouvrir)"
    # nohup : le client survit à la fermeture du Terminal (pas de setsid sous macOS).
    nohup "$1" run_client.py --hidden >/dev/null 2>&1 < /dev/null &
    disown 2>/dev/null || true
}

main ${1+"$@"}
