@echo off
title KaiRest - Actualizar
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1"
echo.
echo Puedes cerrar esta ventana.
pause >nul
