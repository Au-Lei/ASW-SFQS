#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) { throw 'Run scripts/setup.ps1 first.' }
    & ./.venv/Scripts/python.exe scripts/dev.py
    if ($LASTEXITCODE -ne 0) { throw 'Development services stopped with an error. See data/logs/.' }
} finally { Pop-Location }
