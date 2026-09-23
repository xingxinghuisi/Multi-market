Set-Location $PSScriptRoot

$Root = $PSScriptRoot
$RunDir = Join-Path $Root ".run"
$LogDir = Join-Path $Root "logs"

$Services = @(
    "api",
    "market_worker",
    "news_worker"
)

Write-Host ""
Write-Host "========================================"
Write-Host " Korea Market Radar Status"
Write-Host "========================================"

foreach ($Name in $Services) {

    $PidFile = Join-Path $RunDir ($Name + ".pid")

    if (-not (Test-Path $PidFile)) {
        Write-Host "[DOWN] $Name - no PID file"
        continue
    }

    try {

        $PidValue = [int](Get-Content $PidFile -Raw)

        $Process = Get-Process `
            -Id $PidValue `
            -ErrorAction Stop

        Write-Host "[UP]   $Name PID=$PidValue"

    } catch {

        Write-Host "[DOWN] $Name - stale PID file"
    }
}

Write-Host ""
Write-Host "API health:"

try {

    $Response = Invoke-WebRequest `
        -Uri "http://127.0.0.1:8000/docs" `
        -UseBasicParsing `
        -TimeoutSec 3

    if ($Response.StatusCode -eq 200) {
        Write-Host "[OK]   http://127.0.0.1:8000"
    }

} catch {

    Write-Host "[FAIL] API not responding"
}

Write-Host ""
Write-Host "===== API LOG ====="

if (Test-Path "$LogDir\api.log") {
    Get-Content "$LogDir\api.log" -Tail 8
}

Write-Host ""
Write-Host "===== MARKET WORKER LOG ====="

if (Test-Path "$LogDir\market_worker.log") {
    Get-Content "$LogDir\market_worker.log" -Tail 12
}

Write-Host ""
Write-Host "===== NEWS WORKER LOG ====="

if (Test-Path "$LogDir\news_worker.log") {
    Get-Content "$LogDir\news_worker.log" -Tail 12
}

Write-Host ""
