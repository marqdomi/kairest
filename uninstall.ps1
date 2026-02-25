# ═══════════════════════════════════════════════════
# KaiRest POS — Desinstalar (Windows)
# Detiene containers y opcionalmente elimina datos
# ═══════════════════════════════════════════════════
#Requires -Version 5.1
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  KaiRest POS — Desinstalar" -ForegroundColor Red
Write-Host ""

# ── Detect compose command ──
$composeCmd = $null
try {
    docker compose version 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $composeCmd = "docker compose" }
} catch {}
if (-not $composeCmd) {
    try {
        docker-compose version 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { $composeCmd = "docker-compose" }
    } catch {}
}
if (-not $composeCmd) {
    Write-Host "  ERROR: Docker Compose no encontrado." -ForegroundColor Red
    exit 1
}

Write-Host "  Esto detendra KaiRest y eliminara los containers." -ForegroundColor Yellow
Write-Host ""
$deleteDb = Read-Host "  Eliminar tambien la base de datos? (s/N)"

if ($composeCmd -eq "docker compose") {
    docker compose down 2>&1 | Out-Null
} else {
    docker-compose down 2>&1 | Out-Null
}

if ($deleteDb -match "^[sS]([iI])?$") {
    Write-Host "  Eliminando volumenes de datos..." -ForegroundColor Yellow
    if ($composeCmd -eq "docker compose") {
        docker compose down -v 2>&1 | Out-Null
    } else {
        docker-compose down -v 2>&1 | Out-Null
    }
    Write-Host "  Containers y base de datos eliminados." -ForegroundColor Green
} else {
    Write-Host "  Containers detenidos. La base de datos se conserva." -ForegroundColor Green
}

Write-Host ""
Write-Host "  Para reinstalar: .\install.ps1" -ForegroundColor Yellow
Write-Host ""
