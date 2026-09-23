$ErrorActionPreference = "Continue"

Set-Location $PSScriptRoot

$Root = $PSScriptRoot
$RunDir = Join-Path $Root ".run"

$Services = @(
    "news_worker",
    "market_worker",
    "api"
)

foreach ($Name in $Services) {

    $PidFile = Join-Path $RunDir ($Name + ".pid")

    if (-not (Test-Path $PidFile)) {
        Write-Host "[SKIP] $Name not running"
        continue
    }

    try {

        $PidValue = [int](Get-Content $PidFile -Raw)

        $Process = Get-Process `
            -Id $PidValue `
            -ErrorAction Stop

        if ($Process.ProcessName -like "python*") {

            Write-Host "[STOP] $Name PID=$PidValue"

            Stop-Process `
                -Id $PidValue `
                -Force `
                -ErrorAction Stop

            Write-Host "[STOPPED] $Name"

        } else {

            Write-Host "[STALE] $Name PID=$PidValue is not Python"
        }

    } catch {

        Write-Host "[STALE] $Name PID file"

    }

    Remove-Item `
        $PidFile `
        -Force `
        -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "Korea Market Radar stopped."
