<#
Installation du client bureau Organizer sous Windows (utilisateur courant, sans droits administrateur).

    install.bat                                  installe ou met à jour
    install.bat -NoAutostart                     sans démarrage en arrière-plan avec Windows
    install.bat -NoDesktop                       sans raccourci sur le Bureau
    install.bat -ShowKey "Ctrl+Alt+O" -NewKey "Ctrl+Alt+N"    autres raccourcis clavier
    install.bat -Uninstall                       retire les raccourcis (garde le dossier et .venv)
    install.bat -Reuse                           reprend les options de la dernière installation (mise à jour)

Étapes : vérifie Python >= 3.11, crée le venv .venv, installe requirements-client.txt, puis crée les
raccourcis du menu Démarrer (avec leurs raccourcis clavier globaux), du Bureau et du démarrage de session.
Les raccourcis lancent pythonw.exe (pas de console) ; si Organizer tourne déjà, la commande lui est transmise.
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
$Icon = Join-Path $Root "organizer\client\assets\organizer.ico"

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
    if ($Hotkey) { $link.Hotkey = $Hotkey.ToUpper() }
    $link.Save()
}

if ($Uninstall) {
    if (Test-Path $Python) { & $Python $Script --quit }
    foreach ($path in $Links.Values) { if (Test-Path $path) { Remove-Item $path } }
    Write-Host "Raccourcis d'Organizer retirés (le dossier $Root et son .venv restent)." -ForegroundColor Green
    exit 0
}

Write-Step "Installation du client bureau Organizer dans $Root"

# --- Python >= 3.11 (lanceur « py » de python.org, sinon « python ») ---
$base = $null
foreach ($candidate in @(@("py", "-3"), @("python"))) {
    try {
        $exe = $candidate[0]; $rest = @($candidate | Select-Object -Skip 1)
        $ok = & $exe @rest -c "import sys; print(sys.version_info >= (3, 11))" 2>$null
        if ($ok -eq "True") { $base = $candidate; break }
    } catch { }
}
if (-not $base) {
    Write-Host "Python 3.11 ou plus récent est introuvable." -ForegroundColor Red
    Write-Host "Installez-le depuis https://www.python.org/downloads/ (cocher « Add python.exe to PATH »), puis relancez."
    exit 1
}

# --- venv et dépendances ---
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
Write-Host "  Fermer la fenêtre la cache : Organizer continue en arrière-plan (rappels, raccourcis)."
Write-Host "  Pour l'arrêter : menu du compte > Quitter Organizer, ou « Organizer - Quitter » dans le menu Démarrer."
