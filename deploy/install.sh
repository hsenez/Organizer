#!/usr/bin/env bash
# Installation du serveur Organizer (Raspberry Pi ou toute machine Linux avec systemd).
#
#   deploy/install.sh                     installe (ou réinstalle) et démarre le service
#   sudo deploy/install.sh                idem : le service tourne quand même sous VOTRE compte, pas root
#   deploy/install.sh --port 2603 --data-dir /srv/organizer
#   deploy/install.sh --ssl-cert certs/organizer.pem --ssl-key certs/organizer-key.pem   (HTTPS)
#   deploy/install.sh --no-https          revient au HTTP simple
#   deploy/install.sh --reuse             reprend les options de la dernière installation (mises à jour)
#   deploy/install.sh --print-service     affiche le service systemd qui serait installé, sans rien changer
#   deploy/install.sh --uninstall         arrête et retire le service (garde le code, .venv et les données)
#
# Le script peut être relancé autant de fois qu'on veut : il ne refait que ce qui a changé.
#
# ─────────────────────────────────────────────────────────────────────────────────────────────────────────
# VUE D'ENSEMBLE DES ÉTAPES
#   0. Préparation : où est le projet, quel utilisateur, quelles options.
#   1. Vérifications : droits sur le dossier, Python ≥ 3.11, certificats HTTPS lisibles.
#   2. Environnement Python : .venv (créé une fois) + dépendances de requirements.txt.
#   3. Service systemd : fichier /etc/systemd/system/organizer.service généré, activé, (re)démarré.
#   4. Mémorisation des options (deploy/server.conf) pour les mises à jour.
#   5. Vérification finale : le serveur répond-il ? Affichage des adresses à ouvrir.
#
# QUI FAIT QUOI ? Le serveur doit tourner sous un compte ordinaire, jamais root (un serveur web en root
# donnerait tous les droits sur le Pi à quiconque trouverait une faille). Le compte retenu est celui qui
# tape la commande, même précédée de sudo (voir org_target_user dans deploy/common.sh). Ensuite :
#   - tout ce qui touche au projet (venv, pip, dossier des données, server.conf) est fait SOUS CE COMPTE
#     (org_as_user), pour que les fichiers lui appartiennent ;
#   - seules les opérations système (écrire dans /etc/systemd/system, systemctl) passent par
#     l'administrateur (org_as_root : sudo, qui demande le mot de passe si besoin).
# ─────────────────────────────────────────────────────────────────────────────────────────────────────────

# Arrêt immédiat à la première erreur (-e), sur une variable non définie (-u), et si une commande échoue
# au milieu d'un enchaînement « a | b » (pipefail) : on préfère s'arrêter que d'installer à moitié.
set -euo pipefail

# ═════════════════════════════════════════════════════════════════════════════════════════════════════════
# 0. PRÉPARATION
# ═════════════════════════════════════════════════════════════════════════════════════════════════════════

# Dossier du projet = le dossier parent de deploy/, d'où que l'on lance le script.
ORG_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Fonctions communes avec deploy/update.sh : say, fail, org_target_user, org_as_user, org_as_root,
# org_wait_server, et les constantes ORG_SERVICE (« organizer ») et ORG_UNIT_PATH (fichier du service).
# shellcheck source=deploy/common.sh
source "$ORG_ROOT/deploy/common.sh"
# Fichier où sont retenues les options de la dernière installation (non versionné, voir .gitignore).
CONF="$ORG_ROOT/deploy/server.conf"

# --help : affiche l'en-tête de ce fichier (lignes de commentaire du début, jusqu'à la vue d'ensemble).
usage() { sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0; }

# --- 0.a Lecture de la ligne de commande -------------------------------------------------------------
# Les valeurs vides signifient « non précisé » : elles seront complétées plus bas (options retenues ou
# valeurs par défaut). « action » dit ce que l'on fait : installer, seulement afficher le service, ou
# désinstaller.
port="" data_dir="" ssl_cert="" ssl_key="" no_https=0 reuse=0 action="install"
while [[ $# -gt 0 ]]; do
    case "$1" in
        # ${2:?message} : arrête le script avec ce message si la valeur de l'option est absente.
        --port) port="${2:?--port attend un numéro}"; shift 2 ;;
        --data-dir) data_dir="${2:?--data-dir attend un dossier}"; shift 2 ;;
        --ssl-cert) ssl_cert="${2:?--ssl-cert attend un fichier}"; shift 2 ;;
        --ssl-key) ssl_key="${2:?--ssl-key attend un fichier}"; shift 2 ;;
        --no-https) no_https=1; shift ;;
        --reuse) reuse=1; shift ;;
        --print-service) action="print"; shift ;;
        --uninstall) action="uninstall"; shift ;;
        -h|--help) usage ;;
        *) fail "Option inconnue : $1 (voir --help)" ;;
    esac
