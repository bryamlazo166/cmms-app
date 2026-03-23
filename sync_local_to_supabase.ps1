param(
    [string]$SourceDb = "",
    [switch]$SkipCreateTables
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (!(Test-Path $pythonExe)) {
    Write-Host "[ERROR] No se encontro .venv\Scripts\python.exe" -ForegroundColor Red
    exit 1
}

if ([string]::IsNullOrWhiteSpace($SourceDb)) {
    if (Test-Path (Join-Path $projectRoot "cmms_v2.db")) {
        $SourceDb = Join-Path $projectRoot "cmms_v2.db"
    } elseif (Test-Path (Join-Path $projectRoot "instance\cmms_v2.db")) {
        $SourceDb = Join-Path $projectRoot "instance\cmms_v2.db"
    } else {
        Write-Host "[ERROR] No se encontro una base SQLite fuente (cmms_v2.db)." -ForegroundColor Red
        exit 1
    }
}

Write-Host "Sincronizando SQLite -> Supabase" -ForegroundColor Cyan
Write-Host "Fuente SQLite: $SourceDb"

$args = @("migrate_to_supabase.py", "--source", $SourceDb, "--yes")
if (-not $SkipCreateTables) {
    $args += "--create-tables"
}

& $pythonExe $args
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] La sincronizacion fallo." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "Sincronizacion completada." -ForegroundColor Green
Write-Host "Tip: ejecuta .\start_cmms_supabase.ps1 para operar en modo nube."
