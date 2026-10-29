# ===================================================
# KaiRest POS - Restaurar base de datos desde backup (Windows)
#
# Uso:
#   .\restore.ps1                          # restaura el backup mas reciente
#   .\restore.ps1 backups\archivo.dump     # restaura un backup especifico
#
# Los backups se generan automaticamente cada hora en .\backups\
# (formato pg_dump -Fc) y antes de cada actualizacion (pre_update_*).
# ===================================================
#Requires -Version 5.1
param([string]$Dump)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  KaiRest POS - Restaurar backup" -ForegroundColor Cyan
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

# -- Determine compose file (misma regla que update.ps1) --
# Si existe docker-compose.yml, esa es la instalacion (install.ps1 siempre usa ese,
# clone con Git o corra desde la carpeta copiada). prod.yml es solo para despliegues
# con imagen pre-construida, que nunca tienen el archivo de build.
if (Test-Path "docker-compose.yml") {
    $composeFile = ""
} elseif (Test-Path "docker-compose.prod.yml") {
    $composeFile = "-f docker-compose.prod.yml"
} else {
    Write-Host "  ERROR: No se encontro docker-compose.yml ni docker-compose.prod.yml" -ForegroundColor Red
    Write-Host "  Ejecuta este script desde la carpeta de KaiRest (normalmente %USERPROFILE%\kairest)." -ForegroundColor Yellow
    exit 1
}
$compose = ("$composeCmd $composeFile").Trim()

# -- Pick backup file --
if (-not $Dump) {
    $ultimo = Get-ChildItem -Path "backups\*.dump" -ErrorAction SilentlyContinue |
              Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($ultimo) { $Dump = $ultimo.FullName }
}

if (-not $Dump -or -not (Test-Path $Dump)) {
    Write-Host "  ERROR: No se encontro ningun backup (.dump) en .\backups\" -ForegroundColor Red
    Write-Host "  Uso: .\restore.ps1 [backups\archivo.dump]" -ForegroundColor Yellow
    exit 1
}
$Dump = (Resolve-Path $Dump).Path
$tam = "{0:N1} MB" -f ((Get-Item $Dump).Length / 1MB)

# -- Confirm --
Write-Host "  Se restaurara: $Dump ($tam)" -ForegroundColor Yellow
Write-Host "  ESTO REEMPLAZA TODOS LOS DATOS ACTUALES de la base." -ForegroundColor Yellow
$confirm = Read-Host "  Escribe SI para confirmar"
if ($confirm -ne "SI") {
    Write-Host "  Cancelado." -ForegroundColor Cyan
    exit 0
}

# -- Safety backup of current state before restoring --
# La redireccion de PowerShell convierte la salida a texto y corrompe el .dump
# binario, por eso pg_dump/pg_restore van via cmd /c (redireccion de bytes).
Write-Host "  Creando respaldo de seguridad del estado actual..." -ForegroundColor Cyan
if (-not (Test-Path "backups")) { New-Item -ItemType Directory -Path "backups" | Out-Null }
$previo = "backups\pre_restore_$(Get-Date -Format 'yyyyMMdd_HHmmss').dump"
cmd /c "$compose exec -T db pg_dump -Fc -U casaleones casaleones > ""$previo"" 2>nul"
if ((Test-Path $previo) -and ((Get-Item $previo).Length -gt 0)) {
    Write-Host "  Respaldo previo: $previo" -ForegroundColor Green
} else {
    Write-Host "  No se pudo respaldar el estado actual." -ForegroundColor Yellow
    if (Test-Path $previo) { Remove-Item $previo -Force }
}

# -- Stop the app (keep db running) so no writes land mid-restore --
Write-Host "  Deteniendo la aplicacion..." -ForegroundColor Cyan
cmd /c "$compose stop web" | Select-Object -Last 1

# -- Restore --
Write-Host "  Restaurando base de datos..." -ForegroundColor Cyan
cmd /c "$compose exec -T db pg_restore --clean --if-exists --no-owner --no-acl -U casaleones -d casaleones < ""$Dump"""
$restoreExit = $LASTEXITCODE

# -- Restart app --
Write-Host "  Reiniciando la aplicacion..." -ForegroundColor Cyan
cmd /c "$compose start web" | Select-Object -Last 1

if ($restoreExit -ne 0) {
    Write-Host ""
    Write-Host "  pg_restore termino con avisos (codigo $restoreExit)." -ForegroundColor Yellow
    Write-Host "  Es normal si el backup es de una version anterior; revisa que los datos esten completos." -ForegroundColor Yellow
}

# -- Health check --
$port = "5005"
if (Test-Path ".env") {
    foreach ($line in (Get-Content ".env" -ErrorAction SilentlyContinue)) {
        if ($line -match "^APP_PORT=(\d+)") { $port = $Matches[1] }
    }
}

for ($i = 1; $i -le 60; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:${port}/health" -UseBasicParsing -TimeoutSec 3 -ErrorAction SilentlyContinue
        if ($r.StatusCode -eq 200) {
            Write-Host ""
            Write-Host "  Backup restaurado y aplicacion funcionando." -ForegroundColor Green
            Write-Host "  URL: http://localhost:${port}" -ForegroundColor Cyan
            Write-Host ""
            exit 0
        }
    } catch {}
    Start-Sleep -Seconds 2
    Write-Host "." -NoNewline
}

Write-Host ""
Write-Host "  La app no respondio en 120s." -ForegroundColor Red
Write-Host "  Revisa: $compose logs web" -ForegroundColor Yellow
exit 1
