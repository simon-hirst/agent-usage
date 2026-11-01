# Stop Provider Usage Tray (source or packaged app) without killing unrelated Python/WSL tasks.
# Backend supervisors detect the tray's closed stdin and stop only their own APIs.
$ErrorActionPreference = 'Stop'
$sourceEntry = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'desktop\run_app.py'))
$targetNames = @('ProviderUsageTray.exe', 'python.exe', 'pythonw.exe')

try {
    $all = @(Get-CimInstance Win32_Process -Filter "Name = 'ProviderUsageTray.exe' OR Name = 'python.exe' OR Name = 'pythonw.exe'")
} catch {
    Write-Error "Cannot list running processes: $_"
    exit 1
}

$targets = @()
foreach ($process in $all) {
    if ($targetNames -notcontains $process.Name) { continue }
    $cmd = [string]$process.CommandLine
    if ($cmd -match '(?i)(?:^|\s)--(?:backend-server|backend-supervisor|direct-usage|verify-bundle)(?:\s|$)') { continue }
    if ($process.Name -ieq 'ProviderUsageTray.exe') {
        # A uniquely named bundled tray executable (not its background worker mode).
        $targets += $process
    } elseif ($cmd.IndexOf($sourceEntry, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
        # Only the source tray from THIS repository, not other Python apps.
        $targets += $process
    }
}

if ($targets.Count -eq 0) {
    Write-Host 'Provider Usage Tray is not running.'
    exit 0
}

$errors = 0
foreach ($process in $targets) {
    try {
        Write-Host "Stopping Provider Usage Tray (PID $($process.ProcessId))..."
        Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
    } catch {
        Write-Warning "Could not stop PID $($process.ProcessId): $_"
        $errors++
    }
}
if ($errors -gt 0) { exit 1 }
Write-Host 'Tray stopped. App-managed backends should exit when their supervisor pipes close.'
