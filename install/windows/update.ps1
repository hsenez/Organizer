<#
Mise à jour du client bureau Organizer sous Windows (update.bat) :
  1. arrête le client s'il tourne (il garde l'ancien code en mémoire) ;
  2. récupère la nouvelle version (git pull) ;
  3. relance install.ps1 avec les options de la première installation ;
  4. relance le client en arrière-plan s'il tournait.
#>
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
$Script = Join-Path $Root "run_client.py"
Set-Location $Root

if (-not (Test-Path $Python)) { Write-Host "Organizer n'est pas installé ici : lancez install.bat." -ForegroundColor Red; exit 1 }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "git est introuvable (https://git-scm.com/download/win)." -ForegroundColor Red; exit 1
}

& $Python -c "import sys; from organizer.client import instance, system; sys.exit(0 if instance.forward(system.config_dir(), 'ping') else 1)"
$WasRunning = ($LASTEXITCODE -eq 0)
if ($WasRunning) {
    Write-Host "Arrêt du client en cours d'exécution" -ForegroundColor Cyan
    & $Python $Script --quit
    Start-Sleep -Seconds 2
}

function Restart-Client {
    Write-Host "Relance du client en arrière-plan" -ForegroundColor Cyan
    Start-Process -FilePath $Pythonw -ArgumentList "`"$Script`" --hidden" -WorkingDirectory $Root
}

$before = (git rev-parse HEAD)
Write-Host "Récupération de la nouvelle version (git pull)" -ForegroundColor Cyan
git pull --ff-only
if ($LASTEXITCODE -ne 0) {
    Write-Host "git pull a échoué (modifications locales ? autre branche ?). Rien n'a été changé." -ForegroundColor Red
    if ($WasRunning) { Restart-Client }
    exit 1
}
$after = (git rev-parse HEAD)
if ($before -eq $after) { Write-Host "Déjà à jour." -ForegroundColor Green }
else { git log --oneline "$before..$after" }

& (Join-Path $PSScriptRoot "install.ps1") -Reuse
if ($WasRunning) { Restart-Client }
$version = & $Python -c "import organizer; print(organizer.__version__)"
Write-Host "Version installée : $version" -ForegroundColor Green
