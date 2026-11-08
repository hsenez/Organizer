@echo off
rem Retire les raccourcis d'Organizer (le dossier et son environnement Python restent)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -Uninstall
echo.
pause
