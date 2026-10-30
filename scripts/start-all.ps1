$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $project
& (Join-Path $project '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'start-natapp.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& (Join-Path $PSScriptRoot 'start-local.ps1')
