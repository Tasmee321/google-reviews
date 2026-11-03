# Tasmee Personal Reviews

A local Windows tool for writing your own review of a business you visited. You choose the business, exact review text and a rating from 1 to 5. Click **Start** to auto-fetch the business name/location and prepare Google's review form. Detailed preview is optional; submission still happens once after **Post this review**.

## Install and start

Double-click **start_localhost.bat** in the project folder for the convenient
local launcher. It starts the local server and dedicated Firefox when stopped.
If the dashboard is already running, it reuses the server and tells you to use
the existing Firefox dashboard tab instead of starting a duplicate. Keep the
server terminal open; Ctrl+C stops it. This is not Windows startup registration
and it does not connect, disconnect, or change Avast VPN settings.

### New recommended privacy setup: dedicated Firefox

`run.bat` now calls `run_firefox.bat`. It launches ordinary Firefox with the same
isolated `personal_data/firefox-profile` directory each time. It does not use
personal Chrome, import its cookies, clear the Firefox profile, enable remote
debugging, spoof fingerprints/location, or rotate IPs. The Chrome implementation
remains available explicitly through `run_chrome.bat`.

1. Install ordinary Firefox. Use your existing paid Avast VPN; no new purchase is needed.
2. In Avast VPN, select **Menu → Settings → VPN mode → Always on**, keep the VPN
   connected, and enable its **Kill Switch**. Do not exclude Firefox or Google
   traffic from the VPN using split tunneling. Configure these privacy settings
   yourself. Do not disable 2FA or certificate checks. Do not run Proton or a
   second VPN simultaneously. Avast's official guidance is at
   https://support.avast.com/en-gb/article/use-secureline-vpn/ and
   https://support.avast.com/en-gb/article/63/.
3. Double-click `run.bat`. If the dedicated Firefox profile is already open,
   use its existing dashboard tab; close that dedicated window before relaunching.
4. Check **about:addons** in that profile. If signed Tasmee 1.0.6 is already
   installed and active, keep it and refresh the dashboard. Otherwise install
   a Mozilla-signed XPI through **Install Add-on From File**.
5. Complete Google sign-in yourself in this same Firefox profile. Later runs can
   reuse its cookies; Google may still require fresh verification.

The Firefox build is **unsigned**. Normal Firefox requires Mozilla signing for
permanent add-on installation. Temporary installation ends when Firefox closes;
the underlying profile and login cookies are not deleted. Permanent installation
requires the account owner's Mozilla developer account, agreement to Mozilla's
distribution terms, signing submission and a signed XPI. The build script does
not sign or install add-ons; a previously installed signed copy is separate.
The launcher does not disable signature checks or use a developer browser to bypass them.

Rebuild after source changes with `python build_firefox_extension.py`. The build
creates `firefox_extension/` and `dist/tasmee-firefox-unsigned.xpi`. The add-on's
data handling is described in `EXTENSION_PRIVACY.md`; Firefox declarations cover
local dashboard data exchange as well as user-requested Google interactions.

The application **does not verify VPN protection**. Installing Proton is not
the same as connecting it. Use Avast's kill switch and verify your
connection before accessing Google. A VPN does not anonymize a signed-in Google
account, promise unique/location-matched IPs, prevent all login challenges, or
guarantee public review visibility. Rotating IPs and fresh profiles are not used.
No additional VPN or proxy purchase is required. Proton was installed during the
initial trial preparation, but is not used by the application and is not launched.

### Existing optional Chrome mode

1. Install Python 3.11+ and Google Chrome. Select **Add Python to PATH**.
2. Double-click **install.bat** once.
3. Double-click **run_chrome.bat** only for legacy Chrome mode. The dashboard opens at http://127.0.0.1:5000.
4. Keep the terminal open. Stop it with Ctrl+C after using the tool.

Commands, if you prefer:
```powershell
python -m pip install -r requirements.txt
$env:REVIEW_BROWSER='firefox'
python build_firefox_extension.py
python app.py
```

## Google sign-in and 2FA — optional Chrome mode

This section is only for `run_chrome.bat`. The recommended `run.bat` uses your
dedicated Firefox profile. Neither extension workflow uses Playwright for Google sign-in.

One-time extension setup:
1. Open **chrome://extensions** in normal Chrome.
2. Enable **Developer mode**, choose **Load unpacked**, and select the project's **chrome_extension** folder.
3. Refresh the dashboard in this same Chrome browser. It should say **Chrome extension connected**.

The folder path and an optional extension ZIP download are shown in the dashboard. Unzip the download before selecting its folder. The extension is local source code; it is not a Chrome Web Store installation.

1. Enter your Google email in the dashboard.
2. Click **Open Google sign-in**.
3. Enter your password and complete the verification Google requests in Google's browser window.
4. Return to the dashboard and click **Check connection**.
5. On later runs, **Check connection** can reuse Chrome's own saved session.

Passwords, app passwords, TOTP secrets and recovery codes are not requested or stored by this application. The extension does not read or export Google cookies. A Google app password does not replace interactive browser sign-in. Google may still request verification; complete it in Google's own browser page.

