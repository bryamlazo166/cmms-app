# ── Supabase keep-alive ──────────────────────────────────────────────────────
# Hace una consulta minima a la API REST de Supabase para que el proyecto
# free-tier registre actividad y no se pause a los 7 dias de inactividad
# (proyecto pausado 90 dias = eliminado). Se ejecuta via tarea programada
# de Windows "Supabase CMMS KeepAlive" (lunes y jueves 12:00; si la PC
# estaba apagada, corre al encenderla).
#
# Lee SUPABASE_URL y SUPABASE_SERVICE_KEY del .env del proyecto (no duplica
# credenciales). Log en %LOCALAPPDATA%\cmms\supabase_keepalive.log
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$root = Split-Path -Parent $PSScriptRoot   # scripts\ -> raiz del repo
$envFile = Join-Path $root '.env'
$logDir = Join-Path $env:LOCALAPPDATA 'cmms'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }
$logFile = Join-Path $logDir 'supabase_keepalive.log'

function Write-Log($msg) {
    $line = "{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $logFile -Value $line -Encoding utf8
    Write-Output $line
}

try {
    $vars = @{}
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*([^#=]+)=(.*)$') { $vars[$Matches[1].Trim()] = $Matches[2].Trim() }
    }
    $url = $vars['SUPABASE_URL']
    $key = $vars['SUPABASE_SERVICE_KEY']
    if (-not $url -or -not $key) { throw ".env sin SUPABASE_URL o SUPABASE_SERVICE_KEY" }

    $headers = @{ apikey = $key; Authorization = "Bearer $key" }
    $resp = Invoke-RestMethod -Uri "$url/rest/v1/users?select=id&limit=1" -Headers $headers -TimeoutSec 30
    Write-Log "OK keep-alive: consulta REST a 'users' respondio ($(@($resp).Count) fila(s))"
    exit 0
} catch {
    Write-Log "ERROR keep-alive: $($_.Exception.Message)"
    exit 1
}
