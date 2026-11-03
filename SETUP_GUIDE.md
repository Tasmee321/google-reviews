# Dedicated Firefox and UK-IP setup

## Apply an update

Finish or cancel the active review, stop the old terminal with Ctrl+C, and close
its dedicated browser. Back up `personal_data/` before replacing source
files. Preserve your existing `personal_data/`, `.env` and any custom config.
The update does not copy or erase personal Chrome/Firefox profiles.

Run `install.bat`, then `check_setup.bat`, then `run.bat`.
The installer creates a project-local `.venv` and only creates `config.json`
from the example when config is missing; it does not overwrite an existing config.
Supplied defaults now select `mode=extension` and ordinary Firefox. Check old
`.env` overrides: `REVIEW_MODE=poster` or `REVIEW_BROWSER=chrome` still take precedence.
Keep the existing `personal_data/firefox-profile/`; never reset it to apply an update.
The same signed add-on ID and Firefox login profile must be reused.

For Firefox, use **extension 1.0.8**. It fixes the native network request invocation
in 1.0.7; the UK check remains mandatory. Build it with `python build_firefox_extension.py`,
submit the unsigned XPI/source ZIP under the existing Mozilla add-on
`tasmee-personal-reviews@local.invalid`, and obtain Mozilla's signed XPI. The build
does not upload, sign or install anything. In the dedicated Firefox window open
`about:addons` → gear → **Install Add-on From File**, select the signed 1.0.8 XPI,
approve its added network/data permissions and refresh the dashboard. The older
signed 1.0.6 is not compatible with UK-IP protection. Do not disable Firefox's
signing checks. Temporary installation in `about:debugging` is development-only
and ends when Firefox closes.

## Avast SecureLine VPN

1. Open your already-paid Avast SecureLine VPN application.
2. Select an available **United Kingdom** server and connect it yourself.
3. Enable its kill switch. Keep Firefox (`firefox.exe`) out of split-tunnel
   exclusions. If using optional Chrome/Edge/poster, include that executable too.
4. Keep Avast connected while signing in and using Google Maps.

No application proxy, proxy rotation, extra VPN purchase or Avast password/API
key is needed. The app uses the operating-system network connection. It does not
start Avast or change its settings. The enabled UK-IP guard samples country from
the actual extension browser via Cloudflare HTTPS trace endpoints, including a forced
IPv4 sample. It does not certify Avast connection state, DNS or every IPv6 route.
An Avast UK exit is not available separately for every city in the city picker.

## Install and launch

- Python **3.11+** and ordinary Mozilla Firefox **142+** are the defaults. Enable Python on PATH.
- `install.bat`: installs Python dependencies in `.venv`, validates setup, and
  downloads Playwright Chromium only if poster mode selects `browser_channel=chromium`.
- `check_setup.bat`: checks dependencies, config, city data and browser presence.
  It does not open a browser, access Google or submit anything.
- `run.bat` / `start_localhost.bat`: starts the configured local workflow and
  opens its private dashboard link in the same ordinary dedicated Firefox profile.
  No remote debugger, Playwright Firefox or security-preference override is used.
- An already-running dashboard is reused, not replaced. Restart it after a config change.
- `run_firefox.bat`: explicitly selects the recommended Firefox extension flow.
- `run_chrome.bat`: optional ordinary Chrome flow; install the updated 1.0.7 extension.
- Optional `mode=poster`: retained Playwright Chrome flow with a separate persistent
  profile, explicitly enabled Chromium sandbox and no unsandboxed launch fallback.

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
| `mode` | `extension` | Ordinary Firefox and guarded extension; `poster` retains optional Playwright Chrome. |
| `port` | `5000` | Local dashboard port, 1–65535. |
| `browser_channel` | `chrome` | Poster-only: Chrome, `msedge` or Playwright `chromium`; does not select Firefox. |
| `locale` | `en-GB` | Poster-only language setting; Google form selectors currently expect English. Ordinary Firefox preferences remain unchanged. |
| `device` | `null` | Poster-only optional exact Playwright device descriptor; no emulation by default. |
| `city_geolocation` | `false` | Search-only city picker. Optional browser coordinate emulation is not a review-publication aid. |
| `network_guard.enabled` | `true` | Require UK results. Extension 1.0.7 independently always enforces its browser-side guard, even if this backend setting is false. |
| `network_guard.interval_seconds` | `30` | Poster-only idle polling/lifetime, 15–120 seconds. Extension uses fixed 30-second freshness and dashboard idle polling. |
| `network_guard.timeout_ms` | `8000` | Poster-only per-endpoint timeout, 2000–15000 ms. Extension has a fixed 8000 ms endpoint limit. |
| `proxies` | `[]` | Must stay empty for this Avast-based setup. |
| `target.lat`, `target.lng` | `null` | Poster-only optional manual location fallback; Firefox city selection is always search-only. |
| `target.timezone` | `Europe/London` | Poster-only browser timezone, including GMT/BST; ordinary Firefox preferences remain unchanged. |
| `delay_range` | `[0, 0]` | Optional bounded pacing in seconds; maximum 10. |
| `timeouts.navigation_ms` | `45000` | Navigation timeout; allowed 1000–60000 ms. |
| `timeouts.element_ms` | `15000` | Element/action timeout; allowed 1000–60000 ms. |

