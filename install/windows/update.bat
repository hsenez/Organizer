@echo off
rem Mise a jour du client bureau Organizer (git pull + reinstallation avec les memes options)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1"
echo.
pause
