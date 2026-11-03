# UK poster setup

## Apply an update

Finish or cancel the active review, stop the old terminal with Ctrl+C, and close
its dedicated poster browser. Back up `personal_data/` before replacing source
files. Preserve your existing `personal_data/`, `.env` and any custom config.
The update does not copy or erase personal Chrome/Firefox profiles.

Run `install.bat`, then `check_setup.bat`, then `run.bat`.
The installer creates a project-local `.venv` and only creates `config.json`
from the example when config is missing; it does not overwrite an existing config.

## Avast SecureLine VPN

1. Open your already-paid Avast SecureLine VPN application.
2. Select an available **United Kingdom** server and connect it yourself.
3. Enable its kill switch. Keep Chrome (`chrome.exe`), Edge (`msedge.exe`), or
   the chosen bundled Chromium executable out of split-tunnel exclusions.
4. Keep Avast connected while signing in and using Google Maps.

No application proxy, proxy rotation, extra VPN purchase or Avast password/API
key is needed. The app uses the operating-system network connection. It does not
start Avast, change its settings or verify effective browser/IP/DNS/IPv6 routing.
The optional IP-check link is an external service contacted only when clicked.
An Avast UK exit is not available separately for every city in the city picker.

## Install and launch

- Python **3.11+** and Google Chrome are the defaults. Enable Python on PATH.
- `install.bat`: installs Python dependencies in `.venv`, validates setup, and
  downloads Playwright Chromium only if `browser_channel` is `chromium`.
- `check_setup.bat`: checks dependencies, config, city data and browser presence.
  It does not open a browser, access Google or submit anything.
- `run.bat` / `start_localhost.bat`: starts the configured local workflow and
  opens its dashboard in your default browser. The poster opens a separate,
  persistent Chrome window when Google sign-in is requested.
- An already-running dashboard is reused, not replaced. Restart it after a config change.
- `run_chrome.bat` / `run_firefox.bat`: explicit legacy extension modes.

Manual startup after installation:

```powershell
.\.venv\Scripts\python.exe app.py
```

## Configuration

`config.json` contains functional defaults, not values that must be filled in.
The example file has the same defaults. Invalid JSON/settings stop startup with
an error instead of silently selecting another mode.

| Setting | Default | Behaviour |
| --- | --- | --- |
| `mode` | `poster` | `poster.py` / Playwright; `extension` retains the old browser bridge. |
| `port` | `5000` | Local dashboard port, 1–65535. |
| `browser_channel` | `chrome` | Installed Chrome; `msedge` for Edge; `chromium` for Playwright's browser. |
| `locale` | `en-GB` | Browser language; Google form selectors currently expect English. |
| `device` | `null` | Desktop; an optional exact Playwright device name enables that descriptor. |
| `proxies` | `[]` | Must stay empty for this Avast-based setup. |
| `target.lat`, `target.lng` | `null` | No coordinate override. City selection never writes these values. |
| `target.timezone` | `Europe/London` | UK browser timezone, including seasonal GMT/BST changes. |
| `delay_range` | `[0, 0]` | Optional bounded pacing in seconds; maximum 10. |
| `timeouts.navigation_ms` | `45000` | Navigation timeout; allowed 1000–60000 ms. |
| `timeouts.element_ms` | `15000` | Element/action timeout; allowed 1000–60000 ms. |

Legacy `api_key` and `target.name` values are accepted for compatibility but are
not used. Business details come from the selected Maps page, not the Places API.
Neither an API key nor a business/account list is required.

Optional `.env` overrides (see `.env.example`):

```dotenv
REVIEW_MODE=poster
BROWSER_CHANNEL=chrome
PORT=5000
REVIEW_OPEN_BROWSER=1
```

`REVIEW_BROWSER=firefox` or `chrome` chooses the browser only in extension mode.
`REVIEW_OPEN_BROWSER=0` starts the server without opening the dashboard.

## UK city coverage

The picker uses `uk_cities.json`: **55 England, 8 Scotland, 7 Wales, 6 Northern
Ireland** cities. Bangor in Wales and Bangor in Northern Ireland are distinct
search options. Major destinations including London, Birmingham, Manchester,
Leeds, Liverpool, Glasgow, Edinburgh, Cardiff and Belfast are included.

Source: [GOV.UK list of cities](https://www.gov.uk/government/publications/list-of-cities/list-of-cities-html),
checked **3 November 2026**. Crown Dependencies and Overseas Territories are not
included. This is a city list, not a list of every UK town or borough.

For a business-name search the selected city and nation are appended to the
query. **All United Kingdom** adds UK context without choosing a city. A complete
Google Maps URL is passed unchanged. The picker does not set device coordinates,
spoof a visit, select a random branch or switch the VPN. Check the resolved
business name/address before posting.

## Sign-in, review and account switching

1. Enter the Google email, choose **Open Google sign-in**, and finish password/2FA
   directly in Google's dedicated poster window.
2. Click **Check connection**. The exact connected email is verified and saved as
   a local shortcut. A shortcut is not a stored password or an independent session.
3. Choose a city and enter a business search, or paste a Maps business/share link.
4. Click **Start** to fetch the business. Supply 1–5 stars and your exact text to
   prepare its review form. No submission happens during preparation.
5. Click **Post this review** once. Account, branch, text and overall rating are
   rechecked. Food/Service/Atmosphere ratings in embedded forms are not changed.
6. Use **Switch account** only when the worker is idle and there is no active draft.

Google may reject an automated-browser sign-in. The app reports the condition;
it does not bypass the challenge. The optional normal-browser extension workflow
remains available. Live sign-in is separate from the fixture-based tests.

## History and monitoring

- `personal_data/reviews.sqlite3`: drafts, history, account shortcuts and minimal
  duplicate-protection receipts. The database is not encrypted.
- `personal_data/browser/`: poster's persistent Google browser profile.
- `personal_data/firefox-profile/`: retained optional Firefox profile.
- Success clears the submitted composer; uncertainty does not erase the text.
- Refresh clears composer fields while retaining active-job/history state.
- Local deletion requires confirmation, never deletes a Google review, and keeps
  minimal business counts and keyed account-hash receipts for duplicate protection.
- Automatic saved-review checks need the visible, idle dashboard and the matching
  connected account. At most one check per 10 minutes globally, each review no
  more often than every 6 hours; failures back off 30 minutes.
- Manual saved checks have a 60-second cooldown. Checks are read-only and never
  repost, rewrite reviews or switch accounts automatically.
- Success means an explicit submission confirmation or matching own saved review.
  **Public visibility remains unknown.** A failed check is not proof of removal.
- Restart converts interrupted submission to an uncertain state, never to success
  and never to an automatic retry.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Config error | Fix the named value or compare with `config.example.json`; restart. |
| Missing dependency | Run `install.bat`; use the project's `.venv` interpreter. |
| Browser missing | Install Chrome/Edge, or select `chromium` and rerun `install.bat`. |
| Profile already in use | Close the other poster instance; do not erase its profile. |
| Dashboard already running | Use that tab or stop the old server before restarting. |
| Google account mismatch | Select the intended account in Google, then Check connection. |
| Form/branch/rating cannot be verified | Inspect Maps; the draft has not been submitted. |
| Unconfirmed submission | Inspect your own saved review before any further attempt. |
| Extension setup shown | Check `mode`, `.env`, and which launcher you used. |

## Tests

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe build_firefox_extension.py
node tests/test_extension_transport.js
```

Tests use temporary databases/profiles and intercepted Google pages. They cover
both poster and extension modes. They do not test a live Google account, Avast
protection, actual review publication, or Google moderation outcomes.
