"""Validated local configuration. Invalid files never silently fall back to defaults."""
import copy
import json
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULTS = {
    "mode": "poster", "port": 5000, "browser_channel": "chrome",
    "locale": "en-GB", "device": None, "proxies": [], "delay_range": [0, 0],
    "city_geolocation": True,
    "target": {"lat": None, "lng": None, "timezone": "Europe/London"},
    "timeouts": {"navigation_ms": 45000, "element_ms": 15000},
}


class ConfigError(ValueError):
    pass


def number(value, minimum, maximum):
    return type(value) in (int, float) and math.isfinite(value) and minimum <= value <= maximum


def validate_config(values):
    if not isinstance(values, dict):
        raise ConfigError("config.json must contain a JSON object.")
    unknown = values.keys() - DEFAULTS.keys() - {"api_key"}
    if unknown:
        raise ConfigError("Unknown config setting: " + ", ".join(sorted(unknown)))
    cfg = copy.deepcopy(DEFAULTS)
    for key, value in values.items():
        if key in {"target", "timeouts"}:
            if not isinstance(value, dict):
                raise ConfigError(f"{key} must be an object.")
            allowed = cfg[key].keys() | ({"name"} if key == "target" else set())
            if value.keys() - allowed:
                raise ConfigError(f"Unknown setting inside {key}.")
            cfg[key].update(copy.deepcopy(value))
        else:
            cfg[key] = copy.deepcopy(value)
    if cfg["mode"] not in ("poster", "extension"):
        raise ConfigError("mode must be poster or extension.")
    if type(cfg["city_geolocation"]) is not bool:
        raise ConfigError("city_geolocation must be true or false.")
    if type(cfg["port"]) is not int or not 1 <= cfg["port"] <= 65535:
        raise ConfigError("port must be a whole number from 1 to 65535.")
    if cfg["browser_channel"] not in ("chrome", "msedge", "chromium"):
        raise ConfigError("browser_channel must be chrome, msedge or chromium.")
    if not isinstance(cfg["locale"], str) or not 2 <= len(cfg["locale"]) <= 35:
        raise ConfigError("locale must be a language tag such as en-US.")
    if cfg["device"] is not None and (not isinstance(cfg["device"], str) or not 1 <= len(cfg["device"]) <= 100):
        raise ConfigError("device must be null or a Playwright device name.")
    delays = cfg["delay_range"]
    if (not isinstance(delays, (list, tuple)) or len(delays) != 2
            or not all(number(value, 0, 10) for value in delays) or delays[0] > delays[1]):
        raise ConfigError("delay_range must be [minimum, maximum], with 0 <= minimum <= maximum <= 10 seconds.")
    for key, value in cfg["timeouts"].items():
        if type(value) is not int or not 1000 <= value <= 60000:
            raise ConfigError(f"timeouts.{key} must be 1000..60000 milliseconds.")
    target = cfg["target"]
    if (target["lat"] is None) != (target["lng"] is None):
        raise ConfigError("target.lat and target.lng must both be null or both be numbers.")
    if target["lat"] is not None and not (number(target["lat"], -90, 90) and number(target["lng"], -180, 180)):
        raise ConfigError("Target latitude/longitude are outside their valid ranges.")
    if target["timezone"] is not None and (not isinstance(target["timezone"], str) or not 1 <= len(target["timezone"]) <= 100):
        raise ConfigError("target.timezone must be null or an IANA timezone name.")
    if cfg["proxies"] != []:
        raise ConfigError("Leave proxies as []. This setup uses the Windows network connection and Avast VPN.")
    return cfg


def load_config(path=None, environ=None):
    path = Path(path) if path is not None else ROOT / "config.json"
    try:
        if path.exists() and path.stat().st_size > 65536:
            raise ConfigError("config.json must be at most 64 KiB.")
        values = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ConfigError("Cannot read config.json; check the file and JSON syntax.") from error
    cfg = validate_config(values)
    env = os.environ if environ is None else environ
    for variable, key in (("REVIEW_MODE", "mode"), ("BROWSER_CHANNEL", "browser_channel")):
        if env.get(variable):
            cfg[key] = env[variable].strip().lower()
    if env.get("PORT"):
        try:
            cfg["port"] = int(env["PORT"])
        except ValueError as error:
            raise ConfigError("PORT must be a whole number from 1 to 65535.") from error
    return validate_config(cfg)
