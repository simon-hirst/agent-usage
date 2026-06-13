# Start the API using the existing Codex login in Debian WSL.
# IMPORTANT: Do not pass a multi-statement Bash command through `wsl.exe -c`.
# Windows/PowerShell/WSL can change the quoting; run a shell script instead.
$ErrorActionPreference = 'Stop'
$distribution = 'Debian'

Push-Location -LiteralPath $PSScriptRoot
try {
    Write-Host "Starting Work/Codex Usage API in $distribution..."
    Write-Host 'Endpoint: http://localhost:3789/get'

    # WSL inherits the Windows current working directory as its Linux cwd.
    # bash -i reads the same shell configuration/PATH used by your Codex CLI.
    # No shell code, Windows paths, quotes or semicolons cross the WSL boundary.
    & wsl.exe -d $distribution -- bash -i ./start.sh
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($exitCode -ne 0) {
    Write-Error "Debian WSL exited with code $exitCode. Try running: wsl -d Debian -- bash -i ./start.sh"
    exit $exitCode
}
