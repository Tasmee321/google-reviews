# Tasmee Personal Reviews — data handling

The add-on handles the Google account email shown on Maps, the selected business
URL/name/address, your business search, your exact review text and star rating,
and the actions needed to prepare and verify your own review. These are exchanged
with the local dashboard at localhost/127.0.0.1. The dashboard saves local history
in personal_data/reviews.sqlite3. Business location is not device geolocation.

Open Google sign-in transmits your entered email to Google. Business searches
and URLs are opened on Google Maps. Preparing a review fills Google's form;
Google may process entered form content. Post requires your explicit dashboard
click and sends the review through Google's normal signed-in Maps page.

No passwords, OTPs, recovery codes, or Google cookies are read or exported by
this add-on. It does not copy the session from another browser. Firefox itself
keeps login state in the dedicated local profile. There is no developer-owned
collection endpoint, advertising, analytics or background review posting.

Google independently handles its services under https://policies.google.com/privacy.
Reviews can identify your Google Maps profile; VPN use does not anonymize that
profile. Neither this add-on nor the dashboard verifies VPN protection, rotates
IPs, changes browser fingerprints, or spoofs your device location.

Version 1.0.6 can select an already signed-in Google account and perform
read-only saved-review checks in temporary background Maps tabs while the
dashboard is open, idle and monitoring is enabled. Checks do not post reviews;
matching an own-review card does not establish public visibility. Review IDs,
last check times and verification outcomes are stored with local history.

The dashboard keeps verified email shortcuts (not login credentials). Deleting
local history removes its text, email and detailed events, while minimal
business name/address, submission status/time and keyed account-hash receipts
remain for counts and accidental-duplicate protection. Account shortcuts and
Firefox's session are separate: removing a shortcut does not sign out Google.
Existing backups are not altered by a history deletion. The app does not claim
forensic erasure or local database encryption.

The optional browser IPv4-check link opens api.ipify.org only when clicked;
that external service observes the connecting IP. It does not verify DNS,
IPv6, per-process VPN routing, or leak protection.

Firefox's data-consent declarations cover local dashboard data exchange as well
as user-requested Google interactions. Installation does not authorize a review
to be posted. Do not install if you do not agree to these data-handling operations.
