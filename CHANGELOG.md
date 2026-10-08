# Changelog

## v2.0.0 — Cross-platform managed release (2026-10-26)

- Replaced Windows-only C# WinForms frontend with one PySide6 tray/dashboard for Windows, macOS and Linux.
- Added automatic, hidden launching of both usage backends with strict lifecycle ownership.
- Stop app-owned services on Exit; parent-process EOF also terminates managed services after a crash.
- Never stop external/manual services just because they use the same HTTP ports.
- Retained Windows WSL Debian login reuse and huge environment-block workarounds.
- Added native macOS/Linux backend support, including reading macOS Claude Code OAuth from Keychain when appropriate.
- Added Windows Registry, macOS LaunchAgent and Linux XDG autostart controls.
- Kept the JSON endpoints and both rate-limit normalisers backward-compatible.
- Added portable configuration, lifecycle tests and an OS matrix in GitHub Actions.

## v1.x

- Original Windows tray and separate local Codex / Claude APIs.
