# Provider Usage Tray

A small **Windows, macOS and Linux** system-tray app for tracking usage limits from your coding agents and model providers. It updates approximately once a minute, shows only the providers you select and can combine them into **one tray icon**.

**Click the tray icon** for a small usage popup. Use **Open dashboard** only when you want the full window. Right-click for the menu. Your selected providers can be changed at any time under Settings.

## Download and run

Open **GitHub → Releases** and download the package for your operating system and CPU:

| Operating system | Downloads |
| --- | --- |
| Windows 10/11 | `windows-x64.zip` or `windows-arm64.zip` |
| macOS (Intel / Apple Silicon) | `macos-x64.app.zip` or `macos-arm64.app.zip` |
| Linux | `linux-x64.tar.gz` or `linux-arm64.tar.gz` |

**Windows:** extract the entire ZIP, then run `ProviderUsageTray.exe`. **macOS:** unzip and open `ProviderUsageTray.app` (unsigned builds may require approving it in Privacy & Security). **Linux:** extract the archive and run `./ProviderUsageTray/ProviderUsageTray` from a desktop session with a tray.

You **do not need to install Python or build the application**. You still need the relevant provider CLIs/accounts: on Windows, Codex and Claude use Python 3 and authenticated CLIs **inside your configured WSL distro**; on macOS/Linux, they use the native CLI logins. Optional providers have their own setup requirements below.

### Running from source (developers)

Requires Python 3.10+. The launcher installs the Qt desktop dependency on first run.

| OS | Run from the repository root |
| --- | --- |
| Windows 10/11 | `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-windows.ps1` |
| macOS | `./start-macos.sh` |
| Linux | `./start-linux.sh` |

On first launch, choose the providers you use and whether to **Combine into one tray icon**. Toggle **Start automatically when signing in** if wanted.

For Codex/Claude on Windows, install and sign into both CLIs in **Debian WSL** (or change the distribution in Settings). On macOS/Linux, sign into them natively. Their localhost servers are launched silently and stopped automatically when you exit the tray. Existing standalone servers are not stopped.

## Provider connections

| Provider | What the app reads | Required setup |
| --- | --- | --- |
| **Codex / ChatGPT Work** | 5-hour and weekly allowances | Signed-in Codex CLI; managed local API on port `3789` |
| **Claude / Claude Code** | 5-hour and weekly allowances | Signed-in Claude Code; managed local API on port `3790` |
| **Muse Code** | 5-hour and weekly allowances where reported | Signed-in Muse CLI, running `muse usage` periodically |
| **Kimi Code** | 5-hour, legacy weekly, monthly limits where present | Running Kimi local web API; `KIMI_SERVER_TOKEN` environment variable |
| **DeepSeek API** | Current API balance | `DEEPSEEK_API_KEY` environment variable |
| **OpenRouter API** | Available API credits and percentage of purchased credits | `OPENROUTER_API_KEY` **management** key |
| **Grok, Gemini, Copilot, Cursor, Windsurf, Qwen, Perplexity** | Usage windows from a local bridge | Provide a localhost JSON endpoint under **Settings → Advanced** |

**Important:** A *subscription quota*, a *rate limit* and *prepaid API credits* are different measurements. The app labels them separately and doesn't invent percentages. DeepSeek balance is shown in the popup/dashboard, not as a fake percentage. Kimi's newer plans may not have a weekly quota. Muse's CLI output is parsed conservatively and may need an updated adapter if Meta changes the format.

For providers that require an API key, set the relevant environment variable **before starting the app** (then restart it). On Windows, for example, you can use `setx DEEPSEEK_API_KEY "your-key"`, then open a fresh PowerShell window. Never commit keys to Git.

### Kimi local server

Kimi's local web server provides `GET /api/v1/oauth/usage` with a bearer token. By default the app tries `http://127.0.0.1:58627/api/v1/oauth/usage`. Start the Kimi web server, obtain its access token, and set `KIMI_SERVER_TOKEN` in the desktop app's environment. If its port differs, change the endpoint under Advanced. The app does not start Kimi or read its secrets automatically.

### Custom provider bridge

For providers without a supported machine-readable subscription endpoint, run your own localhost service and enter its URL under Settings → Advanced. It should return:

```json
{
  "ok": true,
  "stale": false,
  "five_hour": {"remaining_percent": 65, "resets_at": "2026-10-27T12:00:00Z"},
  "weekly": {"remaining_percent": 40, "resets_at": "2026-11-02T12:00:00Z"}
}
```

Fields can be `null` or omitted if unavailable. The app only accepts **HTTP localhost URLs** for bridges, never arbitrary remote endpoints; don't expose private usage servers publicly. The bridge is optional and **is not bundled** for those services.

## Usage and controls

- **Individual icons:** coloured percentages remaining (or `--` if unavailable). Optionally show weekly icons too.
- **Merged mode:** one coloured icon. Click it for a compact, auto-closing popup listing all selected providers, limits, resets and balances.
- **Dashboard:** opened only with **Open dashboard**, not by clicking the tray icon.
- **Settings:** choose providers, enable merged mode, update local bridge URLs, and configure login startup.
- Both original `/get` APIs remain available at `http://127.0.0.1:3789/get` and `http://127.0.0.1:3790/get` while running.

If a value is `--`, hover for details or open the quick view. The Claude usage endpoint is undocumented and can be rate-limited. On GNOME/Wayland, install an AppIndicator extension if your system doesn't show tray icons.

## Automated GitHub Releases

On every pushed version tag (for example `v3.1.1`), `.github/workflows/release.yml` builds six native packages, smoke-tests the bundled UI and backend entrypoints, checks that all six artifacts exist, and publishes them together with SHA-256 checksums to GitHub Releases. You can also run that workflow manually for an existing tag. Release builds require no local compilation; the binaries are currently unsigned and not notarised.

To publish from a clean committed repository:

```bash
git tag v3.1.1
git push origin v3.1.1
```

## Tests

```bash
python3 -m unittest discover -s desktop/tests -v
python3 -m unittest discover -s work-codex-usage-api/tests -v
python3 -m unittest discover -s claude-usage-api/tests -v
```

MIT licensed. Unaffiliated with the listed providers.
