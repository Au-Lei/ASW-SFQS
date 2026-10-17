#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
try {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Install uv first: python -m pip install uv==0.11.23' }
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'Node.js 22.12+ is required.' }
    $nodeVersion = (& node --version).Trim().TrimStart('v')
    if ([version]$nodeVersion -lt [version]'22.12.0') { throw 'Node.js 22.12+ is required. Node.js 24 LTS is recommended.' }
    & uv sync --frozen
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    & npm.cmd ci --prefix frontend
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
    Write-Output 'Setup complete. Run: powershell -File scripts/dev.ps1'
} finally { Pop-Location }
