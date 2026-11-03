# Tasmee Personal Reviews — Firefox build source

## Requirements

- Python 3.11 or newer (standard library only).
- No pip, npm, network access, credentials or commercial build tools are required.

## Build

Extract this source archive into an empty directory, then run in that directory:

```sh
python build_firefox_extension.py
```

On systems where the Python command is `python3`, use:

```sh
python3 build_firefox_extension.py
```

The outputs are:

- `firefox_extension/`: unpacked Firefox add-on files.
- `dist/tasmee-firefox-unsigned.xpi`: the unsigned distribution package.
- `dist/tasmee-firefox-1.0.7-unsigned.xpi`: the same unsigned versioned package.
- `dist/tasmee-firefox-1.0.7-source.zip`: all inputs needed to reproduce this build.

## Build transformations

The original extension files are in `chrome_extension/`. The Python script:

1. Changes the background service worker to Firefox scripts, loading
   `network_guard.js` before `background.js`.
2. Retains the Firefox ID `tasmee-personal-reviews@local.invalid`, sets the minimum
   version to 142.0 and declares handled data, including IP-derived country.
3. Replaces `chrome.` API namespace references with Firefox's promise-based `browser.` references.
4. Copies the readable HTML/CSS without preprocessing and packages the privacy document.

The code is not minified, obfuscated or bundled. No third-party JavaScript libraries
are included. Archive entries are sorted, use a fixed 1980-01-01 timestamp and
0644 file permissions; repeated builds with the same inputs and Python/zlib
implementation produce identical unsigned XPI/source ZIP bytes. Across compression
implementations, compare extracted names and file contents as well. Mozilla adds
its own signing files after the unsigned package is submitted.

To update a permanent installation, submit version 1.0.7 under the **existing**
Mozilla add-on ID, obtain the signed XPI, then install that signed file through
`about:addons` in the existing dedicated profile. Approve the additional Cloudflare
host/data permissions and refresh the dashboard. Building here neither uploads
nor signs anything. The existing 1.0.6 signed package lacks the guard and is not
compatible with the protected dashboard. Temporary unsigned installation through
`about:debugging` ends when Firefox closes; it is only a development test.

## Scope and data handling

This add-on connects Google Maps to a separate local dashboard. It handles the
selected business, displayed account email and the user's own review draft.
Submission requires the user's explicit Post click. There is no bulk posting,
IP rotation, fingerprint alteration, VPN control, or device-location spoofing.
Passwords, OTPs and Google cookies are not read or exported by the add-on.

The extension checks outbound country through two fixed Cloudflare HTTPS endpoints
before protected actions; this is not a VPN controller or continuous leak detector.
See `EXTENSION_PRIVACY.md` for those checks, local data exchange and Google
transmissions. The local dashboard and browser profile are separate from this
extension package and are not needed to reproduce its build. This source archive
intentionally excludes user accounts, environment secrets, cookies and review history.
