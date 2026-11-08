@echo off
rem Installation du client bureau Organizer (voir install.ps1 pour les options, ex. : install.bat -Uninstall)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
