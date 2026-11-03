"""Private per-launch dashboard capability; localhost is not OS-user authentication."""
import math
import secrets
import time
from datetime import timedelta
from urllib.parse import urlsplit

from flask import jsonify, render_template, request, session
from werkzeug.exceptions import SecurityError

SESSION_SECONDS = 8 * 60 * 60
PUBLIC_ENDPOINTS = {"static", "unlock_dashboard", "dashboard_health"}


def install_dashboard_auth(app, clock=time.time):
    """Install before the app's existing CSRF guard; never bypass its other checks.

    Parent CSRF validation must exempt unlock_dashboard only after checking origin
    and JSON content type. The private capability, not a public CSRF token, unlocks.
    """
    if "dashboard_token" in app.extensions:
        raise RuntimeError("Dashboard authentication is already installed.")
    token, epoch = secrets.token_urlsafe(32), secrets.token_hex(16)
    app.extensions["dashboard_token"] = token
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
                      PERMANENT_SESSION_LIFETIME=timedelta(seconds=SESSION_SECONDS),
                      SESSION_REFRESH_EACH_REQUEST=False)

    def authenticated():
        identifier, issued = session.get("dashboard_session"), session.get("dashboard_unlocked_at")
        if (not isinstance(identifier, str) or not identifier.isascii()
                or not secrets.compare_digest(identifier, epoch)
                or type(issued) not in (int, float) or not math.isfinite(issued)):
            return False
        return 0 <= clock() - issued < SESSION_SECONDS

    @app.before_request
    def require_private_dashboard():
        # Returning the unlock page short-circuits later guards, so enforce the
        # same local-only boundary here too. Flask validates TRUSTED_HOSTS.
        if request.remote_addr not in {"127.0.0.1", "::1"}:
            return jsonify(ok=False, message="This tool is only available on this computer."), 403
        if isinstance(request.routing_exception, SecurityError):
            raise request.routing_exception
        authorized = authenticated()
        if not authorized and ("dashboard_session" in session or "dashboard_unlocked_at" in session):
            session.clear()
        if request.endpoint in PUBLIC_ENDPOINTS:
            return None
        if authorized:
            return None
        if request.path == "/" and request.method in {"GET", "HEAD"}:
            return render_template("unlock.html")
        return jsonify(ok=False, code="dashboard_locked",
                       message="Dashboard locked. Open the private link from this app's terminal."), 401

    @app.post("/api/unlock")
    def unlock_dashboard():
        origin = request.headers.get("Origin")
        if origin and origin != request.host_url.rstrip("/"):
            return jsonify(ok=False, message="Invalid request origin."), 403
        if not request.is_json:
            return jsonify(ok=False, message="Expected a JSON request."), 415
        data = request.get_json(silent=True)
        supplied = data.get("token") if isinstance(data, dict) else None
        if (not isinstance(supplied, str) or not supplied.isascii() or len(supplied) > 128
                or not secrets.compare_digest(supplied, token)):
            return jsonify(ok=False, message="Private code not accepted. Use the link from the current app terminal."), 403
        # Clear old cookies/CSRF state rather than adopting a caller's session.
        session.clear()
        session.permanent = True
        session["dashboard_session"] = epoch
        session["dashboard_unlocked_at"] = clock()
        session["csrf"] = secrets.token_urlsafe(32)
        return jsonify(ok=True)

    @app.get("/api/health")
    def dashboard_health():
        return jsonify(ok=True, application="tasmee-personal-reviews", authentication_required=True)


def private_dashboard_url(app, base_url):
    """Fragment capabilities never travel in HTTP request paths or Referer headers."""
    parsed = urlsplit(base_url)
    if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}
            or parsed.username or parsed.password or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment or parsed.port is None or not 1 <= parsed.port <= 65535):
        raise ValueError("Use the local dashboard's base HTTP URL with its port.")
    return base_url.rstrip("/") + "/#unlock=" + app.extensions["dashboard_token"]
