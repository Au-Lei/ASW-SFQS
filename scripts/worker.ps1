#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
Push-Location $taskRoot
try {
    & .venv/Scripts/python.exe -m backend.workers run @args
    if ($LASTEXITCODE -ne 0) { throw 'Worker exited; check schema readiness and worker ownership.' }
} finally { Pop-Location }
