@echo off
title KaiRest - Detener
cd /d "%~dp0"
echo Deteniendo KaiRest...
echo.
REM La instalacion por imagen no lleva docker-compose.yml: sin el -f, docker
REM responde "no configuration file provided" y el boton no hace nada.
if exist "docker-compose.yml" (
  docker compose down
) else (
  docker compose -f docker-compose.prod.yml down
)
echo.
echo KaiRest detenido. Los datos se conservan.
echo Puedes cerrar esta ventana.
pause >nul
