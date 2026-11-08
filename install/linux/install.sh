#!/usr/bin/env bash
# Installation du client bureau Organizer sous Linux (pour l'utilisateur courant, sans droits root).
#
#   install/linux/install.sh                    installe (ou met à jour)
#   install/linux/install.sh --no-autostart     sans démarrage à l'ouverture de session
#   install/linux/install.sh --no-shortcuts     sans raccourcis clavier globaux
#   install/linux/install.sh --show-key Meta+O --new-key Meta+N    autres raccourcis
#   install/linux/install.sh --uninstall        retire lanceur, icônes, raccourcis (garde le dossier)
#
# Étapes : vérifie Python ≥ 3.11 et WebKitGTK, crée le venv .venv, installe requirements-client.txt, puis
# ajoute lanceur, icônes, démarrage automatique et raccourcis (python -m organizer.client.install).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="$ROOT/.venv"
PYTHON="${PYTHON:-python3}"

say()  { printf '%s\n' "$*"; }
fail() { printf '❌ %s\n' "$*" >&2; exit 1; }

if [[ "${1:-}" == "--uninstall" ]]; then
    [[ -x "$VENV/bin/python" ]] || fail "Pas de venv dans $VENV : rien à désinstaller."
    "$VENV/bin/python" "$ROOT/run_client.py" --quit || true
    exec "$VENV/bin/python" -m organizer.client.install --uninstall
fi

say "📋 Installation du client bureau Organizer dans $ROOT"

# --- Python ---
command -v "$PYTHON" >/dev/null || fail "Python 3 introuvable (variable PYTHON pour en choisir un autre)."
"$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 11))' \
    || fail "Python ≥ 3.11 requis ($("$PYTHON" --version 2>&1) trouvé)."

# --- WebKitGTK (fenêtre native) ---
hint=""
if command -v pacman >/dev/null; then hint="sudo pacman -S webkit2gtk-4.1 gobject-introspection cairo"
elif command -v apt-get >/dev/null; then hint="sudo apt install gir1.2-webkit2-4.1 libgirepository-2.0-dev libcairo2-dev pkg-config python3-dev"
elif command -v dnf >/dev/null; then hint="sudo dnf install webkit2gtk4.1 gobject-introspection-devel cairo-devel python3-devel"
elif command -v zypper >/dev/null; then hint="sudo zypper install webkit2gtk-4_1 gobject-introspection-devel cairo-devel python3-devel"
fi
# Ce que charge la fenêtre : la description GObject de WebKit2 4.1 (chemins Arch, Fedora, Debian/Ubuntu…).
if ! compgen -G "/usr/lib*/girepository-1.0/WebKit2-4.1.typelib" >/dev/null \
    && ! compgen -G "/usr/lib/*/girepository-1.0/WebKit2-4.1.typelib" >/dev/null; then
    say "⚠️  WebKitGTK 4.1 semble absent : la fenêtre native ne pourra pas s'ouvrir."
    [[ -n "$hint" ]] && say "    À installer : $hint"
    say "    (sans lui, le client reste utilisable dans le navigateur : run_client.py --browser)"
fi

# --- venv et dépendances ---
if [[ ! -x "$VENV/bin/python" ]]; then
    say "🐍 Création de l'environnement Python ($VENV)"
    "$PYTHON" -m venv "$VENV"
fi
say "📦 Installation des dépendances (requirements-client.txt)"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
if ! "$VENV/bin/python" -m pip install --quiet -r "$ROOT/requirements-client.txt"; then
    say "❌ L'installation des dépendances a échoué (souvent PyGObject, qui se compile)."
    [[ -n "$hint" ]] && say "    Installez d'abord : $hint"
    exit 1
fi

# --- intégration au bureau ---
"$VENV/bin/python" -m organizer.client.install "$@"

say ""
say "🎉 Terminé ! Lancez « Organizer » depuis le menu des applications."
say "   Fermer la fenêtre la cache : Organizer continue en arrière-plan (rappels, raccourcis)."
say "   Pour l'arrêter : menu du compte → ⏻ Quitter Organizer (ou clic droit sur le lanceur)."
