param(
    [string]$DatabaseUrl = ""
)

$ErrorActionPreference = "SilentlyContinue"
$projectRoot = "D:\PROGRAMACION\CMMS_Industrial"

function Read-DatabaseUrlFromEnv {
    $envFile = Join-Path $projectRoot ".env"
    if (!(Test-Path $envFile)) { return "" }
    $line = Select-String -Path $envFile -Pattern '^DATABASE_URL=' | Select-Object -First 1
    if (!$line) { return "" }
    return ($line.Line -replace '^DATABASE_URL=', '').Trim()
}

if ([string]::IsNullOrWhiteSpace($DatabaseUrl)) {
    $DatabaseUrl = Read-DatabaseUrlFromEnv
}

if ([string]::IsNullOrWhiteSpace($DatabaseUrl)) {
    Write-Host "No se encontro DATABASE_URL. Configura .env primero." -ForegroundColor Red
    exit 1
}

if ($DatabaseUrl.StartsWith("postgres://")) {
    $DatabaseUrl = $DatabaseUrl -replace '^postgres://', 'postgresql://'
}

try {
    $uri = [System.Uri]$DatabaseUrl
} catch {
    Write-Host "DATABASE_URL invalida. Revisa formato." -ForegroundColor Red
    exit 1
}

$hostName = $uri.Host
$port = $uri.Port

Write-Host "Probando conectividad a Supabase..." -ForegroundColor Cyan
Write-Host "Host: $hostName  Puerto: $port"

$resultMain = Test-NetConnection -ComputerName $hostName -Port $port
Write-Host ("TCP {0}:{1} => {2}" -f $hostName, $port, $resultMain.TcpTestSucceeded)

if ($port -ne 6543) {
    $resultPooler = Test-NetConnection -ComputerName $hostName -Port 6543
    Write-Host ("TCP {0}:{1} => {2}" -f $hostName, 6543, $resultPooler.TcpTestSucceeded)
}

Write-Host ""
if ($resultMain.TcpTestSucceeded) {
    Write-Host "Conectividad de red OK para tu DATABASE_URL actual." -ForegroundColor Green
} else {
    Write-Host "No hay conectividad TCP al host/puerto actual." -ForegroundColor Yellow
    Write-Host "Sugerencia: usa la cadena 'Transaction Pooler' de Supabase (puerto 6543)." -ForegroundColor Yellow
}
