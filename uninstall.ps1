# ===================================================
# KaiRest POS - Desinstalar (Windows)
# Detiene containers y opcionalmente elimina datos
# ===================================================
#Requires -Version 5.1
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  KaiRest POS - Desinstalar" -ForegroundColor Red
Write-Host ""

# -- Detect compose command --
$composeCmd = $null
try {
    docker compose version | Out-Null
    if ($LASTEXITCODE -eq 0) { $composeCmd = "docker compose" }
} catch {}
if (-not $composeCmd) {
    try {
        docker-compose version | Out-Null
        if ($LASTEXITCODE -eq 0) { $composeCmd = "docker-compose" }
    } catch {}
}
if (-not $composeCmd) {
    Write-Host "  ERROR: Docker Compose no encontrado." -ForegroundColor Red
    exit 1
}

# -- Que instalacion es: build local o imagen publicada --
# La instalacion por imagen no lleva docker-compose.yml, asi que sin el -f los
# comandos fallan con "no configuration file provided".
if (Test-Path "docker-compose.yml") {
    $composeFile = ""
} elseif (Test-Path "docker-compose.prod.yml") {
    $composeFile = "-f docker-compose.prod.yml"
} else {
    Write-Host "  ERROR: ejecuta esto desde la carpeta de KaiRest." -ForegroundColor Red
    exit 1
}
$compose = ("$composeCmd $composeFile").Trim()

Write-Host "  Esto detendra KaiRest y eliminara los containers." -ForegroundColor Yellow
Write-Host ""
$deleteDb = Read-Host "  Eliminar tambien la base de datos? (s/N)"

cmd /c "$compose down" | Out-Null

if ($deleteDb -match "^[sS]([iI])?$") {
    Write-Host "  Eliminando volumenes de datos..." -ForegroundColor Yellow
    cmd /c "$compose down -v" | Out-Null
    Write-Host "  Containers y base de datos eliminados." -ForegroundColor Green
} else {
    Write-Host "  Containers detenidos. La base de datos se conserva." -ForegroundColor Green
}

Write-Host ""
Write-Host "  Para reinstalar: .\install.ps1" -ForegroundColor Yellow
Write-Host ""