Legacy `api_key` and `target.name` values are accepted for compatibility but are
not used. Business details come from the selected Maps page, not the Places API.
Neither an API key nor a business/account list is required.

Optional `.env` overrides (see `.env.example`):

```dotenv
REVIEW_MODE=extension
REVIEW_BROWSER=firefox
PORT=5000
REVIEW_OPEN_BROWSER=1
```

`REVIEW_BROWSER=firefox` (default) or `chrome` chooses the browser only in extension mode.
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
Google Maps URL is passed unchanged. In the recommended setup, selecting a city
changes search context only. It does not change
the device's system-wide location, the public IP, the Avast server, or the selected
business. Check the resolved business name/address before posting.

## Optional city-location emulation (OFF)

`city_geolocation` is disabled and manual coordinates are null in the supplied
config. Keep this setup for genuine review posting. The emulation capability is
retained for browser testing, not for fabricating a visit. If deliberately enabled,
it works as follows; this is not the recommended live-review flow.

- The status under the city picker shows ON/OFF and the selected location.
- Choose the city before Google sign-in if it must apply from the first poster
  browser session. Choosing it does not itself launch a browser or sign in.
- An already-open poster browser updates in place; no restart is needed per city.
- Location changes are blocked during active reviews or other browser operations.
- **All United Kingdom** clears the city override and its application-granted
  geolocation permissions. If manual `target.lat/lng` exist, those are restored;
  with the supplied null values, no simulated position is available.
- Dashboard refresh and a successful post keep the selected city. A server restart
  clears the session selection; choose the city again, or configure a fixed manual fallback.
- Geolocation permission is granted only for supported Google origins, not every
  website. This applies to the dedicated poster browser, not personal browser tabs.
- Optional Chrome/Firefox extension modes remain search-only; this feature requires poster mode.

