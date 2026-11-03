"""Launch an ordinary, isolated Firefox profile. No automation or identity spoofing."""
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from review_store import ReviewError

ROOT = Path(__file__).resolve().parent
PROFILE = ROOT / "personal_data" / "firefox-profile"


def browser_kind():
    value = os.getenv("REVIEW_BROWSER", "firefox").strip().lower()
    if value not in {"chrome", "firefox"}:
        raise ReviewError("REVIEW_BROWSER must be chrome or firefox.")
    return value


def firefox_executable():
    candidates = [
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Mozilla Firefox/firefox.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Mozilla Firefox/firefox.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Mozilla Firefox/firefox.exe",
    ]
    executable = next((str(path) for path in candidates if path.is_file()), None) or shutil.which("firefox")
    if not executable:
        raise ReviewError("Install ordinary Mozilla Firefox, then run run_firefox.bat again. No other browser was opened.")
    return executable


def open_firefox_dashboard(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
            or parsed.username or parsed.password or parsed.path not in {"", "/"}):
        raise ReviewError("Only the local dashboard can be opened by this launcher.")
    executable = firefox_executable()
    PROFILE.mkdir(parents=True, exist_ok=True)
    # Never copy cookies/passwords from the personal browser or change security preferences.
    # Keep this same profile on every run; -no-remote isolates it from other Firefox windows.
    return subprocess.Popen([executable, "--no-remote", "--profile", str(PROFILE), "--new-window", url],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check Firefox without opening a window")
    args = parser.parse_args()
    if args.check:
        print(firefox_executable())
    else:
        open_firefox_dashboard("http://127.0.0.1:5000/")
