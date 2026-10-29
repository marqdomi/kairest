# ===================================================
# KaiRest POS - Instalacion para Windows
# Ejecuta este script en PowerShell como Administrador
# Requisito: Docker Desktop instalado y corriendo
# ===================================================
#Requires -Version 5.1
$ErrorActionPreference = "Stop"

# -- Colors helper --
function Write-Color($color, $text) { Write-Host $text -ForegroundColor $color }
function Write-Step($text) { Write-Host "  $text" -ForegroundColor Green }
function Write-Info($text) { Write-Host "  $text" -ForegroundColor Cyan }
function Write-Warn($text) { Write-Host "  $text" -ForegroundColor Yellow }

Write-Host ""
Write-Host "  +========================================+" -ForegroundColor Cyan
Write-Host "  |    KaiRest POS - Instalacion Windows   |" -ForegroundColor Cyan
Write-Host "  +========================================+" -ForegroundColor Cyan
Write-Host ""

# -- Verify Docker --
try {
    $dockerInfo = docker info
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

# -- Verify docker compose --
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
    Write-Color Red "  ERROR: Docker Compose no encontrado."
    Write-Host "  Asegurate de tener Docker Desktop actualizado." -ForegroundColor Yellow
    exit 1
}
Write-Step "Docker Compose disponible"

# -- Locate code: imagen publicada, carpeta del proyecto, o clone con git --
# Modo IMAGEN (el del instalador para clientes): solo hay docker-compose.prod.yml.
#   La aplicacion se descarga ya compilada desde GHCR, asi que la instalacion no
#   compila nada, no necesita Git y el codigo no vive en la maquina del cliente.
#   Actualizar es descargar la imagen nueva: un parche no requiere ir al negocio.
# Modo BUILD: hay docker-compose.yml (codigo fuente al lado) y se compila local.
# Modo GIT: no hay ninguno de los dos, se clona el repositorio.
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$composeFile = ""      # vacio = docker-compose.yml por omision
$modoImagen = $false

if (Test-Path (Join-Path $scriptDir "docker-compose.yml")) {
    $installDir = $scriptDir
    Write-Host ""
    Write-Info "Proyecto detectado en: $installDir (compilacion local)"
    Push-Location $installDir
} elseif (Test-Path (Join-Path $scriptDir "docker-compose.prod.yml")) {
    $installDir = $scriptDir
    $composeFile = "-f docker-compose.prod.yml"
    $modoImagen = $true
    Write-Host ""
    Write-Info "Instalando en: $installDir"
    Write-Info "Se descargara la aplicacion ya preparada (no se compila nada aqui)."
    Push-Location $installDir
} else {
    try {
        git --version | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Git not found" }
        Write-Step "Git disponible"
    } catch {
        Write-Color Red "  ERROR: Git no encontrado y el script no esta dentro de la carpeta del proyecto."
        Write-Host "  Opcion A: copia la carpeta completa del proyecto y ejecuta install.ps1 desde adentro." -ForegroundColor Yellow
        Write-Host "  Opcion B: instala Git (https://git-scm.com/download/win) y vuelve a ejecutar." -ForegroundColor Cyan
        exit 1
    }

    $installDir = Join-Path $env:USERPROFILE "kairest"
    Write-Host ""
    Write-Info "Instalando en: $installDir"

    if (Test-Path (Join-Path $installDir ".git")) {
        Write-Info "Actualizando codigo existente..."
        Push-Location $installDir
        try {
            git pull --rebase | Out-Null
        } catch {
            Write-Warn "No se pudo actualizar el codigo."
        }
    } else {
        Write-Info "Descargando KaiRest..."
        git clone https://github.com/marqdomi/kairest.git $installDir | Select-Object -Last 2
        Push-Location $installDir
    }
}

# Create backups directory
if (-not (Test-Path "backups")) { New-Item -ItemType Directory -Path "backups" | Out-Null }
Write-Step $(if ($modoImagen) { "Archivos listos" } else { "Codigo descargado" })

# -- Configure .env --
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
    Write-Warn ".env ya existe - no se modifico"
}

# -- Start services --
Write-Host ""
Write-Info "Iniciando KaiRest POS..."
$compose = ("$composeCmd $composeFile").Trim()

if ($modoImagen) {
    Write-Host "  (la primera vez descarga la aplicacion: unos minutos segun tu internet)" -ForegroundColor DarkGray
    Write-Host ""
    # `pull` por separado para que un fallo de descarga se vea claro y no se
    # confunda con un problema al arrancar los servicios.
    cmd /c "$compose pull" | Select-Object -Last 5
    if ($LASTEXITCODE -ne 0) {
        Write-Color Red "  ERROR: no se pudo descargar la aplicacion."
        Write-Host "  Revisa la conexion a internet y vuelve a ejecutar el instalador." -ForegroundColor Yellow
        exit 1
    }
    cmd /c "$compose up -d" | Select-Object -Last 8
} else {
    Write-Host "  (primera vez puede tardar 2-5 min compilando la imagen)" -ForegroundColor DarkGray
    Write-Host ""
    cmd /c "$compose up -d --build" | Select-Object -Last 8
}

# -- Wait for health --
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
    Write-Host "  +========================================+" -ForegroundColor Green
    Write-Host "  |   KaiRest instalado exitosamente!      |" -ForegroundColor Green
    Write-Host "  +========================================+" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Abre tu navegador en:" -ForegroundColor White
    Write-Host "  --> http://localhost:${port}" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Veras el asistente de configuracion para" -ForegroundColor DarkGray
    Write-Host "  registrar tu restaurante y crear tu usuario." -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  Usa los accesos directos de KaiRest en el menu inicio, o:" -ForegroundColor DarkGray
    Write-Host "  Para actualizar:  .\update.ps1" -ForegroundColor Yellow
    Write-Host "  Para detener:     $compose down" -ForegroundColor Yellow
    Write-Host "  Para reiniciar:   $compose restart" -ForegroundColor Yellow
    Write-Host ""

    # Try to open in default browser
    try {
        Start-Process "http://localhost:${port}"
    } catch {}
} else {
    Write-Host ""
    Write-Color Red "  La app no respondio en 3 minutos."
    Write-Host "  Revisa los logs con: $compose logs web" -ForegroundColor Yellow
    exit 1
}

Pop-Location
