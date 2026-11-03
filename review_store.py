"""Validation and transactional review history."""
import json
import hashlib
import hmac
import re
import secrets
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit

ACTIVE = ("queued", "preparing", "ready", "publishing", "submitting")
MAP_HOSTS = {"google.com", "www.google.com", "maps.google.com", "maps.app.goo.gl", "goo.gl",
             "google.co.uk", "www.google.co.uk", "google.com.pk", "www.google.com.pk"}


class ReviewError(Exception):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status = status
        self.fields = fields or {}


def now():
    return datetime.now(timezone.utc).isoformat()


def normalize_name(value):
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def valid_email(value):
    return isinstance(value, str) and len(value) <= 254 and bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value.strip()))


def maps_url(target):
    if not isinstance(target, str):
        raise ReviewError("Enter a Google Maps link or business search.")
    try:
        parsed = urlsplit(target)
        port = parsed.port
    except ValueError as error:
        raise ReviewError("The Google Maps link is malformed. Check its address and port.") from error
    if parsed.scheme or target.startswith("//") or re.match(r"^(www\.|maps\.|google\.)", target, re.I):
        host = (parsed.hostname or "").lower()
        if (parsed.scheme != "https" or host not in MAP_HOSTS or parsed.username or parsed.password
                or port not in (None, 443)):
            raise ReviewError("Use a complete HTTPS Google Maps link, or enter a business search.")
        if host == "goo.gl" and not parsed.path.startswith("/maps/"):
            raise ReviewError("Only Google Maps links are supported.")
        if host not in {"maps.app.goo.gl", "goo.gl", "maps.google.com"} and not parsed.path.startswith("/maps"):
            raise ReviewError("This link is not a Google Maps business link.")
        return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, ""))
    return "https://www.google.com/maps/search/?api=1&query=" + quote(target, safe="")


def validate_review(data):
    if not isinstance(data, dict):
        raise ReviewError("Expected a JSON object.")
    fields, values = {}, {}
    for key, label, maximum in (("target", "Business link or search", 2048),
                                ("expected_name", "Business name", 200),
                                ("text", "Review text", 4000),
                                ("account_email", "Google account email", 254)):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            fields[key] = f"{label} is required and must be at most {maximum} characters."
        else:
            values[key] = value.strip()
    stars = data.get("stars")
    if isinstance(stars, bool) or not isinstance(stars, int) or not 1 <= stars <= 5:
        fields["stars"] = "Choose a whole-number rating from 1 to 5 stars."
    if "account_email" in values and not valid_email(values["account_email"]):
        fields["account_email"] = "Enter a valid Google account email."
    if fields:
        raise ReviewError("Please check the highlighted fields.", fields=fields)
    try:
        values["navigation_url"] = maps_url(values["target"])
    except (ValueError, ReviewError) as error:
        raise ReviewError("Check the business link.", fields={"target": str(error)}) from error
    values["stars"] = stars
    values["account_email"] = values["account_email"].lower()
    return values


def business_location(url, address=""):
    """Read a place marker, never mistake Maps' @ camera center for a business."""
    if not isinstance(address, str) or len(address) > 500:
        raise ReviewError("The business address could not be verified.")
    result = {"business_address": " ".join(address.split()),
              "business_latitude": None, "business_longitude": None}
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in MAP_HOSTS or not parsed.path.startswith("/maps"):
        return result
    number = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
    pairs = {(float(lat), float(lon)) for lat, lon in re.findall(
        rf"!3d({number})!4d({number})(?=!|/|$)", unquote(parsed.path))}
    if len(pairs) == 1:
        latitude, longitude = pairs.pop()
        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
            result.update(business_latitude=latitude, business_longitude=longitude)
    return result


class ReviewStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.database = self.directory / "reviews.sqlite3"
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS reviews (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                target TEXT NOT NULL, navigation_url TEXT NOT NULL, expected_name TEXT NOT NULL,
                account_email TEXT NOT NULL, stars INTEGER NOT NULL, text TEXT NOT NULL,
                status TEXT NOT NULL, message TEXT NOT NULL, business_name TEXT NOT NULL DEFAULT '',
                business_url TEXT NOT NULL DEFAULT '', business_key TEXT NOT NULL DEFAULT '',
                confirmation_token TEXT NOT NULL, events TEXT NOT NULL DEFAULT '[]')""")
            # Upgrade existing histories without replacing drafts or events.
            columns = {row["name"] for row in db.execute("PRAGMA table_info(reviews)")}
            for name, definition in (("business_address", "TEXT NOT NULL DEFAULT ''"),
                                     ("business_latitude", "REAL"), ("business_longitude", "REAL"),
                                     ("checked_at", "TEXT NOT NULL DEFAULT ''"),
                                     ("saved_status", "TEXT NOT NULL DEFAULT 'unchecked'"),
                                     ("check_message", "TEXT NOT NULL DEFAULT ''"),
                                     ("saved_review_id", "TEXT NOT NULL DEFAULT ''")):
                if name not in columns:
                    db.execute(f"ALTER TABLE reviews ADD COLUMN {name} {definition}")
            db.execute("""CREATE TABLE IF NOT EXISTS receipts (
                id TEXT PRIMARY KEY, account_hash TEXT NOT NULL, business_key TEXT NOT NULL,
                business_name TEXT NOT NULL, business_address TEXT NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL)""")
            db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('receipt_key', ?)", (secrets.token_hex(32),))
            db.execute("""CREATE TABLE IF NOT EXISTS account_shortcuts (
                email TEXT PRIMARY KEY, verified_at TEXT NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS review_duplicate ON reviews(business_key, account_email, status)")
            db.execute("CREATE INDEX IF NOT EXISTS receipt_duplicate ON receipts(business_key, account_hash)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA secure_delete=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def recover(self):
        with self.connect() as db:
            db.execute("UPDATE reviews SET status='unconfirmed', message=?, updated_at=? WHERE status='submitting'",
                       ("The app closed during submission. Check Google Maps before posting again.", now()))
            db.execute("UPDATE reviews SET status='interrupted', message=?, updated_at=? WHERE status IN ('queued','preparing','ready','publishing')",
                       ("The app restarted. Prepare a new review; no submission was resumed.", now()))

    def create(self, values):
        review_id, stamp = secrets.token_hex(12), now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(f"SELECT 1 FROM reviews WHERE status IN ({','.join('?' * len(ACTIVE))})", ACTIVE).fetchone():
                raise ReviewError("Finish or cancel the current review first.", 409)
            db.execute("""INSERT INTO reviews
                (id,created_at,updated_at,target,navigation_url,expected_name,account_email,stars,text,status,message,confirmation_token)
                VALUES (?,?,?,?,?,?,?,?,?,'queued',?,?)""",
                (review_id, stamp, stamp, values["target"], values["navigation_url"], values["expected_name"],
                 values["account_email"], values["stars"], values["text"], "Waiting for the browser.", secrets.token_urlsafe(32)))
        return self.get(review_id)

    def get(self, review_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone()
        if row is None:
            raise ReviewError("Review not found.", 404)
        result = dict(row)
        result["events"] = json.loads(result["events"])
        return result

    def active(self):
        with self.connect() as db:
            row = db.execute(f"SELECT id FROM reviews WHERE status IN ({','.join('?' * len(ACTIVE))}) LIMIT 1", ACTIVE).fetchone()
        return self.get(row["id"]) if row else None

    def list_reviews(self, offset=0):
        with self.connect() as db:
            ids = [row["id"] for row in db.execute("SELECT id FROM reviews ORDER BY created_at DESC, id DESC LIMIT 40 OFFSET ?", (offset,))]
        return [self.get(review_id) for review_id in ids]

    def count(self):
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]

    def has_matching_text(self, text):
        """Advisory only. Deleted payloads are not retained for content matching."""
        normalized = normalize_name(text)
        if not normalized:
            return False
        with self.connect() as db:
            return any(normalize_name(row["text"]) == normalized for row in db.execute(
                "SELECT text FROM reviews WHERE status IN ('posted','submitting','unconfirmed')"))

    def has_other_account_review(self, business_key, email):
        """Local advisory, including deleted-detail receipts; never return account identities."""
        if not business_key:
            return False
        with self.connect() as db:
            return bool(db.execute("SELECT 1 FROM reviews WHERE business_key=? AND account_email<>? "
                                   "AND status IN ('posted','submitting','unconfirmed') LIMIT 1",
                                   (business_key, email.strip().lower())).fetchone() or
                        db.execute("SELECT 1 FROM receipts WHERE business_key=? AND account_hash<>? LIMIT 1",
                                   (business_key, self._account_hash(db, email))).fetchone())

    def _update(self, db, review_id, values):
        if not values.keys() <= {"status", "message", "business_name", "business_url", "business_key",
                                 "business_address", "business_latitude", "business_longitude",
                                 "checked_at", "saved_status", "check_message", "saved_review_id"}:
            raise ValueError("Unexpected review update")
        row = db.execute("SELECT events FROM reviews WHERE id=?", (review_id,)).fetchone()
        if not row:
            raise ReviewError("Review not found.", 404)
        events = json.loads(row["events"])
        if "message" in values:
            events.append({"at": now(), "message": values["message"]})
        values = {**values, "updated_at": now(), "events": json.dumps(events[-40:])}
        db.execute(f"UPDATE reviews SET {','.join(key+'=?' for key in values)} WHERE id=?", (*values.values(), review_id))

    def update(self, review_id, **values):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._update(db, review_id, values)

    def transition(self, review_id, expected, status, message):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM reviews WHERE id=?", (review_id,)).fetchone()
            if not row:
                raise ReviewError("Review not found.", 404)
            if row["status"] != expected:
                raise ReviewError("The review has already changed state. Refresh the page.", 409)
            self._update(db, review_id, {"status": status, "message": message})

    def duplicate(self, review_id, key, email):
        with self.connect() as db:
            return bool(db.execute("""SELECT 1 FROM reviews WHERE id<>? AND business_key=?
                AND account_email=? AND status IN ('posted','submitting','unconfirmed') LIMIT 1""",
                (review_id, key, email.lower())).fetchone() or db.execute(
                    "SELECT 1 FROM receipts WHERE business_key=? AND account_hash=? LIMIT 1",
                    (key, self._account_hash(db, email))).fetchone())

    def _account_hash(self, db, email):
        secret = db.execute("SELECT value FROM metadata WHERE key='receipt_key'").fetchone()[0]
        return hmac.new(bytes.fromhex(secret), email.strip().lower().encode(), hashlib.sha256).hexdigest()

    def delete_history(self, review_id=None):
        """Delete local payload only; keep minimal receipts to prevent accidental reposts."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT * FROM reviews WHERE id=?", (review_id,)).fetchall() if review_id else db.execute("SELECT * FROM reviews").fetchall()
            if review_id and not rows:
                raise ReviewError("Review not found.", 404)
            if any(row["status"] in ACTIVE for row in rows):
                raise ReviewError("Finish or cancel the current review before deleting history.", 409)
            for row in rows:
                if row["status"] in {"posted", "unconfirmed"}:
                    db.execute("INSERT OR IGNORE INTO receipts VALUES (?,?,?,?,?,?,?)", (
                        row["id"], self._account_hash(db, row["account_email"]), row["business_key"],
                        row["business_name"] or row["expected_name"], row["business_address"], row["status"], row["created_at"]))
                db.execute("DELETE FROM reviews WHERE id=?", (row["id"],))
            return len(rows)

    def business_statistics(self):
        with self.connect() as db:
            rows = db.execute("""SELECT business_key, business_name, business_address, status FROM reviews
                WHERE status IN ('posted','unconfirmed') UNION ALL
                SELECT business_key, business_name, business_address, status FROM receipts""").fetchall()
        groups = {}
        for row in rows:
            key = row["business_key"] or normalize_name(row["business_name"] + "|" + row["business_address"])
            group = groups.setdefault(key, {"business_key": key, "name": row["business_name"] or "Unknown business",
                                           "address": row["business_address"], "posted": 0, "pending": 0})
            if row["business_address"]:
                group["address"] = row["business_address"]
            group["posted" if row["status"] == "posted" else "pending"] += 1
        return sorted(groups.values(), key=lambda group: (-group["posted"] - group["pending"], group["name"]))

    def remember_account(self, email):
        if not valid_email(email):
            raise ReviewError("Invalid account email.")
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO account_shortcuts VALUES (?,?)", (email.strip().lower(), now()))

    def accounts(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM account_shortcuts ORDER BY verified_at DESC")]

    def forget_account(self, email):
        with self.connect() as db:
            db.execute("DELETE FROM account_shortcuts WHERE email=?", (email,))

    def record_saved_check(self, review_id, matched, message, saved_review_id=""):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM reviews WHERE id=?", (review_id,)).fetchone()
            if not row or row["status"] not in {"posted", "unconfirmed"}:
                raise ReviewError("This review is not available for a saved-review check.", 409)
            values = {"checked_at": now(), "saved_status": "verified" if matched else "unverified",
                      "check_message": message[:600]}
            if matched:
                values.update(saved_review_id=saved_review_id, status="posted", message=message[:600])
            self._update(db, review_id, values)

    def check_candidate(self, email):
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
        recent = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        with self.connect() as db:
            row = db.execute("""SELECT id FROM reviews WHERE account_email=?
                AND status IN ('posted','unconfirmed') AND business_url<>'' AND updated_at<?
                AND (checked_at='' OR checked_at<?) ORDER BY checked_at, created_at LIMIT 1""", (email, recent, cutoff)).fetchone()
        return self.get(row["id"]) if row else None

    def claim_auto_check(self, review_id):
        stamp = datetime.now(timezone.utc)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            last = db.execute("SELECT value FROM metadata WHERE key='last_auto_check'").fetchone()
            review = db.execute("SELECT checked_at FROM reviews WHERE id=?", (review_id,)).fetchone()
            if not review:
                raise ReviewError("Review not found.", 404)
            if (last and (stamp - datetime.fromisoformat(last[0])).total_seconds() < 600
                    or review[0] and (stamp - datetime.fromisoformat(review[0])).total_seconds() < 21600):
                raise ReviewError("Automatic checks are rate limited. Wait for the next monitoring interval.", 429)
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('last_auto_check',?)", (stamp.isoformat(),))
