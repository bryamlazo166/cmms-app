$ErrorActionPreference = "SilentlyContinue"

try {
    $r = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:5009/api/system/db-status" -TimeoutSec 5
    $j = $r.Content | ConvertFrom-Json
    Write-Host "Servidor: ACTIVO (5009)" -ForegroundColor Green
    Write-Host "Modo DB: $($j.mode)"
    Write-Host "Build:   $($j.build)"
    Write-Host "DB URI:  $($j.uri_masked)"
} catch {
    Write-Host "Servidor: INACTIVO en 127.0.0.1:5009" -ForegroundColor Red
}
