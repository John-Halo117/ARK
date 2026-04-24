$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($args.Count -eq 0 -and (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    $WindowsRoot = $RootDir.TrimEnd("\")
    $WslRoot = (& wsl.exe wslpath -a "$WindowsRoot").Trim()
    if ($LASTEXITCODE -eq 0 -and $WslRoot) {
        Start-Process -WindowStyle Minimized "wsl.exe" -ArgumentList "bash", "-lc", "cd '$WslRoot' && ./forge --desktop --desktop-port 4765"
        Start-Sleep -Seconds 2
        Start-Process "http://127.0.0.1:4765/"
        exit 0
    }
}

$PythonBin = Join-Path $RootDir "ark-core/.venv/Scripts/python.exe"

if (-not (Test-Path $PythonBin)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $ResolvedPython = (& py -3 -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1).Trim()
        if ($ResolvedPython -and (Test-Path $ResolvedPython)) {
            $PythonBin = $ResolvedPython
        }
    }
    if (-not (Test-Path $PythonBin) -and (Get-Command python -ErrorAction SilentlyContinue)) {
        $PythonBin = (Get-Command python -ErrorAction SilentlyContinue).Source
    }
    if (-not (Test-Path $PythonBin) -and (Get-Command python3 -ErrorAction SilentlyContinue)) {
        $PythonBin = (Get-Command python3 -ErrorAction SilentlyContinue).Source
    }
    if (-not (Test-Path $PythonBin)) {
        Write-Error "Forge could not find a usable Python interpreter."
        exit 1
    }
}

& $PythonBin (Join-Path $RootDir "ark-core/scripts/ai/forge.py") @args
exit $LASTEXITCODE
