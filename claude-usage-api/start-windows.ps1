# Windows 11 + Debian WSL, using the same proven launcher method as Codex v2.
$ErrorActionPreference = 'Stop'
$distribution = 'Debian'
Push-Location -LiteralPath $PSScriptRoot
try {
    Write-Host "Starting Claude Usage API in $distribution..."
    Write-Host 'Endpoint: http://localhost:3790/get'
    # Avoid wslpath, command substitution and bash -c quoting altogether.
    & wsl.exe -d $distribution -- bash -i ./start.sh
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
if ($exitCode -ne 0) {
    Write-Error "Debian WSL exited with code $exitCode. Try: wsl -d Debian -- bash -i ./start.sh"
    exit $exitCode
}
