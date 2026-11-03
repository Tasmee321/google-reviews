"""Validate configuration, dependencies and browser installation without signing in."""
import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def installed_browser(channel, bundled):
    if channel == "chromium":
        return Path(bundled).is_file()
    if os.name == "nt":
        suffix = "Google/Chrome/Application/chrome.exe" if channel == "chrome" else "Microsoft/Edge/Application/msedge.exe"
        return any((Path(os.environ.get(key, "")) / suffix).is_file()
                   for key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"))
    if sys.platform == "darwin":
        name = "Google Chrome" if channel == "chrome" else "Microsoft Edge"
        return Path(f"/Applications/{name}.app/Contents/MacOS/{name}").is_file()
    names = ("google-chrome", "google-chrome-stable") if channel == "chrome" else ("microsoft-edge", "microsoft-edge-stable")
    return any(shutil.which(name) for name in names)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initialize", action="store_true", help="Create config.json from the example only when absent")
    parser.add_argument("--install-browser", action="store_true", help="Install bundled Chromium only if selected in config")
    parser.add_argument("--skip-browser", action="store_true", help="Validate files/dependencies only, for automated tests")
    parser.add_argument("--diagnostics", action="store_true", help="Print a redacted offline diagnostic report; no IP requests")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 11):
        print("Python 3.11 or newer is required.")
        return 1
    for name in ("flask", "dotenv", "playwright.sync_api"):
        try:
            importlib.import_module(name)
        except ImportError:
            print(f"Missing dependency: {name}. Run install.bat.")
            return 1
    from dotenv import load_dotenv
    from app_config import ConfigError, load_config
    from browser_options import launch_options
    from review_store import ReviewError
    load_dotenv(ROOT / ".env")
    try:
        if args.initialize and not (ROOT / "config.json").exists():
            with (ROOT / "config.json").open("x", encoding="utf-8") as output:
                output.write((ROOT / "config.example.json").read_text(encoding="utf-8"))
        cfg = load_config(ROOT / "config.json")
        if cfg["city_geolocation"]:
            from city_location import load_city_locations
            load_city_locations(ROOT)
        cities = json.loads((ROOT / "uk_cities.json").read_text(encoding="utf-8"))
        if (not isinstance(cities, dict) or set(cities) != {"England", "Scotland", "Wales", "Northern Ireland"}
                or any(not isinstance(names, list) or not names
                       or any(not isinstance(city, str) or not city for city in names)
                       or len(names) != len(set(names)) for names in cities.values())):
            raise ValueError("uk_cities.json must contain city lists for all four UK nations.")
        importlib.import_module("app")
        if cfg["mode"] == "extension":
            from build_firefox_extension import firefox_sources
            extension = firefox_sources()
            manifest = json.loads(extension["manifest.json"])
            if manifest["version"] != "1.0.7" or manifest["background"] != {"scripts": ["network_guard.js", "background.js"]}:
                raise ValueError("Extension sources are incomplete; update the complete 1.0.7 source package.")
        if not args.skip_browser:
            if cfg["mode"] == "extension":
                from personal_browser import browser_kind, firefox_executable
                if browser_kind() == "firefox":
                    firefox_executable()
            else:
                if args.install_browser and cfg["browser_channel"] == "chromium":
                    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
                from playwright.sync_api import sync_playwright
                with sync_playwright() as playwright:
                    # Flush driver initialization before stopping it on Python 3.14;
                    # this creates no browser and sends no HTTP requests.
                    request_context = playwright.request.new_context()
                    request_context.dispose()
                    launch_options(cfg, playwright.devices)
                    if not installed_browser(cfg["browser_channel"], playwright.chromium.executable_path):
                        raise ValueError("Configured browser is missing. Install Chrome/Edge, or select chromium in config.json and rerun install.bat.")
        print(f"Setup OK: {cfg['mode']} mode; http://127.0.0.1:{cfg['port']}/; {sum(map(len, cities.values()))} UK cities.")
        print("No application proxy. Connect Avast SecureLine VPN to an available UK server yourself.")
        guard_enabled = cfg["mode"] == "extension" or cfg["network_guard"]["enabled"]
        print("UK-IP guard: " + ("enabled; browser checks run before Google sign-in/posting" if guard_enabled else "DISABLED"))
        if cfg["mode"] == "extension":
            print("Install extension 1.0.7 or newer in the selected browser. Its browser-side UK-IP guard is always enabled.")
            print("Ordinary Firefox requires a Mozilla-signed add-on for permanent installation; this check does not sign or verify an installed add-on.")
        print("VPN routing and live Google sign-in were not tested by this offline check.")
        if args.diagnostics:
            from diagnostics import Diagnostics, diagnostic_report
            from local_security import inspect_data_directory
            print(json.dumps(diagnostic_report(cfg, {}, inspect_data_directory(ROOT / "personal_data"), Diagnostics()), indent=2))
        return 0
    except (ConfigError, ReviewError, ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"Setup error: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
