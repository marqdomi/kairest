@echo off
title KaiRest - Restaurar backup
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restore.ps1"
echo.
echo Puedes cerrar esta ventana.
pause >nul