If you see **This browser or app may not be secure**, close the old tool-controlled Google window and use normal Chrome. The new sign-in button opens Chrome without a debugger, a replacement user profile or fingerprint modifications. Google still controls which sign-ins it accepts; authentication has not been verified on your actual account by these tests.

## Write and post a review

1. Paste the business's HTTPS Google Maps share link, or enter a search including its name and city.
2. Select your rating and write your own review. You do not need to type the business name.
3. Click **Start**. The business name/address are fetched from Google's selected place; stars and exact text are automatically prepared. Nothing is posted yet.
4. **View details / preview · optional** can be expanded to inspect branch, location, account, rating and text. The final Post button is available without opening it.
5. Click **Post this review** to submit once after revalidation.

You can also click **Start** with only a business link to fetch its name/location first. No review job is created until you supply stars and text. Ambiguous search results stop instead of selecting a random branch.

Refresh clears the composer URL, name, stars, text, notices and terminal preview. History remains available; select a history row to view it again. An active review remains visible/locked so refresh never cancels it or authorizes another submission.

A name mismatch or ambiguous result stops the flow. A name alone cannot distinguish branches: inspect the resolved Google Maps link in the preview. Ratings and text must have verifiable states in Google's form. If Google changes its markup or does not expose a verifiable rating, the app stops and asks you to finish in Google Maps rather than guessing.

### Business location in the preview

The preview reads the selected business's address from the resolved Google Maps page, including when your original link was a short share link. When the resolved URL contains a single explicit place-coordinate pair, those coordinates are shown too. Maps' camera center (`@latitude,longitude`) is not treated as the business's coordinates. Missing or ambiguous location details are shown as unavailable rather than guessed. Existing local histories are preserved during the database upgrade.

After updating, finish or cancel any active preview, restart the local app, reload **Tasmee Personal Reviews** on **chrome://extensions**, and refresh the dashboard. Prepare a new preview to capture location details; older history entries do not have an address until a new preview is prepared.

This displays the **business's** location; it does not change your IP, device location, browser fingerprint or Google account. No Camoufox or proxy rotation has been added. Posting still requires your confirmation. **Success** means Google displayed a submission confirmation or a matching saved **Your review** card, not that a publicly visible review was independently verified. Open the business link to check visibility; Google controls moderation and publication.

### Google's iframe review form

Extension version **1.0.4** supports Google's embedded review widget as well as the older inline dialog. The extension waits for the signed-in account, verifies the business, fills your exact text, and selects only the **overall Rating stars** group. Food, Service and Atmosphere ratings are not changed. Once the values are verified, the Maps tab stays open and the dashboard shows **Post this review**. Clicking it rechecks the account, business, text and rating before a single submission. Preparing a preview never posts a review.

After an extension update, reload the installed extension and refresh the dashboard before preparing a new preview. Do not close/reload the prepared Maps tab or change its account while preparing or posting: this can interrupt the extension's response. Closing the form alone is never success. After a single Post, either an explicit Google confirmation or a saved **Your review** card must be detected. The saved card requires exact text, overall rating, an edit-own-review control, and revalidated account/business. Submission is never retried automatically.

For older **Check Google Maps** records, use **Verify saved review**. This opens the saved business read-only and verifies the matching own-review card before changing the status to Success; it never posts again. Public visibility in another account remains unverified.

## Status meanings

| Status | Meaning |
| --- | --- |
| Preparing | The business, account and form are being checked. |
| Ready to post | The exact text and rating were verified; no submission yet. |
| Success | Google confirmed submission or shows the matching saved own review. Public visibility is not independently verified. |
| Check Google Maps | Submission may have reached Google, but no clear confirmation was seen. Check your contributions before posting again. |
| Needs attention | The workflow stopped; inspect the message. |
| Interrupted | The app restarted before submission; prepare a new draft. |

There are no automatic submission retries. Repeated clicks cannot submit the same job twice. A locally recorded confirmed or unconfirmed review blocks another job for the same Google account and resolved business. Reviews made outside this tool are not imported into its history.

## Storage and configuration

- `personal_data/reviews.sqlite3`: local history and drafts.
- In the recommended Firefox mode, Google session state stays in
  `personal_data/firefox-profile/`. Optional Chrome mode uses your normal Chrome
  profile. The older `personal_data/browser/` folder is not used by the default launcher.
- The composer is not persisted in browser storage. Refresh clears stale fields/preview while keeping history and active-job state.
- Google credentials from the old `accounts.json` are not used.
- Old `accounts.json`, `targets.json`, `env` and `.env` are preserved. Remove legacy secrets yourself if you no longer need them.
- Original application files are saved in `backups/before-personal-review-update/`.

Optional settings in `.env`:
```dotenv
PORT=5000
```
Use `run.bat` for dedicated Firefox. If starting `python app.py` directly, set
`REVIEW_BROWSER=firefox`; without that setting the legacy default is Chrome.
`BROWSER_CHANNEL` belongs to the older controlled-browser engine and is not used
by the extension flow. For isolated browser tests, install test Chromium with
`python -m playwright install chromium` when needed.

