# Tasmee Personal Reviews — UK poster setup

Local Flask dashboard backed by `poster.py` / Playwright by default. One
verified Google account and one review at a time; posting needs an explicit
**Post this review** click. No browser extension is needed in poster mode.

## Windows quick start

1. Install Python 3.11+ with **Add Python to PATH**, and Google Chrome.
2. Connect your existing Avast SecureLine VPN to an available **United Kingdom**
   server. Enable its kill switch and keep the selected browser out of split-tunnel exclusions.
3. Run `install.bat` once. It installs dependencies in this project's `.venv`.
4. Run `run.bat` or `start_localhost.bat`. Keep the terminal open.
5. Choose a UK city. Its approximate browser location is selected immediately,
   including before Google sign-in. The location status appears under the picker.
6. Open Google sign-in and finish it in the dedicated poster browser, then click
   **Check connection**. Search a business or paste its Maps link, enter your
   review/rating, click **Start**, then explicitly **Post**.

The default address is http://127.0.0.1:5000/ . `check_setup.bat` diagnoses
configuration, dependencies and browser installation without signing in or posting.

## Configured defaults

- Main engine: `poster.py`; Chrome with a persistent local profile.
- UK language/time: `en-GB` and `Europe/London` (GMT/BST).
- All **76 UK cities** from the GOV.UK city list, grouped by nation.
- No application proxy: `proxies` must remain `[]`. Windows/Avast controls routing.
- Automatic city geolocation is enabled: choose a city to apply its coordinates.
  No device emulation or random user-agent changes are enabled.
- History, account shortcuts, duplicate protection and read-only saved-review checks.

City selection narrows **business search** and changes the poster browser's
reported geolocation, **not** the VPN exit IP. All United Kingdom clears the city
override (or restores manual coordinates if configured). The app
neither switches Avast servers nor verifies its IP/DNS/IPv6 protection. A saved
review confirms saved status only; public visibility remains unknown.

`config.json` is ready to use. `config.example.json` is the reset/reference copy.
No Google Maps API key, proxy subscription or Google password in a config file is required.

Coordinates for all 76 cities are bundled in `uk_city_locations.json`: representative
city/area points from [OpenStreetMap contributors, ODbL](https://www.openstreetmap.org/copyright),
retrieved 3 November 2026. City changes make no live geocoding requests. Selection
survives dashboard refresh and successful posts, but must be chosen again after a
server restart. Set `city_geolocation` to `false` to keep the picker search-only.

## Optional extension modes

`run_chrome.bat` explicitly selects the existing Chrome extension workflow.
`run_firefox.bat` explicitly selects the existing dedicated Firefox workflow;
normal Firefox still needs a Mozilla-signed add-on. Existing profiles and signed
add-ons are preserved. To build extension sources: `python build_firefox_extension.py`.

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
