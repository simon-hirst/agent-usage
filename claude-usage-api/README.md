# Claude / Claude Code Usage API

A tiny **localhost-only**, dependency-free Python HTTP server that reads Claude Pro/Max usage (shared with Claude Code) from the signed-in Claude Code OAuth credentials in **Debian WSL** and exposes it at:

**http://localhost:3790/get**

- Five-hour and seven-day usage percentages, remaining percentages, reset timestamps and countdowns.
- Available **model-scoped weekly quotas** (e.g. Sonnet or Opus) and any extra-usage-credit metadata, if the account reports them.
- Cache served instantly by `/get`, automatically refreshed every **60 seconds** when Anthropic permits it.
- **429 backoff** (15 minutes, then 30, then 60, or longer if `Retry-After` says so). During rate limits, cached data is flagged `stale: true`, `ok: false` and shows an error; it is not misrepresented as current.
- Can run alongside your **Work/Codex API on port 3789**; this uses **3790**.

## Install / run (Windows 11 + Debian WSL)

1. Extract the ZIP.
2. Confirm Claude Code is signed in with your **Claude subscription** in Debian, not merely an `ANTHROPIC_API_KEY`. If necessary, open Claude Code and use `/login`.
3. In **PowerShell**, `cd` into the extracted `claude-usage-api` folder.
4. Run:

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-windows.ps1
   ```

   This uses the **same simple, tested WSL launch method as the working Codex API v2**. It calls `wsl.exe -d Debian -- bash -i ./start.sh`, with **no** `wslpath` or fragile `bash -c` quoting.

   **Alternative** from PowerShell in the folder:

   ```powershell
   wsl -d Debian -- bash -i ./start.sh
   ```

   Or inside Debian:

   ```bash
   cd /mnt/c/Users/YOURNAME/Desktop/claude-usage-api
   bash ./start.sh
   ```

5. Visit **http://localhost:3790/get**, or from PowerShell:

   ```powershell
   (Invoke-RestMethod http://localhost:3790/get).five_hour.remaining_percent
   ```

## Endpoints

- **`GET /get`**: cached quota JSON. No new Anthropic request is made by an HTTP caller.
- **`GET /health`**: `200` if up-to-date; `503` if stale or unavailable.
- **`GET /`**: endpoint information.

Illustrative JSON excerpt, not your real account usage:

```json
{
  "ok": true,
  "source": "anthropic-oauth-usage-undocumented",
  "stale": false,
  "updated_at": "2026-10-25T19:00:00Z",
  "age_seconds": 12,
  "refresh_interval_seconds": 60,
  "next_refresh_at": "2026-10-25T19:01:00Z",
  "error": null,
  "five_hour": {
    "used_percent": 45,
    "remaining_percent": 55,
    "duration_minutes": 300,
    "resets_at_unix": 1792969200,
    "resets_at": "2026-10-25T23:00:00Z",
    "resets_in_seconds": 14400
  },
  "weekly": {
    "used_percent": 25,
    "remaining_percent": 75,
    "duration_minutes": 10080,
    "resets_at_unix": 1793401200,
    "resets_at": "2026-10-30T23:00:00Z",
    "resets_in_seconds": 446400
  },
  "additional_limits": {
    "seven_day_sonnet": {
      "used_percent": 10,
      "remaining_percent": 90,
      "duration_minutes": 10080,
      "resets_at_unix": null,
      "resets_at": null,
      "resets_in_seconds": null
    }
  },
  "scoped_limits": [],
  "extra_usage": {
    "is_enabled": false,
    "used_credits": null,
    "monthly_limit": null,
    "utilization": null
  }
}
```

**JavaScript**:

```javascript
const usage = await fetch('http://localhost:3790/get').then(r => r.json());
if (usage.ok) {
  console.log(`Claude 5h: ${usage.five_hour?.remaining_percent ?? 'n/a'}% remaining`);
  console.log(`Claude week: ${usage.weekly?.remaining_percent ?? 'n/a'}% remaining`);
} else console.error('Claude usage unavailable:', usage.error);
```

**If fetching from a browser-based app with a different origin**, enable CORS for *only that specific origin*:

```bash
python3 server.py --cors-origin http://localhost:3000
```

## Configuration

```bash
python3 server.py --port 3790                # default, avoid Codex 3789
python3 server.py --interval 300             # less frequent polling (recommended if frequent 429s)
python3 server.py --once                     # fetch once and print JSON
python3 server.py --credentials /path/to/.credentials.json
python3 server.py --utilization-scale fraction  # ONLY if raw values use 0–1 instead of 0–100
```

By default, credentials are read from `~/.claude/.credentials.json` inside **Debian** (or `$CLAUDE_CONFIG_DIR/.credentials.json` if configured). It **re-reads** access tokens each poll to pick up normal rotations performed by Claude Code. It deliberately does **not** refresh or overwrite Claude Code's tokens: concurrent OAuth refresh can invalidate your login. If you see `access token expired` or `authentication rejected`, use Claude Code to renew the login, and the next successful API poll should recover.

## Important limitations

- Anthropic **does not publish a supported personal subscription quota API**. The app accesses the Claude Code client's **undocumented** `GET https://api.anthropic.com/api/oauth/usage` endpoint with its saved OAuth access token and `anthropic-beta: oauth-2025-04-20`. It can change or stop working. This service does **not** send tokens anywhere except to Anthropic's usage endpoint.
- This endpoint is sometimes **aggressively rate limited**, including when multiple Claude Code sessions already poll it. A **guaranteed** new Anthropic result every minute cannot be promised. Your `/get` endpoint is always available while the server runs and clearly states how fresh the values are. Consider `--interval 300` if you use many Claude Code instances.
- Authentication must be with **Claude subscription OAuth**, not pay-as-you-go Console API keys (which do not have the same five-hour/weekly subscription caps).
- If a window is absent, the API returns `null` rather than guessing a percentage. Some subscription plans have separate model-specific windows.
- Anthropic examples most commonly return `utilization` as a **percentage from 0–100**, which this app assumes. If your endpoint actually returns fractions from 0–1 and you verify that against Claude's `/usage` screen, use `--utilization-scale fraction`. The raw endpoint is undocumented, so units are not guaranteed.
- **Security**: listen only on `127.0.0.1`; credentials are never logged or returned; no CORS unless explicitly enabled; no external Python packages; no token refreshing or changes to your Claude Code settings. Don't forward port 3790 to the public internet or run the service behind a public reverse proxy.

## Troubleshooting

- `No Claude Code login`: run Claude Code with `/login` in **Debian**. Native Windows Claude credentials may be different from WSL credentials.
- `HTTP 429`: wait for the displayed `next_refresh_at` before trying again, or reduce polling with `--interval 300`.
- `Access token expired`: open Claude Code; its own login/refresh process should update credentials; otherwise `/login`.
- Windows cannot connect: check `curl http://localhost:3790/get` **inside** WSL first. WSL2 generally forwards localhost ports to Windows.
- Test: `python3 -m unittest discover -s tests -v` (includes local mock HTTP server; requires no Anthropic network or real login).

## Sources

- Anthropic: subscription limits are shared across Claude and Claude Code: https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan
- Claude Code official statusline docs (publicly supported rate-limit fields, but only after CLI activity): https://code.claude.com/docs/en/statusline
- Reverse-engineered usage API implementation details: https://github.com/MWZ-Code/openusage-cli/blob/main/docs/providers/claude.md
- Reports of OAuth usage endpoint HTTP 429s: https://github.com/anthropics/claude-code/issues/31637
