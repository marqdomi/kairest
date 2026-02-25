# ═══════════════════════════════════════════════════
# KaiRest POS — Instalación para Windows
# Ejecuta este script en PowerShell como Administrador
# Requisito: Docker Desktop instalado y corriendo
# ═══════════════════════════════════════════════════
#Requires -Version 5.1
$ErrorActionPreference = "Stop"

# ── Colors helper ──
function Write-Color($color, $text) { Write-Host $text -ForegroundColor $color }
function Write-Step($text) { Write-Host "  $text" -ForegroundColor Green }
function Write-Info($text) { Write-Host "  $text" -ForegroundColor Cyan }
function Write-Warn($text) { Write-Host "  $text" -ForegroundColor Yellow }

Write-Host ""
Write-Host "  ╔════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║    KaiRest POS — Instalacion Windows   ║" -ForegroundColor Cyan
Write-Host "  ╚════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── Verify Docker ──
try {
    $dockerInfo = docker info 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Docker not running" }
    Write-Step "Docker esta corriendo"
} catch {
    Write-Color Red "  ERROR: Docker no esta corriendo."
    Write-Host ""
    Write-Host "  Abre Docker Desktop primero y vuelve a ejecutar este script." -ForegroundColor Yellow
    Write-Host "  Descarga Docker: https://www.docker.com/products/docker-desktop" -ForegroundColor Cyan
    Write-Host ""
    exit 1
}

# ── Verify docker compose ──
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
    Write-Color Red "  ERROR: Docker Compose no encontrado."
    Write-Host "  Asegurate de tener Docker Desktop actualizado." -ForegroundColor Yellow
    exit 1
}
Write-Step "Docker Compose disponible"

# ── Verify git ──
try {
    git --version 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Git not found" }
    Write-Step "Git disponible"
} catch {
    Write-Color Red "  ERROR: Git no encontrado."
    Write-Host "  Descarga Git: https://git-scm.com/download/win" -ForegroundColor Cyan
    exit 1
}

# ── Clone or update repo ──
$installDir = Join-Path $env:USERPROFILE "kairest"
Write-Host ""
Write-Info "Instalando en: $installDir"

if (Test-Path (Join-Path $installDir ".git")) {
    Write-Info "Actualizando codigo existente..."
    Push-Location $installDir
    try {
        git pull --rebase 2>&1 | Out-Null
    } catch {
        Write-Warn "No se pudo actualizar el codigo."
    }
} else {
    Write-Info "Descargando KaiRest..."
    git clone https://github.com/marqdomi/kairest.git $installDir 2>&1 | Select-Object -Last 2
    Push-Location $installDir
}

# Create backups directory
if (-not (Test-Path "backups")) { New-Item -ItemType Directory -Path "backups" | Out-Null }
Write-Step "Codigo descargado"

# ── Configure .env ──
$envFile = Join-Path $installDir ".env"
if (-not (Test-Path $envFile)) {
    # Generate random secrets
    $secretBytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RNGCryptoServiceProvider]::new()
    $rng.GetBytes($secretBytes)
    $secretKey = ($secretBytes | ForEach-Object { $_.ToString("x2") }) -join ""
    $rng.Dispose()

    $pgPassBytes = New-Object byte[] 8
    $rng2 = [System.Security.Cryptography.RNGCryptoServiceProvider]::new()
    $rng2.GetBytes($pgPassBytes)
    $pgPass = "kairest_" + (($pgPassBytes | ForEach-Object { $_.ToString("x2") }) -join "")
    $rng2.Dispose()

    $envContent = @"
SECRET_KEY=$secretKey
POSTGRES_PASSWORD=$pgPass
APP_PORT=5005
CORS_ORIGINS=http://localhost:5005
"@
    Set-Content -Path $envFile -Value $envContent -Encoding UTF8
    Write-Step ".env creado con SECRET_KEY automatica"
} else {
    Write-Warn ".env ya existe — no se modifico"
}

# ── Start services ──
Write-Host ""
Write-Info "Iniciando KaiRest POS..."
Write-Host "  (primera vez puede tardar 2-5 min compilando la imagen)" -ForegroundColor DarkGray
Write-Host ""

if ($composeCmd -eq "docker compose") {
    docker compose up -d --build 2>&1 | Select-Object -Last 8
} else {
    docker-compose up -d --build 2>&1 | Select-Object -Last 8
}

# ── Wait for health ──
Write-Info "Esperando a que la aplicacion inicie..."

# Read port from .env or default
$port = "5005"
$envLines = Get-Content $envFile -ErrorAction SilentlyContinue
foreach ($line in $envLines) {
    if ($line -match "^APP_PORT=(\d+)") { $port = $Matches[1] }
}

$healthUrl = "http://localhost:${port}/health"
$maxRetries = 90
$healthy = $false

for ($i = 1; $i -le $maxRetries; $i++) {
    try {
        $response = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 3 -ErrorAction SilentlyContinue
        if ($response.StatusCode -eq 200) {
            $healthy = $true
            break
        }
    } catch {}
    Start-Sleep -Seconds 2
    Write-Host "." -NoNewline
}

Write-Host ""

if ($healthy) {
    Write-Host ""
    Write-Host "  ╔════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "  ║   KaiRest instalado exitosamente!      ║" -ForegroundColor Green
    Write-Host "  ╚════════════════════════════════════════╝" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Abre tu navegador en:" -ForegroundColor White
    Write-Host "  --> http://localhost:${port}" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Veras el asistente de configuracion para" -ForegroundColor DarkGray
    Write-Host "  registrar tu restaurante y crear tu usuario." -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  Para actualizar:  cd ~\kairest; .\update.ps1" -ForegroundColor Yellow
    Write-Host "  Para detener:     cd ~\kairest; docker compose down" -ForegroundColor Yellow
    Write-Host "  Para reiniciar:   cd ~\kairest; docker compose restart" -ForegroundColor Yellow
    Write-Host ""

    # Try to open in default browser
    try {
        Start-Process "http://localhost:${port}"
    } catch {}
} else {
    Write-Host ""
    Write-Color Red "  La app no respondio en 3 minutos."
    if ($composeCmd -eq "docker compose") {
        Write-Host "  Revisa los logs con: docker compose logs web" -ForegroundColor Yellow
    } else {
        Write-Host "  Revisa los logs con: docker-compose logs web" -ForegroundColor Yellow
    }
    exit 1
}

Pop-Location