done

# --- 0.b Utilisateur du service ------------------------------------------------------------------------
# Celui qui lance la commande ; s'il l'a lancée avec sudo, sudo nous le donne dans SUDO_USER. Lancé
# directement en root (sans sudo), le script s'arrête : on ne saurait pas pour qui installer.
ORG_USER="$(org_target_user)"
# Son groupe principal (souvent du même nom) : le service tourne avec ce groupe.
ORG_GROUP="$(id -gn "$ORG_USER")"

# --- 0.c Options effectives ----------------------------------------------------------------------------
# Priorité : 1) la ligne de commande, 2) les options retenues (seulement avec --reuse, que passe
# deploy/update.sh), 3) les valeurs par défaut.
SAVED_PORT="" SAVED_DATA_DIR="" SAVED_SSL_CERT="" SAVED_SSL_KEY=""
if [[ $reuse == 1 && -f "$CONF" ]]; then
    # server.conf contient des lignes SAVED_PORT=… : le « sourcer » définit ces variables.
    # shellcheck disable=SC1090
    source "$CONF"
fi
port="${port:-${SAVED_PORT:-2603}}"                       # port d'écoute (2603 par défaut)
data_dir="${data_dir:-${SAVED_DATA_DIR:-$ORG_ROOT/data}}" # base SQLite + pièces jointes
if [[ $no_https == 1 ]]; then
    ssl_cert="" ssl_key=""                                # --no-https : on oublie le certificat retenu
else
    ssl_cert="${ssl_cert:-$SAVED_SSL_CERT}" ssl_key="${ssl_key:-$SAVED_SSL_KEY}"
fi

# Contrôles de cohérence avant de toucher à quoi que ce soit.
[[ "$port" =~ ^[0-9]+$ ]] || fail "Port invalide : $port"
[[ -z "$ssl_cert" && -z "$ssl_key" ]] || [[ -n "$ssl_cert" && -n "$ssl_key" ]] \
    || fail "HTTPS : donnez à la fois --ssl-cert et --ssl-key."

