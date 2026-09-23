$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv_clean\Scripts\python.exe"
$LogDir = Join-Path $Root "logs"
$RunDir = Join-Path $Root ".run"
$EnvFile = Join-Path $Root ".env"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null

if (-not (Test-Path $Python)) {
    throw "Python not found: $Python"
}

$env:PYTHONUTF8 = "1"
$env:PYTHONUNBUFFERED = "1"

# =========================================================
# Load .env
# =========================================================

if (Test-Path $EnvFile) {

    $envJson = & $Python -c "from dotenv import dotenv_values; import json; print(json.dumps({k:v for k,v in dotenv_values('.env').items() if v is not None}, ensure_ascii=False))"

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to read .env"
    }

    if ($envJson) {

        $envObject = $envJson | ConvertFrom-Json

        foreach ($property in $envObject.PSObject.Properties) {

            Set-Item `
                -Path ("Env:" + $property.Name) `
                -Value ([string]$property.Value)
        }
    }

    Write-Host "[ENV] .env loaded"

} else {

    Write-Warning ".env not found"
}

# =========================================================
# PID helpers
# =========================================================

function Get-RadarPid {

    param(
        [string]$Name
    )

    $PidFile = Join-Path $RunDir ($Name + ".pid")

    if (-not (Test-Path $PidFile)) {
        return $null
    }

    try {

        $PidValue = [int](Get-Content $PidFile -Raw)

        $Process = Get-Process `
            -Id $PidValue `
            -ErrorAction Stop

        if ($Process.ProcessName -like "python*") {
            return $PidValue
        }

    } catch {
    }

    Remove-Item `
        $PidFile `
        -Force `
        -ErrorAction SilentlyContinue

    return $null
}


function Start-RadarProcess {

    param(
        [string]$Name,
        [string[]]$Arguments
    )

    $ExistingPid = Get-RadarPid $Name

    if ($ExistingPid) {
        Write-Host "[SKIP] $Name already running PID=$ExistingPid"
        return
    }

    $StdoutLog = Join-Path $LogDir ($Name + ".log")
    $StderrLog = Join-Path $LogDir ($Name + ".error.log")
    $PidFile = Join-Path $RunDir ($Name + ".pid")

    $Process = Start-Process `
        -FilePath $Python `
        -ArgumentList $Arguments `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $StdoutLog `
        -RedirectStandardError $StderrLog `
        -PassThru `
        -WindowStyle Hidden

    Set-Content `
        -Path $PidFile `
        -Value $Process.Id

    Start-Sleep -Milliseconds 800

    $Process.Refresh()

    if ($Process.HasExited) {

        Remove-Item `
            $PidFile `
            -Force `
            -ErrorAction SilentlyContinue

        Write-Host "[ERROR] $Name exited immediately."

        if (Test-Path $StderrLog) {
            Write-Host ""
            Write-Host "===== $Name error log ====="
            Get-Content $StderrLog -Tail 30
        }

        throw "$Name startup failed"
    }

    Write-Host "[STARTED] $Name PID=$($Process.Id)"
}

# =========================================================
# Check port 8000
# =========================================================

$ExistingApiPid = Get-RadarPid "api"

if (-not $ExistingApiPid) {

    $PortInUse = Get-NetTCPConnection `
        -LocalPort 8000 `
        -State Listen `
        -ErrorAction SilentlyContinue

    if ($PortInUse) {
        throw "Port 8000 is already in use. Stop the manually started API first."
    }
}

# =========================================================
# API
# =========================================================

Start-RadarProcess `
    -Name "api" `
    -Arguments @(
        "-m",
        "uvicorn",
        "api:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000"
    )

# =========================================================
# Wait for API
# =========================================================

Write-Host "[WAIT] API health check..."

$ApiReady = $false

for ($i = 0; $i -lt 30; $i++) {

    try {

        $Response = Invoke-WebRequest `
            -Uri "http://127.0.0.1:8000/docs" `
            -UseBasicParsing `
            -TimeoutSec 2

        if ($Response.StatusCode -eq 200) {
            $ApiReady = $true
            break
        }

    } catch {
    }

    Start-Sleep -Milliseconds 500
}

if (-not $ApiReady) {

    Write-Host "[ERROR] API failed health check."

    $ApiErrorLog = Join-Path $LogDir "api.error.log"

    if (Test-Path $ApiErrorLog) {
        Get-Content $ApiErrorLog -Tail 30
    }

    throw "API startup failed"
}

Write-Host "[OK] API ready"

# =========================================================
# Market Worker
# =========================================================

Start-RadarProcess `
    -Name "market_worker" `
    -Arguments @(
        "market_worker.py"
    )

# =========================================================
# News Worker
# =========================================================

Start-RadarProcess `
    -Name "news_worker" `
    -Arguments @(
        "news_worker.py"
    )

Write-Host ""
Write-Host "========================================"
Write-Host " Korea Market Radar started"
Write-Host "========================================"
Write-Host ""
Write-Host "API:     http://127.0.0.1:8000"
Write-Host "Swagger: http://127.0.0.1:8000/docs"
Write-Host "Logs:    $LogDir"
Write-Host ""
