$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$workflowPath = Join-Path $repoRoot 'ingest\n8n\ark-mvp-ingest.json'
$envPath = Join-Path $PSScriptRoot '.env'
$credentialPath = Join-Path $env:TEMP 'ark-postgres-credential.json'

$envMap = @{}
Get-Content $envPath | ForEach-Object {
  if ($_ -match '^\s*#' -or $_ -notmatch '=') {
    return
  }
  $key, $value = $_ -split '=', 2
  $envMap[$key.Trim()] = $value.Trim()
}

$credentialPayload = @(
  @{
    id = 'ark-postgres-credential'
    name = 'ARK Postgres'
    type = 'postgres'
    data = @{
      host = 'postgres'
      port = 5432
      database = $envMap['ARK_POSTGRES_DB']
      user = $envMap['ARK_POSTGRES_USER']
      password = $envMap['ARK_POSTGRES_PASSWORD']
      ssl = 'disable'
    }
  }
)
$credentialPayload | ConvertTo-Json -Depth 8 | Set-Content -Path $credentialPath -Encoding UTF8
$projectId = "$(& docker compose -f (Join-Path $PSScriptRoot 'docker-compose.yml') exec -T postgres psql -U ark -d ark_ssot -Atc 'select id from project limit 1;')".Trim()

if ([string]::IsNullOrWhiteSpace($projectId)) {
  throw 'Unable to resolve n8n project id.'
}

$n8nContainer = "$(& docker compose -f (Join-Path $PSScriptRoot 'docker-compose.yml') ps -q n8n)".Trim()
if ([string]::IsNullOrWhiteSpace($n8nContainer)) {
  throw 'n8n container is not running.'
}

docker cp $credentialPath "${n8nContainer}:/tmp/ark-postgres-credential.json" | Out-Null
docker cp $workflowPath "${n8nContainer}:/tmp/ark-mvp-ingest.json" | Out-Null

$existingCredential = "$(& docker compose -f (Join-Path $PSScriptRoot 'docker-compose.yml') exec -T postgres psql -U ark -d ark_ssot -Atc "select id from credentials_entity where id = 'ark-postgres-credential';")".Trim()
if (-not $existingCredential) {
  docker compose -f (Join-Path $PSScriptRoot 'docker-compose.yml') exec -T n8n n8n import:credentials --input=/tmp/ark-postgres-credential.json --projectId=$projectId | Out-Null
}

$existingWorkflow = "$(& docker compose -f (Join-Path $PSScriptRoot 'docker-compose.yml') exec -T postgres psql -U ark -d ark_ssot -Atc "select id from workflow_entity where id = 'ark-mvp-ingest';")".Trim()
if (-not $existingWorkflow) {
  docker compose -f (Join-Path $PSScriptRoot 'docker-compose.yml') exec -T n8n n8n import:workflow --input=/tmp/ark-mvp-ingest.json --projectId=$projectId | Out-Null
}

docker compose -f (Join-Path $PSScriptRoot 'docker-compose.yml') exec -T n8n n8n update:workflow --id=ark-mvp-ingest --active=true | Out-Null
Write-Host 'n8n workflow imported and activated.'
