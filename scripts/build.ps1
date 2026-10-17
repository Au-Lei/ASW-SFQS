#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
try {
    & uv run --frozen python contracts/generate.py --check
    if ($LASTEXITCODE -ne 0) { throw 'Contracts are out of date.' }
    & npm.cmd run build --prefix frontend
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    Write-Output 'Build complete. Run: powershell -File scripts/start-local.ps1'
} finally { Pop-Location }
