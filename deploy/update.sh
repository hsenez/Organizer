#!/usr/bin/env bash
# Mise à jour du serveur Organizer sur le Raspberry Pi :
#   git pull → dépendances (requirements.txt) → redémarrage du service → vérification de la version.
# Les données (data/) ne sont pas touchées ; les nouvelles tables sont créées au démarrage.
#   deploy/update.sh            (sudo est demandé pour redémarrer le service)
set -euo pipefail

# Tout est dans une fonction : « git pull » peut modifier ce fichier pendant qu'il s'exécute.
main() {
    local root python before after port
    root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    python="$root/.venv/bin/python"
    cd "$root"
    [[ -x "$python" ]] || { echo "❌ Pas de venv dans $root/.venv : voir README.md (Déploiement)."; exit 1; }

    before="$(git rev-parse HEAD)"
    echo "⬇️  Récupération de la nouvelle version (git pull)"
    git pull --ff-only || { echo "❌ git pull a échoué (modifications locales ?). Rien n'a été changé."; exit 1; }
    after="$(git rev-parse HEAD)"
    if [[ "$before" == "$after" ]]; then
        echo "✅ Déjà à jour."
    else
        git log --oneline "$before..$after" | sed 's/^/   /'
    fi

    echo "📦 Dépendances (requirements.txt)"
    "$python" -m pip install --quiet -r requirements.txt

    if systemctl list-unit-files organizer.service >/dev/null 2>&1 \
        && systemctl list-unit-files organizer.service | grep -q organizer; then
        echo "🔁 Redémarrage du service organizer"
        sudo systemctl restart organizer
        port="${ORGANIZER_PORT:-2603}"
        for _ in $(seq 1 30); do
            if version="$(curl -fsS "http://127.0.0.1:$port/api/v1/version" 2>/dev/null)"; then
                echo "✅ Serveur relancé : $version"
                return 0
            fi
            sleep 1
        done
        echo "⚠️  Le serveur ne répond pas encore : journalctl -u organizer -n 50"
        exit 1
    else
        echo "ℹ️  Service systemd « organizer » absent : relancez run_server.py vous-même."
    fi
    echo "🏷️  Version : $("$python" -c 'import organizer; print(organizer.__version__)')"
}

main "$@"
