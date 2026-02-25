# ═══════════════════════════════════════════════════
# KaiRest POS — Actualizar (Windows)
# Crea backup, actualiza codigo y reinicia servicios
# ═══════════════════════════════════════════════════
#Requires -Version 5.1
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  KaiRest POS — Actualizar" -ForegroundColor Cyan
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

# ── Determine compose file ──
$composeFile = ""
if (Test-Path "docker-compose.prod.yml") {
    $composeFile = "-f docker-compose.prod.yml"
    Write-Host "  Usando docker-compose.prod.yml (modo produccion)" -ForegroundColor Cyan
} elseif (Test-Path "docker-compose.yml") {
    $composeFile = ""
    Write-Host "  Usando docker-compose.yml (modo desarrollo)" -ForegroundColor Cyan
    # In dev mode, pull latest code if git repo
    if (Test-Path ".git") {
        Write-Host "  Descargando ultima version del codigo..." -ForegroundColor Cyan
        try {
            git pull --rebase 2>&1 | Out-Null
        } catch {
            Write-Host "  No se pudo hacer git pull." -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "  ERROR: No se encontro docker-compose.yml ni docker-compose.prod.yml" -ForegroundColor Red
    exit 1
}

# ── Create backup before updating ──
Write-Host "  Creando backup de la base de datos..." -ForegroundColor Cyan
if (-not (Test-Path "backups")) { New-Item -ItemType Directory -Path "backups" | Out-Null }

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupFile = "backups\pre_update_$timestamp.dump"

try {
    if ($composeCmd -eq "docker compose") {
        docker compose $composeFile exec -T db pg_dump -Fc -U casaleones casaleones > $backupFile 2>$null
    } else {
        docker-compose $composeFile exec -T db pg_dump -Fc -U casaleones casaleones > $backupFile 2>$null
    }
    Write-Host "  Backup creado: $backupFile" -ForegroundColor Green
} catch {
    Write-Host "  No se pudo crear backup (primera instalacion?)." -ForegroundColor Yellow
}

# ── Pull latest image / rebuild ──
Write-Host "  Descargando ultima version..." -ForegroundColor Cyan
if ($composeCmd -eq "docker compose") {
    docker compose $composeFile pull 2>&1 | Select-Object -Last 3
} else {
    docker-compose $composeFile pull 2>&1 | Select-Object -Last 3
}

Write-Host "  Aplicando actualizacion..." -ForegroundColor Cyan
if ($composeCmd -eq "docker compose") {
    docker compose $composeFile up -d 2>&1 | Select-Object -Last 5
} else {
    docker-compose $composeFile up -d 2>&1 | Select-Object -Last 5
}

# ── Wait for health ──
Write-Host "  Esperando a que la aplicacion inicie..." -ForegroundColor Cyan

# Read port from .env or default
$port = "5005"
$envFile = ".env"
if (Test-Path $envFile) {
    $envLines = Get-Content $envFile -ErrorAction SilentlyContinue
    foreach ($line in $envLines) {
        if ($line -match "^APP_PORT=(\d+)") { $port = $Matches[1] }
    }
}

$healthUrl = "http://localhost:${port}/health"
$maxRetries = 60
$healthy = $false

for ($i = 1; $i -le $maxRetries; $i++) {
    try {
        $response = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 3 -ErrorAction SilentlyContinue
        if ($response.StatusCode -eq 200) {
            $healthy = $true

            # Try to get version
            $version = "?"
            try {
                $body = $response.Content | ConvertFrom-Json
                $version = $body.version
            } catch {}

            Write-Host ""
            Write-Host "  KaiRest actualizado y funcionando." -ForegroundColor Green
            Write-Host "  Version: $version" -ForegroundColor Green
            Write-Host "  URL: http://localhost:${port}" -ForegroundColor Cyan
            Write-Host ""
            exit 0
        }
    } catch {}
    Start-Sleep -Seconds 2
    Write-Host "." -NoNewline
}

Write-Host ""
if (-not $healthy) {
    Write-Host "  La app no respondio en 120s." -ForegroundColor Red
    if ($composeCmd -eq "docker compose") {
        Write-Host "  Revisa: docker compose $composeFile logs web" -ForegroundColor Yellow
    } else {
        Write-Host "  Revisa: docker-compose $composeFile logs web" -ForegroundColor Yellow
    }
    exit 1
}
