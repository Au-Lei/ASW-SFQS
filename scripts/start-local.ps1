#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$previousAppEnvironment = $env:APP_ENV
Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath 'frontend/dist/index.html')) { throw 'Run scripts/build.ps1 first.' }
    if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) { throw 'Run scripts/setup.ps1 first.' }
    $env:APP_ENV = 'local'
    & ./.venv/Scripts/python.exe -m backend
    if ($LASTEXITCODE -ne 0) { throw 'Local server stopped with an error.' }
} finally {
    $env:APP_ENV = $previousAppEnvironment
    Pop-Location
}
