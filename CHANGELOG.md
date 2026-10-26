# Changelog

## v3.3.0 — Direct provider readers (2026-10-26)

- Added built-in Grok, Cursor, Windsurf, Qwen Cloud and Perplexity account readers; no external bridge processes.
- Added browser session access for opt-in providers and local editor state fallbacks.
- Keep credit balances and unknown quota windows distinct from 5-hour/weekly limits.

## v3.2.0 — Direct provider readers

- Add built-in Gemini Code Assist quota reader from an existing CLI OAuth session.
- Add built-in GitHub Copilot monthly quota reader from existing GitHub CLI authentication.
- Remove bridge-setup fields for Grok, Gemini, Copilot, Cursor, Windsurf, Qwen and Perplexity.
- Add one-click account usage links for providers without verified subscription quota endpoints.
- Report model-specific and monthly windows honestly; do not invent five-hour/week percentages.
- Keep all original Codex/Claude/Kimi/Muse and API-balance integrations intact.

## v3.1.2 — Local reset times on tray hover

- Show local 5-hour and weekly reset dates/times when hovering over individual tray icons.
- Add a compact per-provider reset summary to the merged icon hover tooltip.
- Show local reset times in the quick view for every selected provider, including when the OS tooltip is too short.
- Treat missing or stale reset timestamps as unavailable rather than estimating them.

## v3.1.1 — Windows ARM64 release CI fix

- Corrected Claude usage-cache freshness after a failed poll when timestamps are equal.
- Added a deterministic regression test for coarse-resolution clocks.

## v3.1.0 — Native downloadable releases

- Added automated six-platform GitHub Releases for Windows, macOS and Linux on x64 and ARM64.
- Added frozen application backend dispatch and startup registration for the standalone binaries.
- Bundled the Codex and Claude Python services and WSL supervisor with the app.
- Added compiled-app smoke checks and a SHA-256 checksum manifest.

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
