# ===================================================
# KaiRest POS - Actualizar (Windows)
# Crea backup, actualiza codigo y reinicia servicios
# ===================================================
#Requires -Version 5.1
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  KaiRest POS - Actualizar" -ForegroundColor Cyan
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

# -- Determine compose file (misma regla que update.sh) --
# install.ps1 instala con docker-compose.yml (build local) tanto si clona con Git
# como si corre desde la carpeta copiada en USB. Cambiar a prod a media vida haria
# jalar una imagen distinta a la que tiene corriendo el equipo, asi que la regla es:
# si existe docker-compose.yml, esa es la instalacion. docker-compose.prod.yml es
# solo para despliegues que nunca tuvieron el archivo de build (imagen publicada).
$composeFile = ""
$buildFlag = ""
if (Test-Path "docker-compose.yml") {
    $buildFlag = "--build"
    Write-Host "  Usando docker-compose.yml (build local)" -ForegroundColor Cyan
    # Solo hay codigo nuevo que traer si la instalacion se hizo clonando con Git.
    if (Test-Path ".git") {
        Write-Host "  Descargando ultima version del codigo..." -ForegroundColor Cyan
        try {
            git pull --rebase | Out-Null
        } catch {
            Write-Host "  No se pudo hacer git pull." -ForegroundColor Yellow
        }
    } else {
        Write-Host "  Instalacion sin Git: se reconstruye con el codigo de esta carpeta." -ForegroundColor Yellow
    }
} elseif (Test-Path "docker-compose.prod.yml") {
    $composeFile = "-f docker-compose.prod.yml"
    Write-Host "  Usando docker-compose.prod.yml (imagen pre-construida)" -ForegroundColor Cyan
} else {
    Write-Host "  ERROR: No se encontro docker-compose.yml ni docker-compose.prod.yml" -ForegroundColor Red
    exit 1
}
$compose = ("$composeCmd $composeFile").Trim()

# -- Create backup before updating --
Write-Host "  Creando backup de la base de datos..." -ForegroundColor Cyan
if (-not (Test-Path "backups")) { New-Item -ItemType Directory -Path "backups" | Out-Null }

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupFile = "backups\pre_update_$timestamp.dump"

# La redireccion de PowerShell convierte la salida a texto y corrompe el .dump
# binario, por eso pg_dump va via cmd /c (redireccion de bytes).
cmd /c "$compose exec -T db pg_dump -Fc -U casaleones casaleones > ""$backupFile"" 2>nul"
if ((Test-Path $backupFile) -and ((Get-Item $backupFile).Length -gt 0)) {
    Write-Host "  Backup creado: $backupFile" -ForegroundColor Green
} else {
    Write-Host "  No se pudo crear backup (primera instalacion?)." -ForegroundColor Yellow
    if (Test-Path $backupFile) { Remove-Item $backupFile -Force }
}

# -- Pull latest image / rebuild --
if ($buildFlag) {
    Write-Host "  Reconstruyendo la aplicacion..." -ForegroundColor Cyan
} else {
    Write-Host "  Descargando ultima version..." -ForegroundColor Cyan
    cmd /c "$compose pull" | Select-Object -Last 3
}

Write-Host "  Aplicando actualizacion..." -ForegroundColor Cyan
cmd /c "$compose up -d $buildFlag" | Select-Object -Last 5

# -- Apply schema migrations --
# create_all() del arranque solo crea tablas nuevas, nunca altera existentes.
# Alembic aplica los cambios de schema pendientes. En una base creada por
# create_all sin historial alembic, se marca el head actual primero (el schema
# ya coincide) para que futuros upgrades apliquen solo lo nuevo.
Write-Host "  Aplicando migraciones de base de datos..." -ForegroundColor Cyan
Start-Sleep -Seconds 5  # dar tiempo a que los contenedores esten exec-ready
$tieneAlembic = (cmd /c "$compose exec -T db psql -U casaleones -d casaleones -tAc ""SELECT to_regclass('alembic_version') IS NOT NULL"" 2>nul") -join ""
if ($tieneAlembic.Trim() -ne "t") {
    cmd /c "$compose exec -T web flask db stamp head 2>nul" | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  Base marcada en head (primera vez con Alembic)" -ForegroundColor Green
    } else {
        Write-Host "  No se pudo hacer stamp (se reintentara en la proxima actualizacion)." -ForegroundColor Yellow
    }
}
cmd /c "$compose exec -T web flask db upgrade 2>nul" | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "  Migraciones aplicadas" -ForegroundColor Green
} else {
    Write-Host "  No se pudieron aplicar migraciones. Revisa: $compose logs web" -ForegroundColor Yellow
}

# -- Wait for health --
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
    Write-Host "  Revisa: $compose logs web" -ForegroundColor Yellow
    exit 1
}
