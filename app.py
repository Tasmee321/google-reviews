#!/usr/bin/env python3
"""
Tasmee Review Agency — Web Dashboard
Flask backend: admin login, accounts, targets, settings, poster control
"""

import os, json, subprocess, threading, time, hashlib, secrets
from pathlib import Path
from functools import wraps
from flask import Flask, send_from_directory, request, jsonify, Response, session, redirect, url_for
from dotenv import load_dotenv, set_key

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", secrets.token_hex(32))

TEMPLATES_DIR = Path(__file__).parent / "templates"

def serve_html():
    return send_from_directory(str(TEMPLATES_DIR), "index.html")

ROOT        = Path(__file__).parent
ACCOUNTS_F  = ROOT / "accounts.json"
TARGETS_F   = ROOT / "targets.json"
STATE_F     = ROOT / "state.json"
ENV_F       = ROOT / ".env"
LOGS_DIR    = ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)

poster_proc = None
poster_lock = threading.Lock()

# ============ HELPERS ============
def read_json(path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default

def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def get_env(key, default=""):
    return os.getenv(key, default)

def save_env(key, value):
    """Write a key=value to .env file"""
    set_key(str(ENV_F), key, str(value))
    os.environ[key] = str(value)

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "msg": "Unauthorized"}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated

# ============ AUTH ROUTES ============
@app.route("/login", methods=["GET"])
def login_page():
    if session.get("logged_in"):
        return redirect(url_for("index"))
    return serve_html()

@app.route("/api/login", methods=["POST"])
def do_login():
    data = request.json or {}
    admin_user = os.getenv("ADMIN_USER", "admin")
    admin_pass = os.getenv("ADMIN_PASS", "admin123")
    if data.get("username") == admin_user and data.get("password") == admin_pass:
        session["logged_in"] = True
        return jsonify({"ok": True})
    return jsonify({"ok": False, "msg": "Wrong username or password"}), 401

@app.route("/api/logout", methods=["POST"])
def do_logout():
    session.clear()
    return jsonify({"ok": True})

# ============ MAIN ROUTES ============
@app.route("/")
@login_required
def index():
    return serve_html()

@app.route("/api/accounts", methods=["GET"])
@login_required
def get_accounts():
    return jsonify(read_json(ACCOUNTS_F, []))

@app.route("/api/accounts", methods=["POST"])
@login_required
def save_accounts():
    write_json(ACCOUNTS_F, request.json)
    return jsonify({"ok": True})

@app.route("/api/targets", methods=["GET"])
@login_required
def get_targets():
    return jsonify(read_json(TARGETS_F, []))

@app.route("/api/targets", methods=["POST"])
@login_required
def save_targets():
    write_json(TARGETS_F, request.json)
    return jsonify({"ok": True})

@app.route("/api/state", methods=["GET"])
@login_required
def get_state():
    return jsonify(read_json(STATE_F, {}))

@app.route("/api/state/reset", methods=["POST"])
@login_required
def reset_state():
    if STATE_F.exists():
        STATE_F.unlink()
    return jsonify({"ok": True})

# ============ SETTINGS ============
@app.route("/api/settings", methods=["GET"])
@login_required
def get_settings():
    return jsonify({
        "HEADLESS":              get_env("HEADLESS", "false"),
        "SLOW_MO":               get_env("SLOW_MO", "55"),
        "GAP_MIN":               get_env("GAP_MIN", "1200"),
        "GAP_MAX":               get_env("GAP_MAX", "5400"),
        "DAILY_LIMIT_PER_ACCT": get_env("DAILY_LIMIT_PER_ACCT", "2"),
        "MAX_RETRIES":           get_env("MAX_RETRIES", "3"),
        "TZ":                    get_env("TZ", "Asia/Karachi"),
        "LOCALE":                get_env("LOCALE", "en-US"),
        "WARMUP_ENABLED":        get_env("WARMUP_ENABLED", "true"),
        "ADMIN_USER":            get_env("ADMIN_USER", "admin"),
    })

@app.route("/api/settings", methods=["POST"])
@login_required
def save_settings():
    data = request.json or {}
    allowed = [
        "HEADLESS", "SLOW_MO", "GAP_MIN", "GAP_MAX",
        "DAILY_LIMIT_PER_ACCT", "MAX_RETRIES", "TZ", "LOCALE",
        "WARMUP_ENABLED", "ADMIN_USER", "ADMIN_PASS",
    ]
    for key in allowed:
        if key in data and data[key] != "":
            save_env(key, data[key])
    return jsonify({"ok": True})

# ============ POSTER ============
@app.route("/api/poster/start", methods=["POST"])
@login_required
def start_poster():
    global poster_proc
    with poster_lock:
        if poster_proc and poster_proc.poll() is None:
            return jsonify({"ok": False, "msg": "Already running"})
        poster_proc = subprocess.Popen(
            ["python", "poster.py"],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
    return jsonify({"ok": True, "pid": poster_proc.pid})

@app.route("/api/poster/stop", methods=["POST"])
@login_required
def stop_poster():
    global poster_proc
    with poster_lock:
        if poster_proc and poster_proc.poll() is None:
            poster_proc.terminate()
            return jsonify({"ok": True})
    return jsonify({"ok": False, "msg": "Not running"})

@app.route("/api/poster/status", methods=["GET"])
@login_required
def poster_status():
    global poster_proc
    if poster_proc is None:
        return jsonify({"running": False})
    return jsonify({"running": poster_proc.poll() is None, "pid": poster_proc.pid})

@app.route("/api/logs/stream")
@login_required
def stream_logs():
    def generate():
        log_file = None
        last_size = 0
        while True:
            logs = sorted(LOGS_DIR.glob("run_*.log"))
            if logs:
                latest = logs[-1]
                if latest != log_file:
                    log_file = latest
                    last_size = 0
                try:
                    size = log_file.stat().st_size
                    if size > last_size:
                        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                            f.seek(last_size)
                            new = f.read()
                        last_size = size
                        for line in new.splitlines():
                            yield f"data: {line}\n\n"
                except Exception:
                    pass
            time.sleep(1)
    return Response(generate(), mimetype="text/event-stream")

@app.route("/api/logs/latest", methods=["GET"])
@login_required
def latest_log():
    logs = sorted(LOGS_DIR.glob("run_*.log"))
    if not logs:
        return jsonify({"lines": []})
    try:
        lines = logs[-1].read_text(encoding="utf-8", errors="replace").splitlines()
        return jsonify({"lines": lines[-200:]})
    except Exception:
        return jsonify({"lines": []})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
