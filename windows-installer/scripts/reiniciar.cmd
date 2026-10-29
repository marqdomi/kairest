@echo off
title KaiRest - Reiniciar
cd /d "%~dp0"
echo Reiniciando KaiRest...
echo.
REM La instalacion por imagen no lleva docker-compose.yml: sin el -f, docker
REM responde "no configuration file provided" y el boton no hace nada.
if exist "docker-compose.yml" (
  docker compose restart
) else (
  docker compose -f docker-compose.prod.yml restart
)
echo.
echo KaiRest reiniciado.
echo Puedes cerrar esta ventana.
pause >nul
