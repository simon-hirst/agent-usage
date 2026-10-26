# Codex + Claude Usage

A small system-tray monitor for your **Codex / ChatGPT Work** and **Claude / Claude Code** subscription limits. Shows the **percentage remaining** for the 5-hour and weekly windows on **Windows, macOS and Linux**.

- **Green numbers:** Codex. **Orange numbers:** Claude.
- Click an icon for a dashboard; right-click for settings, weekly icons and **Start with my computer**.
- Starts both local usage APIs silently and stops the ones it started when you exit.
- Refreshes approximately every 60 seconds; unavailable or stale values show `--`.

## Install

You need **Python 3.10+**, **Codex CLI** and **Claude Code**, signed in to your subscription accounts. The launcher installs the desktop dependency (`PySide6`) into a local virtual environment on first run.

### Windows 10 / 11

Install WSL with **Debian**, then sign in to Codex CLI and Claude Code **inside Debian**. Open PowerShell in the repository folder:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-windows.ps1
```

Windows runs the APIs inside WSL. You can change the WSL distribution in tray settings.

### macOS

Sign in to both CLIs on the Mac, then run:

```bash
./start-macos.sh
```

### Linux

Sign in to both CLIs on Linux, then run:

```bash
./start-linux.sh
```

On some Linux desktops, tray icons require an AppIndicator extension. If the tray is unavailable, the dashboard opens instead.

## Local APIs

Both APIs are available while their services are running:

| Service | Endpoint |
| --- | --- |
| Codex / ChatGPT Work | `http://127.0.0.1:3789/get` |
| Claude / Claude Code | `http://127.0.0.1:3790/get` |

Each endpoint returns JSON containing `five_hour` and `weekly` quota details, including `remaining_percent` and reset time where available. For example:

```javascript
const usage = await fetch('http://127.0.0.1:3789/get').then(r => r.json());
console.log(usage.five_hour?.remaining_percent);
```

## Notes

- Both services bind to **localhost only** and reuse your existing CLI logins. No credentials are included in this repository.
- **Claude usage relies on an unofficial, undocumented endpoint.** Anthropic may change or rate-limit it. The service automatically backs off after a rate-limit response.
- The tray stops only the backends **it started**. Servers launched separately remain running.
- If an icon shows `--`, inspect its `/get` endpoint for the error and check that the relevant CLI is signed in.
- To keep the icons visible on Windows, use **Settings → Personalization → Taskbar → Other system tray icons**.

## Development

Run tests from the repository root:

```bash
python3 -m unittest discover -s desktop/tests -v
python3 -m unittest discover -s work-codex-usage-api/tests -v
python3 -m unittest discover -s claude-usage-api/tests -v
```

MIT licensed. Not affiliated with OpenAI or Anthropic.
