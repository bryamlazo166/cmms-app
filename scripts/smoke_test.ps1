param(
    [string]$BaseUrl = "http://127.0.0.1:5009"
)

$endpoints = @(
    "/",
    "/avisos",
    "/ordenes",
    "/almacen",
    "/reportes",
    "/lubricacion",
    "/monitoreo",
    "/activos-rotativos",
    "/herramientas",
    "/compras",
    "/api/system/db-status",
    "/api/dashboard-stats",
    "/api/tools",
    "/api/warehouse",
    "/api/work-orders",
    "/api/notices",
    "/api/reports/kpis",
    "/api/reports/recurrent-failures",
    "/api/reports/executive",
    "/api/lubrication/dashboard",
    "/api/monitoring/dashboard",
    "/api/rotative-assets",
    "/api/purchase-requests",
    "/api/purchase-orders",
    "/api/list-spare-parts",
    "/api/export-data",
    "/api/download-template"
)

$allOk = $true
foreach ($path in $endpoints) {
    $url = "$BaseUrl$path"
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 12
        Write-Host "OK  $($response.StatusCode)  $path" -ForegroundColor Green
    }
    catch {
        $allOk = $false
        if ($_.Exception.Response) {
            $code = [int]$_.Exception.Response.StatusCode.value__
            Write-Host "ERR $code  $path" -ForegroundColor Red
        }
        else {
            Write-Host "ERR ---  $path :: $($_.Exception.Message)" -ForegroundColor Red
        }
    }
}

# POST endpoints that are expected to return 400 with empty payload
$postChecks = @(
    @{ Path = "/api/upload-excel"; Body = $null },
    @{ Path = "/api/bulk-paste"; Body = "{}" },
    @{ Path = "/api/bulk-paste-hierarchy"; Body = "{}" }
)

foreach ($check in $postChecks) {
    $url = "$BaseUrl$($check.Path)"
    try {
        $params = @{ Uri = $url; Method = "POST"; TimeoutSec = 12; UseBasicParsing = $true }
        if ($check.Body) {
            $params['ContentType'] = 'application/json'
            $params['Body'] = $check.Body
        }
        $response = Invoke-WebRequest @params
        Write-Host "POST OK  $($response.StatusCode)  $($check.Path)" -ForegroundColor Green
    }
    catch {
        if ($_.Exception.Response) {
            $code = [int]$_.Exception.Response.StatusCode.value__
            if ($code -eq 400 -or $code -eq 422) {
                Write-Host "POST OK  $code  $($check.Path) (expected validation)" -ForegroundColor Green
            }
            else {
                $allOk = $false
                Write-Host "POST ERR $code  $($check.Path)" -ForegroundColor Red
            }
        }
        else {
            $allOk = $false
            Write-Host "POST ERR ---  $($check.Path) :: $($_.Exception.Message)" -ForegroundColor Red
        }
    }
}

if ($allOk) {
    Write-Host "Smoke test finished: ALL CHECKS PASSED" -ForegroundColor Green
    exit 0
}

Write-Host "Smoke test finished: SOME CHECKS FAILED" -ForegroundColor Red
exit 1
