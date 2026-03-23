param(
    [ValidateSet("auto", "local", "supabase")]
    [string]$Mode = "supabase"
)

$ErrorActionPreference = "SilentlyContinue"
$projectRoot = "D:\PROGRAMACION\CMMS_Industrial"
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
$appFile = Join-Path $projectRoot "app.py"

if (!(Test-Path $pythonExe)) {
    Write-Host "No se encontro Python del entorno virtual en: $pythonExe" -ForegroundColor Red
    exit 1
}

$listeners = netstat -ano | Select-String ":5009" | Select-String "LISTENING"
if ($listeners) {
    $pids = @()
    foreach ($line in $listeners) {
        $parts = ($line.ToString() -split "\s+") | Where-Object { $_ -ne "" }
        if ($parts.Count -gt 0) { $pids += $parts[-1] }
    }
    $pids = $pids | Sort-Object -Unique
    foreach ($id in $pids) {
        try { taskkill /PID $id /F | Out-Null } catch {}
    }
    Start-Sleep -Seconds 1
}

Set-Location $projectRoot
if (-not $env:LOCAL_DATABASE_URL) {
    $env:LOCAL_DATABASE_URL = "sqlite:///cmms_v2.db"
}
$env:DB_MODE = $Mode

Write-Host "Iniciando CMMS en http://127.0.0.1:5009 ..." -ForegroundColor Cyan
Write-Host "Modo de base de datos: $Mode" -ForegroundColor Yellow
& $pythonExe $appFile
