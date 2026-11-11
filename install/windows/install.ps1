<#
Installation du client bureau Organizer sous Windows (utilisateur courant, sans droits administrateur).

    install.bat                                  installe ou met à jour
    install.bat -NoAutostart                     sans démarrage en arrière-plan avec Windows
    install.bat -NoDesktop                       sans raccourci sur le Bureau
    install.bat -ShowKey "Ctrl+Alt+O" -NewKey "Ctrl+Alt+N"    autres raccourcis clavier
    install.bat -Uninstall                       retire les raccourcis (garde le dossier et .venv)
    install.bat -Reuse                           reprend les options de la dernière installation (mise à jour)

Étapes : vérifie Python >= 3.11, crée le venv .venv, installe requirements-client.txt, puis crée les
raccourcis du menu Démarrer, du Bureau et du démarrage de session. Les raccourcis clavier globaux sont
enregistrés par Organizer lui-même quand il tourne (d'où le démarrage avec la session par défaut).
Les raccourcis lancent pythonw.exe (pas de console) ; si Organizer tourne déjà, la commande lui est transmise.
Déclare aussi le protocole organizer:// (liens « Ouvrir dans le client bureau ») pour l'utilisateur courant.
#>
param(
    [switch]$Uninstall,
    [switch]$NoAutostart,
    [switch]$NoDesktop,
    [string]$ShowKey = "Ctrl+Alt+O",
    [string]$NewKey = "Ctrl+Alt+N",
    [switch]$Reuse
)
$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"
$Pythonw = Join-Path $Venv "Scripts\pythonw.exe"
$Script = Join-Path $Root "run_client.py"
$Icon = Join-Path $Root "organizer\assets\organizer.ico"

$Protocol = "HKCU:\Software\Classes\organizer"     # liens organizer://note/5
$Programs = [Environment]::GetFolderPath("Programs")   # menu Démarrer de l'utilisateur
$Links = [ordered]@{
    Main    = Join-Path $Programs "Organizer.lnk"
    New     = Join-Path $Programs "Organizer - Nouvelle tâche.lnk"
    Quit    = Join-Path $Programs "Organizer - Quitter.lnk"
    Desktop = Join-Path ([Environment]::GetFolderPath("Desktop")) "Organizer.lnk"
    Startup = Join-Path ([Environment]::GetFolderPath("Startup")) "Organizer (arrière-plan).lnk"
}

function Write-Step($Text) { Write-Host $Text -ForegroundColor Cyan }

# Options retenues d'une installation à l'autre (même dossier que la configuration du client).
$ConfigDir = if ($env:ORGANIZER_CLIENT_DIR) { $env:ORGANIZER_CLIENT_DIR } else { Join-Path $env:APPDATA "Organizer" }
$OptionsFile = Join-Path $ConfigDir "install.json"
if ($Reuse -and (Test-Path $OptionsFile)) {
    $saved = Get-Content $OptionsFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $NoAutostart = [bool]$saved.NoAutostart
    $NoDesktop = [bool]$saved.NoDesktop
    if ($saved.ShowKey) { $ShowKey = $saved.ShowKey }
    if ($saved.NewKey) { $NewKey = $saved.NewKey }
}

function New-Link($Path, $Arguments, $Description, $Hotkey) {
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($Path)
    $link.TargetPath = $Pythonw
    $link.Arguments = ("`"$Script`" " + $Arguments).Trim()
    $link.WorkingDirectory = $Root
    if (Test-Path $Icon) { $link.IconLocation = "$Icon,0" }
    $link.Description = $Description
    # Raccourcis clavier globaux : enregistrés par Organizer lui-même (winshell.py), plus fiables. Un raccourci
    # posé sur un .lnk par une ancienne installation est effacé (sinon l'Explorateur garderait la touche).
    $link.Hotkey = ""
    $link.Save()
}

if ($Uninstall) {
    if (Test-Path $Python) { & $Python $Script --quit }
    foreach ($path in $Links.Values) { if (Test-Path $path) { Remove-Item $path } }
    if (Test-Path $Protocol) { Remove-Item -Recurse -Force $Protocol }
    Write-Host "Raccourcis d'Organizer retirés (le dossier $Root et son .venv restent)." -ForegroundColor Green
    exit 0
}

Write-Step "Installation du client bureau Organizer dans $Root"

# --- Python 3.11 à 3.13 (lanceur « py » de python.org, sinon « python ») ---
# Plus récent : pythonnet (requis par pywebview sous Windows) n'existe pas encore, et des paquets sans
# wheel (PyYAML…) devraient être compilés (ce que le Contrôle intelligent des applications bloque).
$VersionCheck = "import sys; print((3, 11) <= sys.version_info[:2] <= (3, 13))"
$base = $null
foreach ($candidate in @(@("py", "-3.13"), @("py", "-3.12"), @("py", "-3.11"), @("python"))) {
    try {
        $exe = $candidate[0]; $rest = @($candidate | Select-Object -Skip 1)
        $ok = & $exe @rest -c $VersionCheck 2>$null
        if ($ok -eq "True") { $base = $candidate; break }
    } catch { }
}
if (-not $base) {
    Write-Host "Python 3.11, 3.12 ou 3.13 est introuvable (les versions plus récentes ne conviennent pas encore)." -ForegroundColor Red
    Write-Host "Installez Python 3.13 : « py install 3.13 » (gestionnaire d'installation Python), ou depuis"
    Write-Host "https://www.python.org/downloads/ (cocher « Add python.exe to PATH »), puis relancez."
    exit 1
}

# --- venv et dépendances (un venv créé avec une version qui ne convient pas est refait) ---
if (Test-Path $Python) {
    $ok = & $Python -c $VersionCheck 2>$null
    if ($ok -ne "True") {
        Write-Step "Environnement Python existant d'une version qui ne convient pas : recréation"
        Remove-Item -Recurse -Force $Venv
    }
}
if (-not (Test-Path $Python)) {
    Write-Step "Création de l'environnement Python ($Venv)"
    $exe = $base[0]; $rest = @($base | Select-Object -Skip 1)
    & $exe @rest -m venv $Venv
    if ($LASTEXITCODE -ne 0) { Write-Host "Échec de la création du venv." -ForegroundColor Red; exit 1 }
}
Write-Step "Installation des dépendances (requirements-client.txt)"
& $Python -m pip install --quiet --upgrade pip
& $Python -m pip install --quiet -r (Join-Path $Root "requirements-client.txt")
if ($LASTEXITCODE -ne 0) { Write-Host "Échec de l'installation des dépendances." -ForegroundColor Red; exit 1 }

# --- raccourcis ---
Write-Step "Création des raccourcis"
New-Link $Links.Main "" "Organiseur de tâches" $ShowKey
New-Link $Links.New "--new-task" "Créer une nouvelle tâche dans Organizer" $NewKey
New-Link $Links.Quit "--quit" "Arrêter Organizer (il tourne en arrière-plan)" $null
if ($NoDesktop) { if (Test-Path $Links.Desktop) { Remove-Item $Links.Desktop } }
else { New-Link $Links.Desktop "" "Organiseur de tâches" $null }
if ($NoAutostart) { if (Test-Path $Links.Startup) { Remove-Item $Links.Startup } }
else { New-Link $Links.Startup "--hidden" "Démarre Organizer en arrière-plan (rappels, raccourcis)" $null }

# --- protocole organizer:// (« Ouvrir dans le client bureau » depuis un lien partagé) ---
Write-Step "Déclaration des liens organizer://"
New-Item -Path $Protocol -Force -Value "URL:Organizer" | Out-Null
Set-ItemProperty -Path $Protocol -Name "URL Protocol" -Value ""
New-Item -Path "$Protocol\DefaultIcon" -Force -Value "`"$Icon`",0" | Out-Null
New-Item -Path "$Protocol\shell\open\command" -Force -Value "`"$Pythonw`" `"$Script`" `"%1`"" | Out-Null

New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
@{ NoAutostart = [bool]$NoAutostart; NoDesktop = [bool]$NoDesktop; ShowKey = $ShowKey; NewKey = $NewKey } |
    ConvertTo-Json | Set-Content -Path $OptionsFile -Encoding UTF8

# Raccourcis clavier mémorisés pour les afficher dans l'application.
Push-Location $Root
try {
    & $Python -c "import sys; from organizer.client import system; from organizer.client.config import ConfigStore; s = ConfigStore(system.config_dir()); c = s.load(); c.shortcuts = {'show': sys.argv[1], 'new_task': sys.argv[2]}; s.save(c)" $ShowKey $NewKey
} finally { Pop-Location }

Write-Host ""
Write-Host "Terminé ! « Organizer » est dans le menu Démarrer." -ForegroundColor Green
Write-Host "  $ShowKey : ouvrir Organizer      $NewKey : nouvelle tâche"
Write-Host "  Les liens organizer://… (partagés depuis Organizer) ouvrent ce client."
Write-Host "  Fermer la fenêtre la cache : Organizer continue en arrière-plan (rappels, raccourcis)."
Write-Host "  Pour l'arrêter : menu du compte > Quitter Organizer, ou « Organizer - Quitter » dans le menu Démarrer."
