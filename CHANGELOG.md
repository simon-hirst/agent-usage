# Changelog

## v3.0.0 — Selectable providers and compact tray popup (2026-10-26)

- First-run setup for selecting which providers to track.
- Added optional single merged tray icon with compact click-to-expand usage view.
- Full dashboard only opens when explicitly requested.
- Added Muse CLI, Kimi Code quota, DeepSeek API balance, OpenRouter credits and configurable localhost bridges for additional providers.
- Start/stop Codex and Claude backends only when selected; preserved existing managed-process lifecycle.
- Kept Windows, macOS and Linux support and original localhost API endpoints.


## v2.0.1 — Compact numeric tray icons (2026-10-26)

- Changed tray icons to show only the coloured percentage number on a transparent background.
- Removed in-icon service/window labels; the hover tooltip and menu remain explicit about Codex vs Claude and 5-hour vs weekly windows.
- Kept the managed backend lifecycle and all API behaviour unchanged.

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
