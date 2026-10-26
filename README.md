# Codex + Claude Usage Tray

**v2.0.1 — Windows / macOS / Linux**

A small cross-platform system-tray app showing the **percentage of subscription quota remaining** for **Codex / ChatGPT Work** and **Claude / Claude Code**. The tray starts and owns the two local usage API services **in the background**, so no backend terminal window is necessary. On **Exit — stop managed APIs**, both services started by this app are shut down.

The APIs remain independently useful for integrations:

| Provider | Five-hour and weekly JSON | Source |
| --- | --- | --- |
| Codex / ChatGPT Work | `http://127.0.0.1:3789/get` | `codex app-server` rate-limit RPC |
| Claude / Claude Code | `http://127.0.0.1:3790/get` | Claude Code OAuth usage endpoint (unofficial) |

**Green numbers** = Codex; **orange numbers** = Claude. Tray icons now show **just the remaining percentage number** on a transparent background, matching the compact style of a plain numeric toolbar indicator. Hover or right-click any icon to see exactly which service/window it represents, then open the dashboard, toggle weekly icons, change startup behaviour or exit. Double-click/left-click an icon to open the dashboard (desktop behaviour varies).

## Install

Install **Python 3.10 or newer** on the host OS, and install/log into **Codex CLI** and **Claude Code** on the OS where the backend runs. The launcher automatically installs `PySide6` into a project-local Python virtual environment on its first run; an internet connection is required for that first installation. No admin permissions or hosted API keys are required.

### Windows 10/11 (WSL)

Prerequisites: Python on Windows, WSL distribution named **Debian** (or change it in tray Settings after first launch), and both Codex CLI and Claude Code signed in **inside that WSL distribution**.

Open PowerShell in the **repository root** and run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-windows.ps1
```

The PowerShell launcher exits once the tray starts; it does **not** leave two API terminals open. The tray runs the Python usage servers through hidden WSL processes using the signed-in Debian environment. The launcher and managed processes work around oversized Windows environment blocks.

**Upgrading from the old Windows/C# release:** Exit the old tray app and **disable its old Start with Windows toggle** before starting the new one. Stop the two old PowerShell API windows once. When the new tray owns the API servers, closing it stops them. If existing servers are already listening on those ports, the new tray **uses them but does not kill them** (see below).

### macOS

Prerequisites: Python 3.10+ and both CLIs signed in natively on the Mac. Run from Terminal in the repository root:

```bash
./start-macos.sh
```

The launcher installs Qt into `.venv` if needed, starts the tray **in the background**, and returns to the shell. The Claude service reads the regular Claude Code credentials file when available, or the **macOS Keychain** (`Claude Code-credentials`) when Claude Code has stored its OAuth login there. macOS may prompt to approve Keychain access; no login material is sent to the tray or saved by this project. If your login is not OAuth/subscription-based, Claude's usage endpoint may be unavailable.

### Linux

Prerequisites: Python 3.10+, `python3-venv`, a compatible tray/status-notifier desktop environment, and the two CLIs signed in natively. Run from a terminal in the repository root:

```bash
./start-linux.sh
```

The launcher starts the tray **in the background**. Under GNOME Shell / Wayland you may need an AppIndicator/StatusNotifier extension for tray icons. If no compatible tray is available, the app opens its dashboard window instead; closing it exits and stops its managed backends.

## Starting automatically

Right-click a tray icon → **Start with my computer**, or use the checkbox in **Settings**. This enables per-user login startup on the current OS:

- **Windows:** Current-user Registry `Run` entry launches the PowerShell bootstrap hidden.
- **macOS:** `~/Library/LaunchAgents/local.codex-claude-usage.tray.plist`.
- **Linux:** `~/.config/autostart/codex-claude-usage.desktop` (or your `XDG_CONFIG_HOME`).

Uncheck to remove the startup entry. No elevation or system service installation is required. Keep the checked-out repository in a permanent location after enabling startup (otherwise toggle off and on to update the path).

## Backend lifecycle and safety

- **The tray owns the services it launches.** It opens no backend terminals, holds a private child process pipe, and sends a stop command / closes the pipe when exiting. The supervisor also reacts to an unexpected tray-process exit; subprocess termination is best-effort on system crashes or forced power-off.
- **Already-running, separately launched servers are left alone.** If you manually started either API, that process is not owned by the tray and will **not** be stopped by exiting it. Stop your old API terminal(s) before using managed mode if you want both ports to go away on Exit.
- The tray starts only missing services. Once the ports become free, the tray can relaunch its own services on the next poll.
- APIs bind **only to `127.0.0.1`**, not the LAN. Do not expose these ports to the internet. WSL localhost forwarding is handled by WSL if enabled.
- Backend snapshots refresh every ~60 seconds when available. The tray polls both every 60 seconds (more frequently while they start). A stale/offline backend displays `--` rather than a fake or expired percentage.
- The Codex service delegates authentication to the existing authenticated Codex CLI via its app-server protocol. The Claude service reads the Claude Code login in the local service environment and only sends its OAuth access token to Anthropic; nothing credential-like is returned from `/get`.
- Anthropic's usage endpoint is **undocumented**, may stop working without notice, and may impose rate limits. The service backs off after HTTP 429; a guaranteed 60-second upstream refresh is not possible.
- These tools are **not affiliated with OpenAI or Anthropic**. Different accounts/plans may lack one of the two windows. Missing windows appear as `--`.

## Calling the APIs

```javascript
const [codex, claude] = await Promise.all([
  fetch('http://127.0.0.1:3789/get').then(r => r.json()),
  fetch('http://127.0.0.1:3790/get').then(r => r.json())
]);

