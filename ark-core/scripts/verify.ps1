# Run from repo root: .\scripts\verify.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

if (-not (Test-Path .venv\Scripts\python.exe)) {
    python -m venv .venv
}
.\.venv\Scripts\pip install -r requirements-dev.txt
.\.venv\Scripts\ruff check .
.\.venv\Scripts\ruff format --check .
.\.venv\Scripts\pytest --cov --cov-report=term-missing
if (Get-Command docker -ErrorAction SilentlyContinue) {
    docker compose -f compose.yaml config | Out-Null
    Write-Host "docker compose config: OK"
}
