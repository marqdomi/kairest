@echo off
title KaiRest - Respaldo fuera de la laptop
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0respaldo-externo.ps1" %*
echo.
echo Puedes cerrar esta ventana.
pause >nul
