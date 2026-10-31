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

## Build transformations

The original extension files are in `chrome_extension/`. The Python script:

1. Changes the background service worker manifest entry to Firefox background scripts.
2. Adds the Firefox ID, minimum version and data-handling declarations.
3. Replaces `chrome.` API namespace references with Firefox's promise-based `browser.` references.
4. Copies the readable HTML/CSS without preprocessing and packages the privacy document.

The code is not minified, obfuscated or bundled. No third-party JavaScript libraries
are included. Compare extracted XPI file names and contents, not the complete ZIP
binary, because ZIP timestamps can vary between build runs. Mozilla adds its own
signing files after the unsigned package is submitted.

## Scope and data handling

This add-on connects Google Maps to a separate local dashboard. It handles the
selected business, displayed account email and the user's own review draft.
Submission requires the user's explicit Post click. There is no bulk posting,
IP rotation, fingerprint alteration, VPN control, or device-location spoofing.
Passwords, OTPs and Google cookies are not read or exported by the add-on.

See `EXTENSION_PRIVACY.md` for local data exchange and user-requested Google
transmissions. The local dashboard and browser profile are separate from this
extension package and are not needed to reproduce its build. This source archive
intentionally excludes user accounts, environment secrets, cookies and review history.
