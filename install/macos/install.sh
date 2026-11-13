#!/usr/bin/env bash
# Installation du client bureau Organizer sous macOS (pour l'utilisateur courant, sans droits administrateur).
#
#   install/macos/install.sh                    installe (ou met à jour)
#   install/macos/install.sh --no-autostart     sans démarrage à l'ouverture de session
#   install/macos/install.sh --no-shortcuts     sans raccourcis clavier globaux
#   install/macos/install.sh --show-key Cmd+Alt+O --new-key Cmd+Alt+N    autres raccourcis
#   install/macos/install.sh --uninstall        retire l'application et le démarrage auto (garde le dossier)
#
# Étapes : cherche Python ≥ 3.11 (Homebrew, python.org…), crée le venv .venv, installe
# requirements-client.txt (pywebview y ajoute PyObjC), puis crée ~/Applications/Organizer.app et le
# démarrage automatique (python -m organizer.client.install_macos).
# Compatible avec le bash 3.2 livré avec macOS.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="$ROOT/.venv"
cd "$ROOT"   # python -m organizer… doit trouver le paquet, d'où qu'on lance le script
export PYTHONUTF8=1

say()  { printf '%s\n' "$*"; }
fail() { printf '❌ %s\n' "$*" >&2; exit 1; }

[[ "$(uname -s)" == "Darwin" ]] || fail "Ce script est pour macOS (Linux : install/linux/install.sh)."

if [[ "${1:-}" == "--uninstall" ]]; then
    [[ -x "$VENV/bin/python" ]] || fail "Pas de venv dans $VENV : rien à désinstaller."
    "$VENV/bin/python" "$ROOT/run_client.py" --quit || true
    exec "$VENV/bin/python" -m organizer.client.install_macos --uninstall
fi

say "📋 Installation du client bureau Organizer dans $ROOT"

# --- Python ≥ 3.11 (le python3 de macOS est souvent trop ancien) ---
version_ok() { "$1" -c 'import sys; sys.exit(sys.version_info < (3, 11))' >/dev/null 2>&1; }
find_python() {
    local candidate
    if [[ -n "${PYTHON:-}" ]]; then
        version_ok "$PYTHON" && { command -v "$PYTHON"; return 0; }
        return 1
    fi
    for candidate in python3.13 python3.12 python3.11 python3.14 \
        /opt/homebrew/bin/python3 /usr/local/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/Current/bin/python3 python3; do
        if command -v "$candidate" >/dev/null 2>&1 && version_ok "$candidate"; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

if [[ -x "$VENV/bin/python" ]] && ! version_ok "$VENV/bin/python"; then
    say "🧹 Le venv existant utilise un Python trop ancien : il est recréé"
    rm -rf "$VENV"
fi
if [[ ! -x "$VENV/bin/python" ]]; then
    PY="$(find_python)" || fail "Python ≥ 3.11 introuvable. Installez-le avec Homebrew (brew install python@3.13)
   ou depuis https://www.python.org/downloads/macos/, puis relancez ce script
   (variable PYTHON pour en désigner un : PYTHON=/chemin/python3 $0)."
    say "🐍 Création de l'environnement Python ($VENV) avec $("$PY" --version 2>&1)"
    "$PY" -m venv "$VENV"
fi

# --- dépendances ---
say "📦 Installation des dépendances (requirements-client.txt, quelques minutes la première fois)"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -r "$ROOT/requirements-client.txt" \
    || fail "L'installation des dépendances a échoué (voir les messages ci-dessus)."

# --- intégration au système ---
"$VENV/bin/python" -m organizer.client.install_macos ${1+"$@"}

say ""
say "🎉 Terminé ! Lancez « Organizer » depuis le Launchpad, Spotlight ou ~/Applications"
say "   (glissez-le dans le Dock pour l'y garder)."
say "   Fermer la fenêtre la cache : Organizer continue en arrière-plan (rappels, raccourcis)."
say "   Pour l'arrêter : ⌘Q, ou menu du compte → ⏻ Quitter Organizer."
say "   Notifications des rappels : autorisez « Éditeur de script » dans Réglages Système → Notifications."