The offline coordinates in `uk_city_locations.json` are representative city/area
points, not precise addresses or device positions. Source: **© OpenStreetMap
contributors**, obtained through Nominatim on **3 November 2026**, licensed under
[ODbL 1.0](https://www.openstreetmap.org/copyright). Each point includes its OSM
source URL. Preserve the attribution when redistributing the coordinate dataset.
No geocoding call happens when you choose a city. Neither geolocation emulation
nor a UK VPN exit hides the identity of a signed-in Google account.

## Sign-in, review and account switching

1. Connect Avast UK and install the signed 1.0.8 extension in dedicated Firefox,
   then **Check UK IP**. Enter the Google email, choose **Open Google sign-in**,
   and finish password/2FA directly on Google's page in dedicated Firefox.
2. Click **Check connection**. The exact connected email is verified and saved as
   a local shortcut. A shortcut is not a stored password or an independent session.
3. Choose a city and enter a business search, or paste a Maps business/share link.
4. Click **Start** to fetch the business. Supply 1–5 stars and your exact text to
   prepare its review form. No submission happens during preparation.
5. Check the exact preview and per-review policy confirmation, then click **Post this review** once. UK IP, account, branch, text and overall rating are
   rechecked. Food/Service/Atmosphere ratings in embedded forms are not changed.
6. Use **Switch account** only when the worker is idle and there is no active draft.

Google may require extra verification or reject a sign-in; the app does not
bypass challenges. Ordinary Firefox does not guarantee account acceptance.
The optional automated poster can also be rejected by Google. Live sign-in is
separate from fixture-based tests. Never enter passwords, OTPs or recovery codes
into the dashboard, config files or diagnostics.

## UK-IP guard and diagnostics

- Samples are fetched by the actual extension browser, not Python's or Node's
  possibly different VPN route. Both `https://www.cloudflare.com/cdn-cgi/trace`
  and `https://1.1.1.1/cdn-cgi/trace` must report GB. Same-city matching is not used.
- A check is forced before protected Google actions, navigation and final
  submission. The visible, connected, idle dashboard also checks about every 30
  seconds. Its sample expires after 30 seconds; worker restart resets it to unknown.
  Closing/hiding the dashboard or a busy operation can stop/delay idle polling.
  Protected extension commands still force their own fresh checks.
- Non-UK, timeout, service error, redirect or malformed response is a block, never
  a fallback success. Firefox is not closed automatically and unrelated manual
  browser actions are not blocked. Uncertain submissions are never automatically
  reposted. The optional poster instead samples its browser context and closes
  that context on failure; interrupted poster drafts need preparation again.
- These are point-in-time country estimates, not continuous leak prevention or
  proof that Avast is connected. A route can change after checking. **Avast's OS
  kill switch remains necessary.** No claim is made about all DNS/IPv6 routes or
  direct manual interactions with Google outside app-controlled actions.
- Dashboard country reports are assertions from the installed extension/local
  dashboard, not cryptographic proof or an OS firewall. The extension independently
  enforces its checks. Do not load untrusted extensions/scripts into this profile.
- Cloudflare sees the public IP and ordinary browser request metadata. No review
  text, Google credentials or Google cookies are supplied to the probe endpoints.
- Use **Download private diagnostics** for versions, protection status, last check
  and the last 50 fixed error events. The report excludes personal review/account
  data, full IPs, tokens and paths. Events reset when the server restarts.
- `python check_setup.py --diagnostics` runs offline and does not launch a browser
  or contact an IP service. Missing storage is reported as unverified, not created.

## Local session protection

The dashboard requires a secret per-launch link/code in addition to localhost
checks and CSRF protection. The launcher opens the private link automatically;
the terminal prints it for manual use. Never share or screenshot it. The token
uses the URL fragment, is removed from browser history before being sent in a
same-origin JSON request, and is never put in URL queries or diagnostic exports.
After eight hours unlock again with the current terminal link. Restarting rotates
the token and invalidates previous dashboard sessions. Only a public, data-free
health check and the unlock screen are accessible without it.

Before the lock, database or browser profile is opened, storage permissions are
checked and restricted to the current OS account (plus SYSTEM on Windows).
Existing file contents are preserved. Unexpected ownership, linked paths, hard
links, unprotectable files or a tree over 100,000 entries stop startup rather than
silently continue. Do not run this tool against someone else's copied profile.

Future Windows files inherit the restricted ACL. POSIX production startup uses a
077 umask and 0700 directories/0600 files. Permissions are **not encryption**;
administrators, malware running as you and unencrypted offline disk access are
outside this protection. Keep Windows locked when unattended and enable disk
encryption. Account shortcuts are not passwords; the persistent browser session
is still sensitive. Do not include session directories in source ZIPs or reports.

## History and monitoring

- `personal_data/reviews.sqlite3`: drafts, history, account shortcuts and minimal
  duplicate-protection receipts. The database is not encrypted.
- `personal_data/browser/`: poster's persistent Google browser profile.
- `personal_data/firefox-profile/`: default persistent Firefox profile and signed add-on.
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
| Browser missing | Install ordinary Firefox142+; optional poster needs Chrome/Edge or selected Chromium. |
| Profile already in use | Use the existing dedicated Firefox window, or close it before relaunching; do not erase its profile. |
| Dashboard already running | Use that tab or stop the old server before restarting. |
| Google account mismatch | Select the intended account in Google, then Check connection. |
| Form/branch/rating cannot be verified | Inspect Maps; the draft has not been submitted. |
| Unconfirmed submission | Inspect your own saved review before any further attempt. |
| Extension missing/outdated | Install Mozilla-signed 1.0.8 in the existing dedicated Firefox profile and refresh. |
| Firefox 1.0.7 says UK IP could not be confirmed | Update to signed 1.0.8; its native fetch binding is fixed. Do not disable UK protection. |
| Wrong browser/mode | Check `mode`, old `.env` overrides and which launcher you used. |
| UK IP not confirmed | Connect Avast UK, check internet and retry Check UK IP. Cloudflare/service failures also block. |
| Local protection failed | Close the browser/app, check ownership and remove unsafe links from the intended data tree; do not weaken permissions. |
| Policy confirmation missing | Review the prepared branch/account/text, then tick the confirmation. |
| Website/email blocked | Cancel the draft, remove contact/link content yourself and prepare again. |

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