console.log(codex.ok && !codex.stale ? codex.five_hour?.remaining_percent : null);
console.log(claude.ok && !claude.stale ? claude.weekly?.remaining_percent : null);
```

Sample window:

```json
{
  "used_percent": 25,
  "remaining_percent": 75,
  "duration_minutes": 300,
  "resets_at_unix": 1790000000,
  "resets_at": "2026-09-21T18:13:20Z",
  "resets_in_seconds": 7200
}
```

**This is illustrative JSON, not a real account reading.** The full `/get` payload includes `ok`, `stale`, cache metadata and other optional windows. See the two API folders' READMEs for details.

## Project structure

```text
codex-claude-usage/
├── desktop/                 PySide6 tray, dashboard, process ownership, startup controls
│   ├── app.py               UI and asynchronous local HTTP polling
│   ├── managed_native.py    Linux/macOS Python subprocess supervisor
│   ├── managed-wsl.sh       Windows/WSL supervisor that obeys shutdown pipe
│   ├── processes.py         Backend lifecycle management and 64 KB env workaround
│   ├── autostart.py         Registry / LaunchAgent / XDG autostart
│   └── tests/              Tests (including process exit/crash simulation)
├── work-codex-usage-api/    Python Codex app-server bridge
├── claude-usage-api/        Python Anthropic OAuth usage bridge
├── start-windows.ps1        Background Windows bootstrap
├── start-macos.sh           Background macOS bootstrap
├── start-linux.sh           Background Linux bootstrap
├── requirements.txt         Qt dependency
└── .github/workflows/       Cross-platform CI
```

## Tests

```bash
python3 -m unittest discover -s desktop/tests -v
python3 -m unittest discover -s work-codex-usage-api/tests -v
python3 -m unittest discover -s claude-usage-api/tests -v
```

GitHub Actions runs API tests, desktop lifecycle tests and a Qt import/icon-rendering smoke test on Windows, Linux and macOS. Full interactive tray behaviour still needs to be exercised in a real graphical login session.

## Troubleshooting

- **Windows shows no icons:** check *Settings → Personalization → Taskbar → Other system tray icons*. For GUI startup exceptions, check `%LOCALAPPDATA%\CodexClaudeUsage\logs\tray-error.log`.
- **Windows first launch fails:** install Python 3.10+ on Windows and ensure WSL/Debian is working; use the PowerShell launcher to see package installation errors. In **Settings**, change the WSL distribution if it isn't `Debian`.
- **All values `--`:** make sure Codex and Claude Code are signed in inside the right environment. Look at local `http://127.0.0.1:3789/get` and `http://127.0.0.1:3790/get` to see the precise error. Server logs are under `~/.local/state/codex-claude-usage/` in WSL; on macOS under `~/Library/Logs/CodexClaudeUsage/` and on Linux under `~/.local/state/codex-claude-usage/`.
- **macOS Claude Keychain permission:** approve the system request if you trust this local tool; otherwise leave Claude disabled/unavailable. The API never outputs your access token.
- **Linux missing tray icons:** use a compatible system tray or enable a suitable GNOME AppIndicator extension; the dashboard still works without tray icons.
- **Existing APIs keep running when you exit:** they were already running outside this tray (perhaps from the original release). Stop those terminal sessions. The app never kills unrelated services just to free ports.

MIT licence in [LICENSE](LICENSE). PRs and contributions welcome.

## Optional: reconstruct a Git history from the release snapshot

This ZIP contains `bootstrap_git_history.py`, which can initialize a fresh Git
repository and group the files into approximately 14 coherent commits. **These
commits are synthetic checkpoints** with randomly generated dates and times;
they do not establish when the code was actually written.

Run from the project root, **before** adding any commits:

```bash
python bootstrap_git_history.py --preview --seed 42
python bootstrap_git_history.py --seed 42
```

On Windows you can use `py -3` instead of `python`. The `--preview` flag does
not modify the repository. Remove `--seed 42` if you prefer fresh random dates.
The script uses the June 4, 2026–current-date interval, sets the local Git
identity to `simon <simonhirst@pm.me>`, and refuses to run if history already
exists. Verify that the email address is verified by your GitHub account if
you want commits to be attributed to you on GitHub.
