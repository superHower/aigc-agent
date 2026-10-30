$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
function Ready([string]$url) {
    try { return (Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch { return $false }
}
try {
    $python = Join-Path $project '.venv\Scripts\python.exe'
    $frontend = Join-Path $project 'frontend'
    if (!(Test-Path $python)) { throw 'Project Python environment is missing.' }
    $node = (Get-Command node -ErrorAction Stop).Source
    if (!(Ready 'http://127.0.0.1:8000/api/health')) {
        if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { throw 'Port 8000 is occupied.' }
        Start-Process $python -ArgumentList '-m uvicorn backend.main:app --host 0.0.0.0 --port 8000' -WorkingDirectory $project -WindowStyle Hidden -RedirectStandardOutput (Join-Path $project 'backend\dev.stdout.log') -RedirectStandardError (Join-Path $project 'backend\dev.stderr.log') | Out-Null
    }
    if (!(Ready 'http://127.0.0.1:5173')) {
        if (Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue) { throw 'Port 5173 is occupied.' }
        Start-Process $node -ArgumentList 'node_modules/vite/bin/vite.js --host 0.0.0.0 --port 5173 --strictPort' -WorkingDirectory $frontend -WindowStyle Hidden -RedirectStandardOutput (Join-Path $frontend 'dev.stdout.log') -RedirectStandardError (Join-Path $frontend 'dev.stderr.log') | Out-Null
    }
    Write-Host 'Waiting for services...'
    $deadline = (Get-Date).AddSeconds(90)
    do {
        if ((Ready 'http://127.0.0.1:8000/api/health') -and (Ready 'http://127.0.0.1:5173/api/health')) {
            Start-Process 'http://localhost:5173'
            exit 0
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw "Startup timed out. Check backend\dev.stderr.log and frontend\dev.stderr.log in $project."
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
