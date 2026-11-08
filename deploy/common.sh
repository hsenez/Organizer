# Fonctions communes à deploy/install.sh et deploy/update.sh (fichier inclus avec « source » : il ne
# s'exécute pas seul, il ajoute ces fonctions et constantes au script qui l'inclut).

# Nom du service systemd (systemctl status organizer…) et emplacement de son fichier.
ORG_SERVICE="organizer"
ORG_UNIT_PATH="${ORG_UNIT_PATH:-/etc/systemd/system/${ORG_SERVICE}.service}"  # réglable pour les tests

# Afficher un message ; afficher une erreur (sur la sortie d'erreur) et arrêter le script.
say()  { printf '%s\n' "$*"; }
fail() { printf '❌ %s\n' "$*" >&2; exit 1; }

# Utilisateur pour lequel le serveur est installé et tourne : celui qui tape la commande, jamais root.
#   - lancé sans sudo : le script tourne déjà sous ce compte → id -un ;
#   - lancé avec sudo : le script tourne en root (identifiant effectif 0), mais sudo a noté dans SUDO_USER
#     le nom de celui qui a tapé la commande → c'est lui qu'on retient ;
#   - lancé directement en root (session root, su -) : pas de SUDO_USER → refus.
# ORG_EUID permet aux tests de simuler un lancement avec sudo.
org_target_user() {
    local euid="${ORG_EUID:-$EUID}"
    if [[ "$euid" -eq 0 ]]; then
        if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
            printf '%s\n' "$SUDO_USER"
            return 0
        fi
        fail "Lancez ce script depuis votre compte utilisateur (avec ou sans sudo), pas directement en root : le serveur ne doit pas tourner en root."
    fi
    id -un
}

# Exécute une commande en tant que l'utilisateur cible : directement si le script tourne déjà sous son
# compte, sinon (script lancé avec sudo) par « sudo -u <utilisateur> ». Les fichiers créés (venv,
# données, server.conf) lui appartiennent ainsi, pas à root.
org_as_user() {
    if [[ "${ORG_EUID:-$EUID}" -eq 0 ]]; then
        sudo -u "$ORG_USER" -H -- "$@"
    else
        "$@"
    fi
}

# Exécute une commande système (écrire dans /etc, systemctl) : directement si le script tourne déjà en
# root (lancé avec sudo), sinon par sudo, qui demande alors le mot de passe.
org_as_root() {
    if [[ "${ORG_EUID:-$EUID}" -eq 0 ]]; then
        "$@"
    else
        sudo -- "$@"
    fi
}

# Attend que le serveur réponde sur /api/v1/version (40 essais, un par seconde) et affiche sa version ;
# échoue s'il ne répond pas. $1 = port, $2 = https (0/1), $3 = adresse (127.0.0.1 par défaut). Écrit en
# Python (celui du .venv) pour ne pas dépendre de curl ; en HTTPS, le certificat n'est pas vérifié (il est
# émis pour le nom du Pi, pas pour 127.0.0.1).
org_wait_server() {
    local port="$1" https="$2" address="${3:-127.0.0.1}" python="$ORG_ROOT/.venv/bin/python"
    "$python" - "$port" "$https" "$address" <<'PY'
import json, ssl, sys, time, urllib.request
port, https, address = sys.argv[1], sys.argv[2] == "1", sys.argv[3]
url = f"{'https' if https else 'http'}://{address}:{port}/api/v1/version"
context = ssl._create_unverified_context() if https else None  # certificat émis pour le nom du Pi
for _ in range(40):
    try:
        with urllib.request.urlopen(url, timeout=2, context=context) as response:
            print(json.loads(response.read())["version"])
            sys.exit(0)
    except Exception:
        time.sleep(1)
sys.exit(1)
PY
}
