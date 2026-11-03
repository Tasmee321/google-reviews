# Tasmee Personal Reviews — UK poster setup

Local Flask dashboard backed by `poster.py` / Playwright by default. One
verified Google account and one review at a time; posting needs an explicit
**Post this review** click. No browser extension is needed in poster mode.

## Windows quick start

1. Install Python 3.11+ with **Add Python to PATH**, and Google Chrome.
2. Connect your existing Avast SecureLine VPN to an available **United Kingdom**
   server. Enable its kill switch and keep the selected browser out of split-tunnel exclusions.
3. Run `install.bat` once. It installs dependencies in this project's `.venv`.
4. Run `run.bat` or `start_localhost.bat`. Its private link unlocks the dashboard;
   keep the terminal open and do not share that link/code.
5. Click **Check UK IP**. The dedicated poster browser must report UK before
   Google sign-in/posting. Choose a city for business search; location spoofing is OFF.
6. Open Google sign-in and finish it in the dedicated poster browser, then click
   **Check connection**. Search a business or paste its Maps link, enter your
   review/rating, click **Start**, check the final preview and policy confirmation,
   then explicitly **Post**.

The default address is http://127.0.0.1:5000/ . `check_setup.bat` diagnoses
configuration, dependencies and browser installation without signing in or posting.

## Configured defaults

- Main engine: `poster.py`; Chrome with a persistent local profile.
- UK language/time: `en-GB` and `Europe/London` (GMT/BST).
- All **76 UK cities** from the GOV.UK city list, grouped by nation.
- No application proxy: `proxies` must remain `[]`. Windows/Avast controls routing.
- City geolocation is OFF: the city picker is search-only.
  No device emulation or random user-agent changes are enabled.
- UK-IP checks before sign-in, before submission and about every 30 idle seconds.
- Protected local session/history folder and redacted diagnostics downloads.
- History, account shortcuts, duplicate protection and read-only saved-review checks.

City selection narrows **business search**, not the VPN exit IP or device position.
UK-IP checks sample the actual poster browser through two fixed Cloudflare HTTPS
trace endpoints. Non-UK, invalid or unavailable results block app actions and
close the poster browser; there is no success fallback or automatic repost.
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

## Optional extension modes

`run_chrome.bat` explicitly selects the existing Chrome extension workflow.
`run_firefox.bat` explicitly selects the existing dedicated Firefox workflow;
normal Firefox still needs a Mozilla-signed add-on. Existing profiles and signed
add-ons are preserved. To build extension sources: `python build_firefox_extension.py`.
The UK-IP guard cannot verify extension traffic, so extension network actions are
blocked while it is enabled. Disabling it explicitly removes that protection.

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
