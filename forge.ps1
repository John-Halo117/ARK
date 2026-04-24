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
        $PythonBin = "py"
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        $PythonBin = "python"
    }
    else {
        Write-Error "Forge could not find a usable Python interpreter."
        exit 1
    }
}

& $PythonBin (Join-Path $RootDir "ark-core/scripts/ai/forge.py") @args
exit $LASTEXITCODE