Old bulk-posting settings such as proxies, headless mode, daily limits and review spinners are no longer used. The application binds to 127.0.0.1 and accepts only requests from this computer. Cloud/Render deployment is not supported because sign-in needs a visible local browser.

## Verification

```powershell
python -m unittest discover -s tests -v
```
Unit tests cover input validation, state transitions, concurrency, duplicate protection and local request security. Browser tests exercise the actual Chrome extension in test Chromium against intercepted Google fixtures; they do not log in to Google or publish real reviews. A real Google sign-in and submission still need to be checked by the account owner. English Google Maps form labels are currently supported; if the form cannot be verified, the tool stops instead of guessing.

New Firefox setup checks (no live browser/sign-in/VPN changes):
```powershell
python -m unittest discover -s tests -p test_firefox_setup.py -v
python build_firefox_extension.py
node tests/test_extension_transport.js
```
These test the generated manifest, promise namespace, persistent-profile launch,
browser-kind isolation, narrow API permissions and transport validation. They do
not verify a live Firefox/Google sign-in or public review visibility.

## History/account/monitor update — extension 1.0.6

Default launcher is `run.bat` -> dedicated ordinary Firefox. Existing signed
`dist/tasmee-firefox-1.0.5.xpi` is preserved. Dashboard-only history, address
counts, confirmation dialog and success-only form reset work with 1.0.5.
Background saved-review checks and direct account selection need version 1.0.6.
If signed 1.0.6 is already active in about:addons, no reinstall is needed.
Only when building a new extension release, submit its unsigned XPI and source
to Mozilla using the same add-on ID and private distribution. For version 1.0.6,
these files are `dist/tasmee-firefox-1.0.6-unsigned.xpi` and
`dist/tasmee-firefox-1.0.6-source.zip`. Install the resulting signed XPI through about:addons.
Never disable Firefox signing or replace the permanent add-on with an unsigned
temporary installation. Signing/manual review completion is not assumed.

- Success clears only the composer for the submitted job. Pending/uncertain
  results preserve text; selecting or verifying an old entry does not clear an
  unrelated draft. Refresh clears stale composer fields.
- History selection automatically opens account, address, stars, exact text,
  timestamps and activity. Search/filter apply to loaded history; load older
  pages to inspect additional entries.
- Deletion is LOCAL only and requires confirmation. Active jobs cannot be
  deleted. Text/email/events are removed from the history row; minimal keyed
  account-hash/business/status/time receipts remain for counts and duplicate
  protection. Existing backups, Google reviews and browser sessions are not
  erased. SQLite is not encrypted and forensic erasure is not guaranteed.
- Counts reflect locally tracked submitted/uncertain jobs, including receipts,
  not publicly visible reviews. Failed drafts are excluded.
- Verified account shortcuts persist locally. Add an account via normal Google
  sign-in and Check connection. Select a shortcut and Switch account. Google
  may require manual account selection/login; exact email matching is always
  required before preparation/posting. Verified numeric Google account indices
  are reused where available; a missing/mismatched account stops the action.
  No passwords, cookies or OTPs are imported or automated. Shortcuts are not
  simultaneous active connections or separate Firefox profiles.
- Read-only monitoring runs only while the dashboard is open/visible, idle and
  connected, including older history. One automatic check per 10 minutes
  globally, no more than once per review every 6 hours; failures back off 30
  minutes. Manual checks have a 1-minute cooldown. It never posts/reposts or
  rotates accounts. A matching OWN review verifies saved status only; public
  visibility remains Unknown. A failed check is NOT proof of deletion/rejection.
  Closed browser/server means no monitoring. Pause checkbox choice persists.
- Checks reserve the browser for at most 120 seconds. Account switching,
  posting and deletion are blocked during the reservation; interrupted checks
  expire instead of leaving the browser permanently busy.

## VPN and review visibility

Avast split tunneling excludes executables, not a single Firefox profile. Keep
Firefox out of exclusions. Exclude only other apps whose direct routing you
intend. OS route inspection alone does not prove per-app IP/DNS/IPv6 protection.
The optional IPv4-check link contacts an external service only when clicked.
Signing into Google identifies the account even with a VPN. IP changes do not
guarantee publication or prevent removal after 5–7 days.

Google genuine-experience/manipulation policy:
https://support.google.com/contributionpolicy/answer/7400114?hl=en
Use authentic reviews of your own experience; do not use multiple accounts to
inflate ratings or duplicate reviews. Delayed moderation may change visibility;
this application cannot determine the exact removal reason. Owner/public
visibility distinction:
https://support.google.com/contributionpolicy/answer/13780397?hl=en
For a genuine removed review, check account notices and the available appeal
process rather than automatically reposting.

`REVIEW_OPEN_BROWSER=0` starts the server without opening a browser window for
maintenance. Ordinary launchers still open the dedicated Firefox profile.
