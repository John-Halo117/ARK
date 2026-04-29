$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ForgeCmd = Join-Path $RootDir "forge.cmd"

if (-not (Test-Path $ForgeCmd)) {
    Write-Error "Forge launcher is missing: $ForgeCmd"
    exit 1
}

$Command = 'cd /d "' + $RootDir + '" && forge.cmd'
foreach ($Arg in $args) {
    $Escaped = [string]$Arg -replace '"', '\"'
    $Command += ' "' + $Escaped + '"'
}

Start-Process -FilePath "cmd.exe" -ArgumentList "/d", "/c", $Command -WindowStyle Minimized
exit 0
