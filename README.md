# Tasmee Personal Reviews

Local Flask dashboard for preparing and explicitly submitting your own Google
Maps reviews through an ordinary, persistent Firefox profile and a signed
browser extension. No cloud deployment, bulk posting, IP rotation or spoofing.

## Windows quick start

1. Install Python 3.11+ and ordinary Mozilla Firefox 142+.
2. Run `install.bat` to install Python dependencies.
3. Run `start_localhost.bat`, or `run.bat` (dedicated Firefox).
4. Install the Mozilla-signed extension into that Firefox profile through
   `about:addons` → Install Add-on From File.
5. Sign in directly with Google and click Check connection in the dashboard.
6. Enter your genuine review and business link, click Start, then explicitly Post.

Dashboard: http://127.0.0.1:5000/ . Keep the server terminal open.

## Features

- Verified account, business, exact text and star rating before submission.
- Success-only composer reset; uncertainty is not silently marked successful.
- History details, local deletion, filters, pagination and business/address counts.
- Verified account shortcuts with one active account at a time.
- Conservative read-only saved-review monitoring while the dashboard is open.
- Local-only API, origin/CSRF protection and duplicate/retry safeguards.

Saved/submitted status does **not** prove public visibility. Google moderates
reviews independently. VPN protection is neither controlled nor verified by
this app, and cannot guarantee that a review stays published.

## Build Firefox extension

```powershell
python build_firefox_extension.py
```

Outputs include unpacked sources, a versioned **unsigned** XPI and a clean source
ZIP for Mozilla signing. Normal Firefox requires the resulting signed XPI for
permanent installation. Signing protection must not be disabled. Generated
artifacts and browser profiles are intentionally excluded from Git.

## Tests

```powershell
python -m unittest discover -s tests -v
node tests/test_extension_transport.js
```

Browser tests use intercepted Google fixtures, not real accounts or reviews.
They require the configured Chrome/test Chromium runtime. Unit/API tests can
run without controlling a live browser.

## Local data

Passwords, account lists, environment files, browser sessions, review databases,
backups and test outputs must not be committed. Local history deletion leaves
minimal business/count and keyed account-hash receipts for duplicate protection;
it does not delete Google reviews or existing backups. The database is not
encrypted. Legacy account credentials are not used by the current workflow.

See [SETUP_GUIDE.md](SETUP_GUIDE.md), [EXTENSION_PRIVACY.md](EXTENSION_PRIVACY.md)
and [FIREFOX_SOURCE_BUILD.md](FIREFOX_SOURCE_BUILD.md) for detailed setup,
limitations, data handling and reproducible extension builds.
