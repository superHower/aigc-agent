$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $project
& (Join-Path $PSScriptRoot 'start-local.ps1')
