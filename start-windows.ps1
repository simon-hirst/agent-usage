# Windows tray launcher, Windows 10/11 with Python 3.10+ installed.
# Starts only the GUI with pythonw.exe; GUl owns both silent WSL backends.
# This bootstrap restores any oversized developer environment when it exits.
param([switch]$NoConsole)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$original = @{}
$keep = @('SystemRoot','windir','SystemDrive','ComSpec','Path','PATHEXT','TEMP','TMP',
    'USERPROFILE','APPDATA','LOCALAPPDATA','HOMEDRIVE','HOMEPATH','OS',
    'PROCESSOR_ARCHITECTURE','NUMBER_OF_PROCESSORS','ProgramFiles',
    'ProgramFiles(x86)','ProgramW6432','CommonProgramFiles','CommonProgramFiles(x86)')
try {
    foreach ($entry in (Get-ChildItem Env:)) {
        $original[$entry.Name] = $entry.Value
        if ($keep -notcontains $entry.Name -or $entry.Value.Length -gt 9000) {
            [Environment]::SetEnvironmentVariable($entry.Name, $null, 'Process')
        }
    }
    if (-not $env:SystemRoot) { $env:SystemRoot = 'C:\Windows' }
    if (-not $env:Path) {
        $paths = New-Object System.Collections.Generic.List[string]
        $paths.Add("$env:SystemRoot\System32")
        $paths.Add($env:SystemRoot)
        foreach ($candidate in ($original['Path'] -split ';')) {
            if ($candidate -and $candidate.Length -lt 400 -and
                ((Test-Path -LiteralPath (Join-Path $candidate 'py.exe')) -or
                 (Test-Path -LiteralPath (Join-Path $candidate 'python.exe')))) {
                if (-not $paths.Contains($candidate)) { $paths.Add($candidate) }
            }
        }
        $env:Path = ($paths -join ';')
    }
    $venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    $venvPythonW = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
    if (-not (Test-Path -LiteralPath $venvPython)) {
        if (Get-Command py.exe -ErrorAction SilentlyContinue) {
            & py.exe -3 -m venv (Join-Path $PSScriptRoot '.venv')
        } elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
            & python.exe -m venv (Join-Path $PSScriptRoot '.venv')
        } else {
            throw 'Python 3.10+ not found. Install it from python.org (include the py launcher).'
        }
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python virtual environment.' }
    }
    $marker = Join-Path $PSScriptRoot '.venv\requirements-installed'
    if (-not (Test-Path -LiteralPath $marker)) {
        Write-Host 'Installing Qt tray dependency (first run only)...'
        & $venvPython -m pip install --disable-pip-version-check -r (Join-Path $PSScriptRoot 'requirements.txt')
        if ($LASTEXITCODE -ne 0) { throw 'Failed to install PySide6; inspect pip error above.' }
        Set-Content -Path $marker -Value 'installed' -Encoding ASCII
    }
    $entry = Join-Path $PSScriptRoot 'desktop\run_app.py'
    Start-Process -FilePath $venvPythonW -WorkingDirectory $PSScriptRoot -ArgumentList ('"' + $entry + '"')
    Write-Host 'Started Usage Tray; backend API servers run silently and exit with the tray.'
} catch {
    if (-not $NoConsole) { Write-Error $_ }
    else { $_ | Out-File -FilePath (Join-Path $env:TEMP 'codex-claude-usage-startup-error.log') }
    if (-not $NoConsole) { exit 1 }
} finally {
    foreach ($entry in (Get-ChildItem Env:)) {
        if (-not $original.ContainsKey($entry.Name)) {
            [Environment]::SetEnvironmentVariable($entry.Name, $null, 'Process')
        }
    }
    foreach ($name in $original.Keys) { [Environment]::SetEnvironmentVariable($name, $original[$name], 'Process') }
}
