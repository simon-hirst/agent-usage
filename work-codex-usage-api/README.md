# Work + Codex Usage API

A tiny, dependency-free Python HTTP server that reads **live Work/Codex quota** from your signed-in **Codex CLI** via its documented `app-server` JSON-RPC protocol, caches the result and refreshes it every **60 seconds**.

Work and Codex currently share a usage pool, so this gives you both (when you use the same ChatGPT account/workspace for both).

## Run in Debian WSL (Windows 11)

1. Extract this ZIP somewhere accessible from WSL, e.g. your Windows Downloads folder.
2. Open **Debian WSL**, in the same shell where `codex` works.
3. Verify Codex is authenticated:

   ```bash
   codex login status
   ```

   If you aren't signed in, run `codex login`.

4. Go to the extracted folder. If it's in `C:\Users\YOURNAME\Downloads\work-codex-usage-api`:

   ```bash
   cd /mnt/c/Users/YOURNAME/Downloads/work-codex-usage-api
   ./start.sh
   ```

   You can also run `python3 server.py` from anywhere.

   **Alternative: one command from Windows PowerShell** in the extracted folder.
   The launcher switches to the folder containing the script and calls
   `bash -i ./start.sh` (without passing Bash code in `-c`, which caused a
   quoting failure in earlier builds). This loads your Codex PATH:

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-windows.ps1
   ```

5. In **Windows PowerShell** or a browser, open:

   ```text
   http://localhost:3789/get
   ```

   Windows 11 WSL2 normally forwards WSL-bound localhost services to Windows localhost. If the Windows URL doesn't work, try `curl http://127.0.0.1:3789/get` inside WSL first.

## Endpoints

- `GET /get` — most recent quota JSON, refreshed in the background every minute.
- `GET /health` — 200 if current; 503 if no current quota is available.
- `GET /` — endpoint listing.

Example response excerpt (illustrative percentages; the real response also includes `buckets`, reset times, freshness and other metadata):

```json
{
  "ok": true,
  "source": "codex-app-server",
  "updated_at": "2026-10-25T19:00:00Z",
  "age_seconds": 20,
  "refresh_interval_seconds": 60,
  "stale": false,
  "error": null,
  "plan": "plus",
  "five_hour": {
    "used_percent": 45,
    "remaining_percent": 55,
    "duration_minutes": 300,
    "resets_at_unix": 1792969200,
    "resets_at": "2026-10-25T23:00:00Z",
    "resets_in_seconds": 14380
  },
  "weekly": {
    "used_percent": 25,
    "remaining_percent": 75,
    "duration_minutes": 10080,
    "resets_at_unix": 1793401200,
    "resets_at": "2026-10-30T23:00:00Z",
    "resets_in_seconds": 446380
  }
}
```

`buckets` contains the full **normalized** quota buckets, including any additional model-specific buckets. The values above are examples only. Live fields that the provider doesn't supply (including missing five-hour windows on certain plans) are `null`—not inferred. Some plans expose only weekly usage.

For scripts:

```powershell
(Invoke-RestMethod http://localhost:3789/get).five_hour.remaining_percent
```

```bash
curl -s http://localhost:3789/get | python3 -m json.tool
```

## Options

```bash
python3 server.py --port 3789                   # default
python3 server.py --interval 60                 # default
python3 server.py --once                        # test login & response
python3 server.py --cors-origin http://localhost:3000  # allow browser fetch from this origin
python3 server.py --codex-path /full/path/to/codex     # custom CLI path
```

If a refresh fails, `/get` retains the previous values, marks them `stale: true`, sets `ok: false`, and includes an error; if no fetch has ever worked it responds HTTP 503. This avoids displaying old data as if current.

## Security

- HTTP listens **only on 127.0.0.1**, not the LAN. There is no public binding option.
- Your Codex auth tokens are handled by the existing `codex app-server` process; this script does not read or expose them.
- No third-party Python packages or API key are required.
- Browser CORS is off by default; use `--cors-origin` if you need to call from a local website.
- The Codex App Server API is official, but the exact quotas exposed can change as plans change. Run Codex CLI in the same account and workspace as ChatGPT Work.

## Troubleshooting

`codex not found`: run from the *same interactive WSL shell* where Codex CLI works, or pass `--codex-path`.

`No usable usage windows`: check the account is logged in with ChatGPT (not an API key) via `codex login status`, and that you have an allowance for Work/Codex. Check with the Codex CLI `/status` command as a comparison.

If the Windows launcher fails, use this command **from PowerShell in the extracted project folder**: `wsl -d Debian -- bash -i ./start.sh`. Or open Debian, `cd /mnt/c/Users/YOURNAME/Desktop/work-codex-usage-api`, and run `bash ./start.sh`. If `server.py` is not found, check you extracted the ZIP, and that your Windows drives are mounted in Debian.

Windows cannot reach `localhost`: verify it works with `curl http://localhost:3789/get` **inside** WSL, and check Windows/WSL localhost forwarding configuration.

Tests: `python3 -m unittest discover -s tests -v`.

Sources: https://learn.chatgpt.com/docs/app-server (official app-server spec); https://help.openai.com/en/articles/20001516-managing-usage-with-gpt-6-astra-in-work-and-codex (shared usage).
