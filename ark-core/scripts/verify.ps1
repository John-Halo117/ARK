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
.\.venv\Scripts\python scripts\ci\enforce_tiers.py --rules config\tiering_rules.json --validate-rules-only
if (Get-Command bash -ErrorAction SilentlyContinue) {
    bash scripts/ci/redteam.sh
}
if (Get-Command go -ErrorAction SilentlyContinue) {
    go test ./...
}
if (Get-Command docker -ErrorAction SilentlyContinue) {
    docker compose -f compose.yaml config | Out-Null
    docker compose -f docker-compose.yml config | Out-Null
    Write-Host "docker compose config: OK"
}
