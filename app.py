# app.py
"""Local dashboard for your own Google Maps reviews."""
import atexit
import json
import os
import secrets
import io
import zipfile
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, session, send_file

from review_store import ReviewStore, ReviewError, validate_review, valid_email, maps_url
from browser_bridge import BrowserBridge, open_normal_chrome
from personal_browser import browser_kind, open_firefox_dashboard
from build_firefox_extension import firefox_archive
from review_policy import review_warnings, POLICY_URL, QUALITY_URL, APPEAL_URL

ROOT = Path(__file__).resolve().parent


def load_config():
    """Load config.json from the project root. Returns an empty dict if absent."""
    config_path = ROOT / "config.json"
    if config_path.is_file():
        try:
            with config_path.open(encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def acquire_runtime_lock(directory):
    """Prevent a second process from invalidating an active browser's review state."""
    directory.mkdir(parents=True, exist_ok=True)
    handle = (directory / "session.lock").open("a+b")
    if handle.seek(0, 2) == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        handle.close()
        raise RuntimeError("This tool is already running. Use its existing dashboard window.") from error
    return handle


def create_app(data_dir=None, worker_factory=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=secrets.token_hex(32), MAX_CONTENT_LENGTH=24000,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
        TRUSTED_HOSTS=["localhost", "127.0.0.1"],
    )
    cfg = load_config()
    store = ReviewStore(Path(data_dir) if data_dir else ROOT / "personal_data")
    store.recover()

    if worker_factory is None:
        # Default: use BrowserBridge (extension mode). To use the Playwright-based
        # ReviewWorker from poster.py instead, pass:
        #   worker_factory=lambda s: ReviewWorker(s, cfg)
        worker = BrowserBridge(store)
    else:
        worker = worker_factory(store, cfg)

    app.extensions.update(review_store=store, review_worker=worker)
    atexit.register(worker.close)

    @app.before_request
    def protect_local_api():
        if request.remote_addr not in {"127.0.0.1", "::1"}:
            return jsonify(ok=False, message="This tool is only available on this computer."), 403
        if request.method == "POST":
            token = session.get("csrf")
            supplied = request.headers.get("X-CSRF-Token", "")
            origin = request.headers.get("Origin")
            if origin and urlsplit(origin).netloc != request.host:
                return jsonify(ok=False, message="Invalid request origin."), 403
            if not token or not secrets.compare_digest(token, supplied):
                return jsonify(ok=False, message="Refresh this page before trying again."), 403
            if not request.is_json:
                return jsonify(ok=False, message="Expected a JSON request."), 415

    @app.after_request
    def security_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        return response

    @app.errorhandler(ReviewError)
    def review_error(error):
        return jsonify(ok=False, message=str(error), fields=error.fields), error.status

    @app.errorhandler(413)
    def too_large(error):
        return jsonify(ok=False, message="The request is too large."), 413

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ReviewError("Expected a JSON object.")
        return data

    @app.get("/")
    def index():
        session.setdefault("csrf", secrets.token_urlsafe(32))
        kind = getattr(worker, "browser_kind", "chrome")
        return render_template("index.html", csrf=session["csrf"], browser_kind=kind,
                               policy_url=POLICY_URL, quality_url=QUALITY_URL, appeal_url=APPEAL_URL,
                               extension_path=str(ROOT / ("firefox_extension" if kind == "firefox" else "chrome_extension")))

    @app.get("/api/status")
    def status():
        return jsonify(ok=True, browser=worker.snapshot(), reviews=store.list_reviews(),
                       history_total=store.count(), businesses=store.business_statistics(),
                       accounts=store.accounts())

    @app.get("/api/history")
    def history():
        try:
            offset = int(request.args.get("offset", "0"))
        except ValueError:
            raise ReviewError("Invalid history offset.")
        if not 0 <= offset <= 100000:
            raise ReviewError("Invalid history offset.")
        return jsonify(ok=True, reviews=store.list_reviews(offset), total=store.count())

    @app.get("/api/reviews/<review_id>")
    def review_details(review_id):
        return jsonify(ok=True, review=store.get(review_id))

    @app.get("/api/check-candidate")
    def check_candidate():
        state = worker.snapshot()
        review = store.check_candidate(state["email"]) if state["status"] == "connected" and not state["busy"] and not store.active() else None
        return jsonify(ok=True, review=review)

    def deletion_allowed():
        if body().get("confirm_local_delete") is not True:
            raise ReviewError("Confirm deletion of local history first.")
        if worker.snapshot()["busy"]:
            raise ReviewError("Wait for the browser to finish before deleting history.", 409)

    @app.post("/api/history/clear")
    def clear_history():
        deletion_allowed()
        count = store.delete_history()
        return jsonify(ok=True, deleted=count, message="Local history deleted. Google reviews were not deleted; minimal count and duplicate-protection receipts remain.")

    @app.post("/api/reviews/<review_id>/delete")
    def delete_history_entry(review_id):
        deletion_allowed()
        store.delete_history(review_id)
        return jsonify(ok=True, message="Local entry deleted. Any Google review is unchanged; a minimal submission receipt may remain.")

    @app.post("/api/browser/select")
    def select_account():
        email = body().get("email", "")
        if not valid_email(email) or email.lower() not in {account["email"] for account in store.accounts()}:
            raise ReviewError("Connect and verify this Google account first.")
        if store.active():
            raise ReviewError("Finish or cancel the current review before switching accounts.", 409)
        worker.command("select", email.lower())
        return jsonify(ok=True)

    @app.post("/api/account-shortcuts/forget")
    def forget_account():
        email = body().get("email", "")
        if not valid_email(email):
            raise ReviewError("Invalid account email.")
        if store.active() or worker.snapshot()["busy"]:
            raise ReviewError("Finish the current action first.", 409)
        store.forget_account(email.strip().lower())
        return jsonify(ok=True, message="Shortcut removed. This does not sign out Google or delete review history.")

    @app.get("/extension/download")
    def extension_download():
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
            for filename in ("manifest.json", "background.js", "dashboard.js", "google.js", "review_widget.js", "popup.html", "popup.css"):
                path = ROOT / "chrome_extension" / filename
                if path.is_file():
                    output.write(path, "tasmee-chrome-extension/" + path.name)
        archive.seek(0)
        return send_file(archive, mimetype="application/zip", as_attachment=True, download_name="tasmee-chrome-extension.zip")

    @app.post("/api/browser/login")
    def login():
        email = body().get("email", "")
        if not valid_email(email):
            raise ReviewError("Enter your Google account email.", fields={"email": "Enter a valid email address."})
        if store.active():
            raise ReviewError("Finish or cancel the current review first.", 409)
        worker.command("login", email.strip().lower())
        return jsonify(ok=True, requires_extension=getattr(worker, "browser_kind", "chrome") == "firefox",
                       message="Complete Google sign-in and 2FA in the browser window."), 202

    @app.get("/extension/firefox/download")
    def firefox_download():
        return send_file(firefox_archive(), mimetype="application/x-xpinstall", as_attachment=True,
                         download_name="tasmee-firefox-unsigned.xpi")

    @app.post("/api/browser/check")
    def check_login():
        body()
        if store.active():
            raise ReviewError("Finish or cancel the current review first.", 409)
        worker.command("check")
        return jsonify(ok=True, requires_extension=getattr(worker, "extension_mode", False)), 202

    @app.post("/api/browser/verified")
    def verified_browser():
        if not getattr(worker, "extension_mode", False):
            raise ReviewError("This connection method is unavailable.", 409)
        worker.connect(body())
        return jsonify(ok=True)

    @app.post("/api/reviews/preflight")
    def review_preflight():
        text = body().get("text")
        if not isinstance(text, str) or len(text) > 4000:
            raise ReviewError("Review text must be a string of at most 4,000 characters.",
                              fields={"text": "Enter at most 4,000 characters."})
        return jsonify(ok=True, warnings=review_warnings(text, store.has_matching_text(text)),
                       message="Local advisory checks only. No warnings does not mean Google approved the review.")

    @app.post("/api/reviews")
    def prepare():
        values = validate_review(body())
        browser = worker.snapshot()
        if browser["busy"] or browser["status"] != "connected":
            raise ReviewError("Connect your Google account first.", 409)
        if browser["email"].lower() != values["account_email"]:
            raise ReviewError("The connected account does not match this review's email.", 409)
        review = store.create(values)
        try:
            worker.command("prepare", review["id"])
        except ReviewError:
            store.update(review["id"], status="failed", message="Browser is busy. Prepare the review again.")
            raise
        return jsonify(ok=True, review=store.get(review["id"]), requires_extension=getattr(worker, "extension_mode", False)), 202

    @app.post("/api/business/resolve")
    def resolve_business():
        target = body().get("target", "")
        if not isinstance(target, str) or not target.strip() or len(target) > 2048:
            raise ReviewError("Enter a Google Maps business link.", fields={"target": "Enter a Google Maps link or business search."})
        browser = worker.snapshot()
        if store.active() or browser["busy"] or browser["status"] != "connected":
            raise ReviewError("Connect Google and finish the current review first.", 409)
        if not getattr(worker, "extension_mode", False):
            raise ReviewError("Auto-fetch needs the Tasmee browser extension.", 409)
        try:
            url = maps_url(target.strip())
        except (ValueError, ReviewError) as error:
            raise ReviewError("Check the business link.", fields={"target": str(error)}) from error
        return jsonify(ok=True, navigation_url=url, account_email=browser["email"])

    @app.post("/api/reviews/<review_id>/publish")
    def publish(review_id):
        token = body().get("confirmation_token", "")
        review = store.get(review_id)
        if not isinstance(token, str) or not secrets.compare_digest(review["confirmation_token"], token):
            raise ReviewError("Confirmation expired. Prepare the review again.", 409)
        if worker.snapshot()["busy"]:
            raise ReviewError("The browser is busy.", 409)
        store.transition(review_id, "ready", "publishing", "Rechecking the account, business, text and rating.")
        try:
            worker.command("publish", review_id)
        except ReviewError:
            store.update(review_id, status="failed", message="Posting did not start. Prepare the review again.")
            raise
        return jsonify(ok=True, requires_extension=getattr(worker, "extension_mode", False), review=store.get(review_id)), 202

    def extension_review(review_id):
        if not getattr(worker, "extension_mode", False):
            raise ReviewError("Extension transport is unavailable.", 409)
        data = body()
        review = store.get(review_id)
        token = data.get("confirmation_token", "")
        if not isinstance(token, str) or not secrets.compare_digest(token, review["confirmation_token"]):
            raise ReviewError("Invalid review confirmation.", 409)
        return data, review

    def extension_callback(handler):
        @wraps(handler)
        def guarded(review_id):
            if not getattr(worker, "extension_mode", False):
                raise ReviewError("Extension transport is unavailable.", 409)
            with worker.review_action(review_id):
                return handler(review_id)
        return guarded

    @app.post("/api/reviews/<review_id>/prepared")
    @extension_callback
    def prepared(review_id):
        data, review = extension_review(review_id)
        if review["status"] != "preparing":
            raise ReviewError("This review is no longer preparing.", 409)
        details = worker.validate_assertion(review_id, data.get("assertion", {}))
        store.update(review_id, **details)
        store.transition(review_id, "preparing", "ready", "The browser verified the business, account, exact text and rating. Ready for your confirmation.")
        worker.finish(review_id)
        return jsonify(ok=True)

    @app.post("/api/reviews/<review_id>/submitting")
    @extension_callback
    def submitting(review_id):
        data, review = extension_review(review_id)
        if review["status"] != "publishing":
            raise ReviewError("This review is no longer waiting for submission.", 409)
        worker.validate_assertion(review_id, data.get("assertion", {}))
        store.transition(review_id, "publishing", "submitting", "Submitting once in your verified browser session.")
        worker.renew_operation(review_id)
        return jsonify(ok=True)

    @app.post("/api/reviews/<review_id>/result")
    @extension_callback
    def submission_result(review_id):
        data, review = extension_review(review_id)
        if review["status"] != "submitting":
            raise ReviewError("This review is not waiting for a result.", 409)
        confirmed = data.get("confirmed") is True
        store.transition(review_id, "submitting", "posted" if confirmed else "unconfirmed",
                         "Google explicitly confirmed submission. Google may still moderate public visibility."
                         if confirmed else "Google did not show a clear confirmation. Check your contributions before posting again.")
        worker.finish(review_id)
        return jsonify(ok=True)

    @app.post("/api/reviews/<review_id>/failure")
    @extension_callback
    def extension_failure(review_id):
        data, review = extension_review(review_id)
        if review["status"] not in {"preparing", "publishing", "submitting"}:
            raise ReviewError("This review has already changed state.", 409)
        message = data.get("message", "Browser action did not finish.")
        if not isinstance(message, str):
            message = "Browser action did not finish."
        uncertain = review["status"] == "submitting"
        store.transition(review_id, review["status"], "unconfirmed" if uncertain else "failed",
                         "Submission may have reached Google. Check contributions before trying again." if uncertain else message[:600])
        worker.finish(review_id)
        return jsonify(ok=True)

    @app.post("/api/reviews/<review_id>/reconcile")
    def reconcile_review(review_id):
        data, review = extension_review(review_id)
        if review["status"] != "unconfirmed" or store.active() or worker.snapshot()["busy"]:
            raise ReviewError("Only an uncertain review can be checked when the browser is idle.", 409)
        assertion = data.get("assertion", {})
        if not isinstance(assertion, dict) or not isinstance(assertion.get("saved_review_id"), str) or not assertion["saved_review_id"].strip():
            raise ReviewError("Google did not expose a matching saved review.", 409)
        worker.validate_assertion(review_id, assertion)
        store.record_saved_check(review_id, True,
                         "Success: Google Maps shows your saved review with matching account, business, text and rating. Public visibility is not independently verified.", assertion["saved_review_id"][:500])
        return jsonify(ok=True)

    @app.post("/api/reviews/<review_id>/check-start")
    def start_saved_check(review_id):
        data, review = extension_review(review_id)
        if review["status"] not in {"posted", "unconfirmed"} or not review["business_url"]:
            raise ReviewError("Only saved or uncertain submissions can be checked.", 409)
        if review["checked_at"]:
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(review["checked_at"])).total_seconds()
            if elapsed < 60:
                raise ReviewError("Wait a minute before checking this review again.", 429)
        if not hasattr(worker, "reserve_check"):
            raise ReviewError("This browser does not support background saved-review checks.", 409)
        token = worker.reserve_check(review_id)
        try:
            if data.get("automatic") is True:
                store.claim_auto_check(review_id)
        except ReviewError:
            worker.release_check(review_id, token)
            raise
        return jsonify(ok=True, verification_token=token, review=review)

    @app.post("/api/reviews/<review_id>/check-result")
    def saved_check_result(review_id):
        data, review = extension_review(review_id)
        with worker.saved_check_result(review_id, data.get("verification_token")):
            matched = data.get("matched") is True
            if matched:
                assertion = data.get("assertion", {})
                saved_id = assertion.get("saved_review_id") if isinstance(assertion, dict) else None
                if not isinstance(saved_id, str) or not saved_id.strip() or len(saved_id) > 500:
                    raise ReviewError("A matching saved review ID is required.", 409)
                worker.validate_assertion(review_id, assertion)
                store.record_saved_check(review_id, True,
                    "Saved review verified against account, business, exact text and rating. Public visibility remains unknown.", saved_id)
            else:
                store.record_saved_check(review_id, False,
                    "The saved review could not be verified. It may be hidden, changed or the page may not have loaded. This is not proof of deletion; no repost was attempted.")
        return jsonify(ok=True, review=store.get(review_id))

    @app.post("/api/reviews/<review_id>/cancel")
    def cancel(review_id):
        body()
        review = store.get(review_id)
        if getattr(worker, "extension_mode", False):
            worker.cancel(review_id)
        elif review["status"] == "ready":
            if worker.snapshot()["busy"]:
                raise ReviewError("The browser is busy.", 409)
            store.transition(review_id, "ready", "cancelled", "Review cancelled. Nothing was submitted.")
            worker.command("discard", review_id)
        elif review["status"] in {"queued", "preparing"}:
            worker.cancel(review_id)
        else:
            raise ReviewError("This review cannot be cancelled at its current stage.", 409)
        return jsonify(ok=True)

    return app


if __name__ == "__main__":
    load_dotenv(ROOT / ".env")
    port = int(os.getenv("PORT", "5000"))
    try:
        runtime_lock = acquire_runtime_lock(ROOT / "personal_data")
    except RuntimeError as error:
        raise SystemExit(str(error))
    dashboard = create_app()
    print(f"Personal review dashboard: http://127.0.0.1:{port}", flush=True)
    import threading
    def open_dashboard():
        try:
            opener = open_firefox_dashboard if browser_kind() == "firefox" else open_normal_chrome
            opener(f"http://127.0.0.1:{port}/")
        except ReviewError as error:
            print(str(error), flush=True)
    if os.getenv("REVIEW_OPEN_BROWSER", "1") != "0":
        opening = threading.Timer(1, open_dashboard)
        opening.daemon = True
        opening.start()
    dashboard.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)
