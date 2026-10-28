# Provider Usage Tray

A cross-platform system tray monitor for coding assistants and model providers. Track your remaining usage, see when limits reset, and keep everything in one place without opening a dozen dashboards.

**Windows · macOS · Linux** — x64 and ARM64

[**Download the latest release**](https://github.com/simon-hirst/agent-usage/releases/latest) · [Report an issue](https://github.com/simon-hirst/agent-usage/issues)

## Overview

Provider Usage Tray runs quietly in the background and checks selected providers approximately once a minute.

- **At a glance:** coloured tray numbers show remaining quota; hover to see reset times in your local timezone.
- **One icon or many:** use individual indicators, or click a single merged icon for a compact usage view.
- **Your providers:** choose what to track on first launch and change it later in Settings.
- **No extra windows:** the full dashboard opens only when you select **Open dashboard**.
- **Automatic startup:** optionally launch on sign-in. App-managed Codex and Claude backends start and stop with the tray.

A provider may report a five-hour limit, a weekly/monthly allowance, or an API credit balance. These are displayed as separate measurements; unavailable values are never treated as zero.

If Claude usage temporarily fails to refresh, the tray keeps its last successful 5-hour and weekly percentages, dimmed and clearly marked **cached / not live** in the hover text and popup. Those readings persist across app restarts until a fresh reading is available.

## Architecture

The application is split into a small desktop client, provider readers, and two managed local APIs:

| Component | Source | Description |
| --- | --- | --- |
| Tray and dashboard | [`desktop/`](desktop/) | PySide6 interface, provider selection, compact popup, and local-time reset tooltips. |
| Codex usage API | [`work-codex-usage-api/`](work-codex-usage-api/) | Reads subscription limits from the authenticated Codex CLI. Serves `127.0.0.1:3789/get`. |
| Claude usage API | [`claude-usage-api/`](claude-usage-api/) | Reads Claude Code subscription usage. Serves `127.0.0.1:3790/get`. |
| Other provider readers | [`desktop/extra_readers.py`](desktop/extra_readers.py) | Reads available quota or billing data from authenticated CLIs, editors, browsers, and provider APIs. |
| Process management | [`desktop/processes.py`](desktop/processes.py) | Starts selected local backends silently and stops only processes the tray started. |
| Releases | [`.github/workflows/`](.github/workflows/) | Tests and packages native builds for all six OS/architecture targets. |

The two `/get` endpoints remain available to other local applications while their backends are running.

## Download and run

Download the build for your system from [GitHub Releases](https://github.com/simon-hirst/agent-usage/releases/latest):

| Platform | Package | Run |
| --- | --- | --- |
| Windows (x64 / ARM64) | `windows-*.zip` | Extract and launch `ProviderUsageTray.exe`. |
| macOS (Intel / Apple Silicon) | `macos-*.app.zip` | Unzip and open `ProviderUsageTray.app`. |
| Linux (x64 / ARM64) | `linux-*.tar.gz` | Extract and run `./ProviderUsageTray/ProviderUsageTray`. |

The desktop application comes prebuilt; **no desktop Python installation or compilation is required**. The macOS builds are currently unsigned, so you may need to approve them in macOS Privacy & Security. Linux requires a desktop environment with system tray support.

On first launch, select your providers and choose whether to combine them into one icon.

### Provider authentication

The app reuses existing logins where supported; it does not require a separately hosted bridge.

| Providers | What to have ready |
| --- | --- |
| **Codex, Claude** | Signed-in CLIs. On Windows, these run in WSL with Python 3 installed; on macOS/Linux, use native CLI logins. |
| **Muse, Gemini, GitHub Copilot, Grok** | Their respective signed-in CLIs (Copilot uses `gh auth login`). |
| **Cursor, Windsurf** | Signed-in desktop editors; some readings come from local cached data. |
| **Qwen Cloud, Perplexity** | Supported signed-in browser sessions. Qwen targets its individual Token Plan; Perplexity reports credits, not search limits. |
| **Kimi Code** | Its local usage server and `KIMI_SERVER_TOKEN`. |
| **DeepSeek, OpenRouter** | `DEEPSEEK_API_KEY` or an `OPENROUTER_API_KEY` management key, respectively. |

Some providers use undocumented interfaces and may stop reporting usage when those interfaces change. The app shows unavailable readings rather than guessing. Credentials are not written to tray settings. Keep API keys out of Git.

## Development

Run from the repository root with **Python 3.10+**:

```powershell
# Windows
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-windows.ps1
```

```bash
# macOS
./start-macos.sh

# Linux
./start-linux.sh
```

The source launchers set up the desktop dependency on first run. Windows Codex/Claude backends require an authenticated WSL distribution (Debian by default; configurable in Settings).

Run the tests:

```bash
python3 -m unittest discover -s desktop/tests -v
python3 -m unittest discover -s work-codex-usage-api/tests -v
python3 -m unittest discover -s claude-usage-api/tests -v
```

Version tags (`v*`) trigger [automated releases](.github/workflows/release.yml) for Windows, macOS, and Linux on x64 and ARM64, with SHA-256 checksums.

## Contributing

Issues and pull requests are welcome, particularly for provider compatibility, platform-specific bugs, and more reliable usage readers. Include your OS, provider, and relevant error output; **remove tokens, cookies, and other credentials** before sharing logs.

MIT licensed. This is an independent project and is not affiliated with the providers it monitors.
