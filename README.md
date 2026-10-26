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
| **Gemini Code Assist** | Model-specific remaining quota and reset dates | Signed-in Gemini CLI using OAuth on the same OS/WSL environment; Google CLI OAuth availability depends on account type |
| **GitHub Copilot** | Monthly quota percentage and reset date when reported | Signed-in `gh` CLI (`gh auth login`) on same OS/WSL; uses an undocumented GitHub endpoint |
| **Grok** | CLI billing quota (weekly/monthly/credits when reported) | `grok login` in CLI environment |
| **Cursor** | Editor plan usage; shared Grok weekly pool on supported accounts | Signed-in Cursor editor or browser |
| **Windsurf** | Editor-cached daily/weekly quota or named counters | Signed-in Windsurf editor |
| **Qwen Cloud** | Individual Token Plan 5h/weekly quotas (best effort) | Signed-in Qwen Cloud browser session |
| **Perplexity** | Remaining account credits (not search allowance) | Signed-in Perplexity browser session |

**Important:** A *subscription quota*, a *rate limit* and *prepaid API credits* are different measurements. The app labels them separately and doesn't invent percentages. DeepSeek balance is shown in the popup/dashboard, not as a fake percentage. Kimi's newer plans may not have a weekly quota. Muse's CLI output is parsed conservatively and may need an updated adapter if Meta changes the format.

For providers that require an API key, set the relevant environment variable **before starting the app** (then restart it). On Windows, for example, you can use `setx DEEPSEEK_API_KEY "your-key"`, then open a fresh PowerShell window. Never commit keys to Git.

### Kimi local server

Kimi's local web server provides `GET /api/v1/oauth/usage` with a bearer token. By default the app tries `http://127.0.0.1:58627/api/v1/oauth/usage`. Start the Kimi web server, obtain its access token, and set `KIMI_SERVER_TOKEN` in the desktop app's environment. If its port differs, change the endpoint under Advanced. The app does not start Kimi or read its secrets automatically.

### Built-in account readers

The tray includes its own Gemini and Copilot account readers. It executes the readers as short-lived subprocesses and **never runs a third-party bridge service**. On Windows, sign in to the relevant CLI **inside the configured WSL distribution**; on macOS/Linux, sign in natively. Gemini quota reads require a current CLI OAuth access token; if it has expired, open the CLI to renew it. These endpoints may change and are not guaranteed for every account.

The five additional providers now have opt-in readers built into the desktop app. They need no localhost bridge. Their provider-specific setup and caveats are listed below. Authentication is inherited from an existing CLI, editor or browser session rather than being stored in the tray settings.


## Usage and controls

- **Individual icons:** coloured percentages remaining (or `--` if unavailable). Hover over an icon to see its reported quota windows and reset dates in your computer's local timezone. Gemini shows per-model quotas; Copilot shows monthly quotas. Optionally show weekly icons too.
- **Merged mode:** one coloured icon. Hover for a compact summary of local reset times. Operating systems limit tray tooltip length, so if you're tracking many providers, click for the full quick view (with reset dates for all providers).
- **Dashboard:** opened only with **Open dashboard**, not by clicking the tray icon.
- **Settings:** choose providers, enable merged mode, configure optional Muse/Kimi endpoints, and configure login startup.
- Both original `/get` APIs remain available at `http://127.0.0.1:3789/get` and `http://127.0.0.1:3790/get` while running.

If a value is `--`, hover for details or open the quick view. The Claude usage endpoint is undocumented and can be rate-limited. On GNOME/Wayland, install an AppIndicator extension if your system doesn't show tray icons.

## Automated GitHub Releases

On every pushed version tag (for example `v3.3.2`), `.github/workflows/release.yml` builds six native packages, smoke-tests the bundled UI and backend entrypoints, checks that all six artifacts exist, and publishes them together with SHA-256 checksums to GitHub Releases. You can also run that workflow manually for an existing tag. Release builds require no local compilation; the binaries are currently unsigned and not notarised.

To publish from a clean committed repository:

```bash
git tag v3.3.2
git push origin v3.3.2
```

## Tests

```bash
python3 -m unittest discover -s desktop/tests -v
python3 -m unittest discover -s work-codex-usage-api/tests -v
python3 -m unittest discover -s claude-usage-api/tests -v
```

MIT licensed. Unaffiliated with the listed providers.


## Additional direct account readers (v3.3.0)

Enable providers in **Choose providers / Settings**. No separate local bridge server is required. Readers reuse the selected provider’s existing local login when available and make read-only requests to that provider. Selecting a provider authorises the app to read **only that provider’s** existing local credentials/browser session; no cookies, access tokens or API keys are written to settings or returned in the UI.

- **Grok:** sign into the Grok Build CLI (`grok`) on the OS where the reader runs (Debian WSL on Windows). Uses CLI billing endpoint, not xAI developer API keys.
- **Cursor:** sign into the Cursor editor on your desktop. Reads its local state database read-only, then queries account usage; optional `CURSOR_COOKIE` environment variable if local login is not usable. New X subscriptions can have a shared Grok/Cursor weekly allowance; legacy plans can have monthly allowances.
- **Windsurf:** sign into the Windsurf editor. Reads its cached plan/quota, so values may lag while the editor is closed. Falls back to named message/flow-action usage counters, never invents reset times.
- **Qwen:** supported for **Qwen Cloud international individual Token Plan**, not generic Qwen chat or all ModelStudio accounts. Sign into `home.qwencloud.com` in Chrome, Edge or Firefox; optional `QWEN_CLOUD_COOKIE` and `QWEN_CLOUD_SEC_TOKEN` environment variables. The unofficial account gateway may reject sessions.
- **Perplexity:** sign into `perplexity.ai` in Chrome, Edge or Firefox. Reads recurring/purchased credits, **not** a five-hour/weekly Pro search allowance. Optional `PERPLEXITY_COOKIE` environment variable.

Browser-cookie retrieval uses `browser-cookie3` bundled with the desktop application. Protected profiles or browser-specific encryption may block automatic access; the reader reports that clearly. All these endpoints are undocumented, subject to change, and cannot be verified against an actual subscribed account by CI. The app displays unavailable instead of fabricating a quota.
