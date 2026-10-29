# ===================================================
# KaiRest POS - Copia de respaldos fuera de la laptop (Windows)
#
# Los respaldos automaticos se guardan cada hora en .\backups\, pero en el
# MISMO disco: si esa laptop se dana o se la roban, el negocio pierde todo.
# Este script copia el respaldo mas reciente a un USB o a una carpeta que la
# nube sincronice (OneDrive, Google Drive), y verifica que la copia sirva.
#
# Uso:
#   .\respaldo-externo.ps1                    # usa BACKUP_EXTERNO_DIR del .env
#   .\respaldo-externo.ps1 -Destino D:\KaiRest
#   .\respaldo-externo.ps1 -InstalarTarea     # lo programa todos los dias
# ===================================================
#Requires -Version 5.1
param(
    [string]$Destino,
    [int]$Conservar = 30,
    [switch]$InstalarTarea,
    [string]$HoraTarea = "23:30"
)

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
$origen = Join-Path $raiz "backups"
$log = Join-Path $origen "respaldo-externo.log"

function Escribir($texto, $color = "Gray") {
    $linea = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $texto
    Write-Host "  $texto" -ForegroundColor $color
    try { Add-Content -Path $log -Value $linea -Encoding utf8 } catch {}
}

# -- Destino: parametro, .env, o error --
if (-not $Destino) {
    $envFile = Join-Path $raiz ".env"
    if (Test-Path $envFile) {
        foreach ($linea in (Get-Content $envFile -ErrorAction SilentlyContinue)) {
            if ($linea -match "^\s*BACKUP_EXTERNO_DIR\s*=\s*(.+?)\s*$") {
                $Destino = $Matches[1].Trim('"').Trim("'")
            }
        }
    }
}

# -- Programar la tarea diaria y salir --
if ($InstalarTarea) {
    if (-not $Destino) {
        Write-Host "  ERROR: indica el destino. Ejemplo:" -ForegroundColor Red
        Write-Host "    .\respaldo-externo.ps1 -InstalarTarea -Destino D:\KaiRest" -ForegroundColor Yellow
        exit 1
    }
    $script = Join-Path $raiz "respaldo-externo.ps1"
    $accion = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument ("-NoProfile -ExecutionPolicy Bypass -File `"$script`" -Destino `"$Destino`"")
    $disparador = New-ScheduledTaskTrigger -Daily -At $HoraTarea
    $ajustes = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries
    Register-ScheduledTask -TaskName "KaiRest - Respaldo externo" -Action $accion `
        -Trigger $disparador -Settings $ajustes -Description "Copia el respaldo de KaiRest fuera de la laptop" -Force | Out-Null
    Write-Host ""
    Write-Host "  Listo: se respaldara todos los dias a las $HoraTarea en $Destino" -ForegroundColor Green
    Write-Host "  Deja conectado el USB (o la carpeta de la nube) a esa hora." -ForegroundColor Yellow
    Write-Host ""
    exit 0
}

Write-Host ""
Write-Host "  +========================================+" -ForegroundColor Cyan
Write-Host "  |   KaiRest - Respaldo fuera del equipo  |" -ForegroundColor Cyan
Write-Host "  +========================================+" -ForegroundColor Cyan
Write-Host ""

if (-not $Destino) {
    Escribir "ERROR: no hay destino configurado." "Red"
    Write-Host ""
    Write-Host "  Indica a donde copiar los respaldos, por ejemplo:" -ForegroundColor Yellow
    Write-Host "    .\respaldo-externo.ps1 -Destino D:\KaiRest" -ForegroundColor Cyan
    Write-Host "    .\respaldo-externo.ps1 -Destino `"$env:USERPROFILE\OneDrive\KaiRest`"" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  O agrega esta linea al archivo .env:" -ForegroundColor Yellow
    Write-Host "    BACKUP_EXTERNO_DIR=D:\KaiRest" -ForegroundColor Cyan
    Write-Host ""
    exit 1
}

# -- Respaldo mas reciente --
if (-not (Test-Path $origen)) {
    Escribir "ERROR: no existe la carpeta backups. Ejecuta esto desde la carpeta de KaiRest." "Red"
    exit 1
}
$ultimo = Get-ChildItem -Path (Join-Path $origen "*.dump") -ErrorAction SilentlyContinue |
          Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $ultimo) {
    Escribir "ERROR: no hay ningun respaldo en .\backups. Revisa que KaiRest este corriendo." "Red"
    exit 1
}

# Un dump valido empieza con "PGDMP"; uno truncado o de 0 bytes no sirve y es
# peor que no tener respaldo, porque da falsa tranquilidad.
if ($ultimo.Length -lt 1024) {
    Escribir ("ERROR: el respaldo {0} pesa {1} bytes: esta incompleto." -f $ultimo.Name, $ultimo.Length) "Red"
    exit 1
}
$cabecera = [System.IO.File]::ReadAllBytes($ultimo.FullName)[0..4]
if ([System.Text.Encoding]::ASCII.GetString($cabecera) -ne "PGDMP") {
    Escribir ("ERROR: {0} no es un respaldo valido de PostgreSQL." -f $ultimo.Name) "Red"
    exit 1
}

# -- Destino disponible --
try {
    if (-not (Test-Path $Destino)) { New-Item -ItemType Directory -Path $Destino -Force | Out-Null }
} catch {
    Escribir "ERROR: no se puede escribir en $Destino." "Red"
    Write-Host "  Si es un USB, conectalo y vuelve a intentar." -ForegroundColor Yellow
    exit 1
}

# -- Copiar y verificar --
$nombre = "kairest_{0}.dump" -f (Get-Date -Format "yyyyMMdd_HHmmss")
$copia = Join-Path $Destino $nombre
Copy-Item -Path $ultimo.FullName -Destination $copia -Force

# Se compara el tamano: una copia a medias en un USB que se desconecto pasaria
# desapercibida sin esta verificacion.
$destinoInfo = Get-Item $copia
if ($destinoInfo.Length -ne $ultimo.Length) {
    Escribir ("ERROR: la copia quedo incompleta ({0} de {1} bytes)." -f $destinoInfo.Length, $ultimo.Length) "Red"
    Remove-Item $copia -Force -ErrorAction SilentlyContinue
    exit 1
}

$mb = "{0:N2} MB" -f ($destinoInfo.Length / 1MB)
Escribir "Respaldo copiado: $nombre ($mb)" "Green"
Escribir "Destino: $Destino"

# -- Retencion --
$viejos = Get-ChildItem -Path (Join-Path $Destino "kairest_*.dump") -ErrorAction SilentlyContinue |
          Sort-Object LastWriteTime -Descending | Select-Object -Skip $Conservar
foreach ($v in $viejos) {
    Remove-Item $v.FullName -Force -ErrorAction SilentlyContinue
    Escribir "Eliminado respaldo antiguo: $($v.Name)"
}

$total = (Get-ChildItem -Path (Join-Path $Destino "kairest_*.dump") -ErrorAction SilentlyContinue).Count
Write-Host ""
Write-Host "  Hay $total respaldo(s) guardados fuera de la laptop." -ForegroundColor Green
Write-Host "  Para restaurar uno:  .\restore.ps1 `"$copia`"" -ForegroundColor Cyan
Write-Host ""
exit 0
