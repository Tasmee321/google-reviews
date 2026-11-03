# Tasmee Personal Reviews — dedicated Firefox setup

Local Flask dashboard connected to an ordinary, dedicated Firefox profile through
the Tasmee extension. One verified Google account and one review at a time;
posting needs an explicit **Post this review** click. Firefox is not launched
through Playwright or a remote debugger. The older poster flow remains optional.

## Windows quick start

1. Install Python 3.11+ with **Add Python to PATH**, and ordinary Mozilla Firefox 142+.
2. Connect your existing Avast SecureLine VPN to an available **United Kingdom**
   server. Enable its kill switch and keep the selected browser out of split-tunnel exclusions.
3. Run `install.bat` once. It installs dependencies in this project's `.venv`.
4. Run `run.bat` or `start_localhost.bat`. Its private link unlocks the dashboard;
   keep the terminal open and do not share that link/code. The default opens the
   same dedicated Firefox profile at `personal_data/firefox-profile/` every time.
5. Install the **Mozilla-signed Tasmee 1.0.7 add-on** in that Firefox profile using
   `about:addons` → gear → **Install Add-on From File**, then refresh the dashboard.
   Build outputs here are unsigned: building does not sign or install the add-on.
   Update the existing Mozilla add-on ID, do not register a different ID.
6. Click **Check UK IP**. The dedicated Firefox browser must report UK before
   Google sign-in/posting. Choose a city for business search; location spoofing is OFF.
7. Open Google sign-in and finish it in dedicated Firefox, then click
   **Check connection**. Search a business or paste its Maps link, enter your
   review/rating, click **Start**, check the final preview and policy confirmation,
   then explicitly **Post**.

The default address is http://127.0.0.1:5000/ . `check_setup.bat` diagnoses
configuration, dependencies and browser installation without signing in or posting.

## Configured defaults

- Main flow: `mode=extension`, `REVIEW_BROWSER=firefox`; existing dedicated profile
  and installed signed add-on are preserved. Ordinary Firefox preferences are unchanged.
- All **76 UK cities** from the GOV.UK city list, grouped by nation.
- No application proxy: `proxies` must remain `[]`. Windows/Avast controls routing.
- City geolocation is OFF: the city picker is search-only.
  No device emulation or random user-agent changes are enabled.
- Extension 1.0.7 forces UK-IP checks before protected Google actions and final
  submission; the visible, connected, idle dashboard also checks about every 30 seconds.
- Protected local session/history folder and redacted diagnostics downloads.
- History, account shortcuts, duplicate protection and read-only saved-review checks.

City selection narrows **business search**, not the VPN exit IP or device position.
UK-IP checks sample the actual extension browser through two fixed Cloudflare HTTPS
trace endpoints. Non-UK, invalid or unavailable results block app-controlled actions;
there is no success fallback or automatic repost. Firefox is not closed automatically.
The checks do not control manual activity in other Firefox tabs.
The app neither switches Avast nor certifies its kill switch, DNS or all IPv6
routes. Samples are not continuous protection: keep Avast's kill switch enabled.
A saved review confirms saved status only; public visibility remains unknown.

`config.json` is ready to use. `config.example.json` is the reset/reference copy.
No Google Maps API key, proxy subscription or Google password in a config file is required.

Coordinates for all 76 cities are bundled in `uk_city_locations.json`: representative
city/area points from [OpenStreetMap contributors, ODbL](https://www.openstreetmap.org/copyright),
retrieved 3 November 2026. The optional coordinate-emulation feature is retained
for testing but disabled in the recommended configuration. No geocoding requests
are made. UK IP is a personal routing preference, not a Google review requirement.

## Build and optional flows

`run.bat` follows config; supplied defaults use dedicated Firefox. `run_firefox.bat`
explicitly selects this flow. An old `.env` override can still select poster/Chrome:
remove it or use `REVIEW_MODE=extension` and `REVIEW_BROWSER=firefox`.
`run_chrome.bat` selects ordinary Chrome with the updated 1.0.7 extension.
The 1.0.7 extension always enforces its browser-side guard; legacy 1.0.6 is not compatible.

`python build_firefox_extension.py` creates deterministic unsigned XPI and complete
stdlib-only build-source ZIP files for 1.0.7. See [FIREFOX_SOURCE_BUILD.md](FIREFOX_SOURCE_BUILD.md).
Permanent ordinary-Firefox installation requires Mozilla signing. No signing,
upload or signing-security bypass is performed by the build.

Optional `mode=poster` uses `poster.py` / Playwright with installed Chrome and its
separate existing `personal_data/browser/` profile. Chromium sandboxing is explicitly
enabled; browser-start failure does not trigger an unsandboxed retry. Its language/
timezone options are `en-GB`/`Europe/London`, not overrides for normal Firefox.

## Privacy and policy safeguards

Local storage is restricted to the current OS user (and SYSTEM on Windows),
including future browser-profile files. Unsafe ownership/links/permissions stop
startup. This is **not encryption** or protection against administrators or malware
running as the same user. Use Windows screen lock and full-disk encryption; never
share a browser-profile backup.
The local dashboard also requires a private per-launch code, so another local
Windows account cannot simply query history or control the signed-in browser over
localhost. The launcher supplies the code in a URL fragment (not HTTP logs), clears
it from the address bar, and establishes an HTTPOnly session lasting eight hours.
Restarting rotates the code and invalidates old dashboard sessions.

**Download private diagnostics** exports versions, protection status and bounded
fixed error codes, not review text, emails, cookies, passwords, full IPs or paths.
Cloudflare receives the IP-check requests; it receives no review text or Google
credentials. Offline diagnostics: `python check_setup.py --diagnostics`.

Final posting requires a fresh per-review self-confirmation. Clear website/email
inclusions block posting; possible phone numbers, repeated wording and previous
same-business reviews under another local account get manual-review warnings.
These checks do not prove authenticity or guarantee Google's approval. Read
[GOOGLE_REVIEW_GUIDE.md](GOOGLE_REVIEW_GUIDE.md) for the remaining human checks.

## Verification

```powershell
.\.venv\Scripts\python.exe check_setup.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe build_firefox_extension.py
node tests/test_extension_transport.js
```

Browser tests use temporary profiles and intercepted Google fixtures, not live
accounts or reviews. They require Chrome and Playwright test Chromium; install
the latter with `.\.venv\Scripts\python.exe -m playwright install chromium`.

See [SETUP_GUIDE.md](SETUP_GUIDE.md) for configuration, Avast setup and troubleshooting.
Session data lives under `personal_data/`; do not commit it, `.env`, backups,
account lists or private keys. Local history deletion does not remove Google reviews.