# Les chemins sont rendus absolus : le service, lui, ne démarre pas depuis le dossier courant.
absolute() { [[ "$1" == /* ]] && printf '%s\n' "$1" || printf '%s\n' "$PWD/$1"; }
data_dir="$(absolute "$data_dir")"
[[ -n "$ssl_cert" ]] && ssl_cert="$(absolute "$ssl_cert")" && ssl_key="$(absolute "$ssl_key")"
https=0; [[ -n "$ssl_cert" ]] && https=1

# --- 0.d Contenu du service systemd -------------------------------------------------------------------
# systemd est le gestionnaire de services de Linux : il démarre le serveur au boot, le relance s'il
# s'arrête et garde ses journaux (journalctl). On lui décrit le serveur dans un fichier « unit », généré
# ici avec les valeurs ci-dessus (rien n'est écrit tant qu'on n'est pas à l'étape 3).
service_unit() {
    cat <<UNIT
# Service systemd du serveur Organizer — généré par deploy/install.sh (ne pas modifier à la main :
# relancer deploy/install.sh avec d'autres options).
[Unit]
Description=Organizer - serveur de tâches (port $port)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$ORG_USER
Group=$ORG_GROUP
WorkingDirectory=$ORG_ROOT
Environment="ORGANIZER_DATA_DIR=$data_dir"
Environment="ORGANIZER_PORT=$port"
UNIT
    if [[ $https == 1 ]]; then
        printf 'Environment="ORGANIZER_SSL_CERT=%s"\nEnvironment="ORGANIZER_SSL_KEY=%s"\n' "$ssl_cert" "$ssl_key"
    fi
    cat <<UNIT
ExecStart="$ORG_ROOT/.venv/bin/python" "$ORG_ROOT/run_server.py"
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
}
# Lecture du fichier généré :
#   After/Wants=network-online.target  démarrer une fois le réseau disponible ;
#   User/Group                         compte sous lequel tourne le serveur (jamais root) ;
#   WorkingDirectory                   dossier du projet ;
#   Environment                        réglages lus par organizer/config.py (ORGANIZER_…) ;
#   ExecStart                          la commande lancée : le Python du .venv + run_server.py ;
#   Restart=always, RestartSec=5       relancé 5 s après tout arrêt (plantage ou non) ;
#   WantedBy=multi-user.target         une fois « activé » (enable), démarré à chaque démarrage du Pi.

# --print-service : on montre le fichier et on s'arrête, sans rien installer.
if [[ $action == "print" ]]; then
    service_unit
    exit 0
fi

command -v systemctl >/dev/null || fail "systemd est introuvable : ce script installe un service systemd."

# --uninstall : arrêter le service, ne plus le lancer au démarrage, effacer son fichier, et prévenir
# systemd. Le code, le .venv et les données ne sont pas touchés (réinstaller les retrouve tels quels).
if [[ $action == "uninstall" ]]; then
    say "🗑️  Arrêt et retrait du service $ORG_SERVICE"
    org_as_root systemctl disable --now "$ORG_SERVICE" 2>/dev/null || true  # « || true » : déjà absent
    org_as_root rm -f "$ORG_UNIT_PATH"
    org_as_root systemctl daemon-reload
    say "✅ Service retiré. Le code, .venv et les données ($data_dir) sont conservés."
    exit 0
fi

say "📋 Installation du serveur Organizer"
say "   dossier : $ORG_ROOT · utilisateur : $ORG_USER · données : $data_dir · port : $port$([[ $https == 1 ]] && echo ' · HTTPS')"

# ═════════════════════════════════════════════════════════════════════════════════════════════════════════
# 1. VÉRIFICATIONS (avant de modifier quoi que ce soit)
# ═════════════════════════════════════════════════════════════════════════════════════════════════════════

# Le compte doit pouvoir écrire dans le dossier du projet (création du .venv). Échoue typiquement si le
# dépôt a été cloné avec « sudo git clone » : les fichiers appartiennent alors à root.
org_as_user test -w "$ORG_ROOT" \
    || fail "$ORG_USER ne peut pas écrire dans $ORG_ROOT (dossier cloné en root ?) : sudo chown -R $ORG_USER: \"$ORG_ROOT\""

# Python 3.11 au minimum (version du Raspberry Pi OS actuel). PYTHON=… permet d'en choisir un autre.
python="${PYTHON:-python3}"
org_as_user "$python" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null \
    || fail "Python ≥ 3.11 requis pour $ORG_USER (sur Raspberry Pi OS : sudo apt install python3 python3-venv)."

# En HTTPS, le serveur (qui tourne sous ce compte) doit pouvoir lire le certificat et sa clé.
if [[ $https == 1 ]]; then
    org_as_user test -r "$ssl_cert" || fail "Certificat illisible par $ORG_USER : $ssl_cert"
    org_as_user test -r "$ssl_key" || fail "Clé illisible par $ORG_USER : $ssl_key"
fi

# ═════════════════════════════════════════════════════════════════════════════════════════════════════════
# 2. ENVIRONNEMENT PYTHON
# ═════════════════════════════════════════════════════════════════════════════════════════════════════════

# Le .venv est un Python privé au projet : les bibliothèques y sont installées sans toucher au système.
# Créé une seule fois ; les relances du script le réutilisent.
if [[ ! -x "$ORG_ROOT/.venv/bin/python" ]]; then
    say "🐍 Création de l'environnement Python (.venv)"
    org_as_user "$python" -m venv "$ORG_ROOT/.venv" \
        || fail "Création du venv impossible (sur Raspberry Pi OS : sudo apt install python3-venv)."
fi

# Dépendances du serveur (NiceGUI, SQLModel…). pip n'installe que ce qui manque ou a changé de version :
# c'est ce qui fait qu'une mise à jour récupère les nouvelles dépendances.
say "📦 Dépendances (requirements.txt)"
org_as_user "$ORG_ROOT/.venv/bin/python" -m pip install --quiet --upgrade pip
org_as_user "$ORG_ROOT/.venv/bin/python" -m pip install --quiet -r "$ORG_ROOT/requirements.txt"

# Dossier des données (la base y est créée au premier démarrage du serveur).
org_as_user mkdir -p "$data_dir"

# ═════════════════════════════════════════════════════════════════════════════════════════════════════════
# 3. SERVICE SYSTEMD
# ═════════════════════════════════════════════════════════════════════════════════════════════════════════

# On génère le fichier dans un fichier temporaire (effacé à la fin du script, même en cas d'erreur)…
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
service_unit > "$tmp"

# … et on ne remplace celui du système que s'il est différent (première installation, options ou
# nouvelle version du script). « daemon-reload » fait relire ses fichiers à systemd.
if ! cmp -s "$tmp" "$ORG_UNIT_PATH" 2>/dev/null; then
    say "⚙️  Service systemd $ORG_UNIT_PATH"
    org_as_root install -m 644 "$tmp" "$ORG_UNIT_PATH"   # copie lisible par tous, modifiable par root
    org_as_root systemctl daemon-reload
fi

# « enable » : démarrage automatique à chaque démarrage du Pi (lien vers multi-user.target).
org_as_root systemctl enable --quiet "$ORG_SERVICE"

# « restart » : démarre le service, ou l'arrête puis le redémarre s'il tournait déjà — indispensable après
# une mise à jour, sinon l'ancien code resterait en mémoire.
say "🔁 (Re)démarrage du service"
org_as_root systemctl restart "$ORG_SERVICE"

# ═════════════════════════════════════════════════════════════════════════════════════════════════════════
# 4. MÉMORISATION DES OPTIONS
# ═════════════════════════════════════════════════════════════════════════════════════════════════════════

# deploy/update.sh relance ce script avec --reuse : il retrouve ainsi le port, le dossier des données et
# le certificat choisis ici. printf %q protège les chemins contenant des espaces ou des caractères
# spéciaux. Le fichier est écrit sous le compte de l'utilisateur (tee), pas sous root.
org_as_user tee "$CONF" >/dev/null <<CONF
# Options de deploy/install.sh (reprises par --reuse et deploy/update.sh). Généré automatiquement.
SAVED_PORT=$(printf '%q' "$port")
SAVED_DATA_DIR=$(printf '%q' "$data_dir")
SAVED_SSL_CERT=$(printf '%q' "$ssl_cert")
SAVED_SSL_KEY=$(printf '%q' "$ssl_key")
CONF

# ═════════════════════════════════════════════════════════════════════════════════════════════════════════
# 5. VÉRIFICATION FINALE
# ═════════════════════════════════════════════════════════════════════════════════════════════════════════

# org_wait_server interroge http(s)://127.0.0.1:<port>/api/v1/version pendant 40 s au plus : si le
# serveur répond, l'installation a réussi et l'on connaît la version qui tourne réellement.
if version="$(org_wait_server "$port" "$https")"; then
    scheme="http"; [[ $https == 1 ]] && scheme="https"
    say ""
    say "✅ Organizer $version tourne (service « $ORG_SERVICE », lancé au démarrage, relancé s'il s'arrête)."
    say "   Adresses :"
    # Nom réseau du Pi (ex. raspberrypi.local, résolu par mDNS sur le réseau local)…
    say "     $scheme://$(hostname).local:$port"
    # … et ses adresses IPv4 : « hostname -I » (Raspberry Pi OS, Debian), sinon « ip » (autres
    # distributions). Les adresses IPv6 (contenant « : ») sont ignorées.
    addresses="$(hostname -I 2>/dev/null || true)"
    if [[ -z "$addresses" ]] && command -v ip >/dev/null; then
        addresses="$(ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1)"
    fi
    for ip in $addresses; do
        [[ "$ip" == *:* ]] || say "     $scheme://$ip:$port"
    done
    say "   Première fois : ouvrez l'une de ces adresses pour créer le compte administrateur."
    say "   État : systemctl status $ORG_SERVICE · journaux : journalctl -u $ORG_SERVICE -f"
else
    # Le service est installé mais le serveur ne répond pas : la cause est dans ses journaux.
    say "⚠️  Le serveur ne répond pas : journalctl -u $ORG_SERVICE -n 50"
    exit 1
fi
