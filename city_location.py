"""Offline city coordinates and Google-only browser geolocation permissions."""
import json
from pathlib import Path

from app_config import ConfigError, number
from review_store import ReviewError

ROOT = Path(__file__).resolve().parent
GOOGLE_ORIGINS = ("https://www.google.com", "https://google.com", "https://maps.google.com",
                  "https://www.google.co.uk", "https://www.google.com.pk")


def load_city_locations(root=ROOT):
    root = Path(root)
    try:
        path = root / "uk_city_locations.json"
        if path.stat().st_size > 1000000:
            raise ConfigError("City coordinate file is too large.")
        document = json.loads(path.read_text(encoding="utf-8"))
        cities = json.loads((root / "uk_cities.json").read_text(encoding="utf-8"))
        expected = {f"{city}, {country}, United Kingdom" for country, names in cities.items() for city in names}
        points = document["locations"]
        if not isinstance(points, dict) or set(points) != expected:
            raise ConfigError("City coordinates must match every city in the UK picker.")
        for key, point in points.items():
            if (not isinstance(point, dict) or not number(point.get("latitude"), 49, 61)
                    or not number(point.get("longitude"), -9, 3)):
                raise ConfigError(f"Invalid UK city coordinates: {key}")
        return points
    except (OSError, ValueError, KeyError, TypeError) as error:
        if isinstance(error, ConfigError):
            raise
        raise ConfigError("Cannot read UK city coordinates. Restore uk_city_locations.json from the project.") from error


def selected_location(cfg, points, city="", revision=0):
    if not isinstance(city, str) or len(city) > 200:
        raise ReviewError("Choose a city from the UK list.")
    if city:
        if not cfg["city_geolocation"]:
            raise ReviewError("Automatic city location is disabled in config.json.", 409)
        if city not in points:
            raise ReviewError("Unknown UK city. Choose a city from the list.")
        point = points[city]
        return {"selection": city, "source": "city", "enabled": True, "revision": revision,
                "latitude": point["latitude"], "longitude": point["longitude"]}
    target = cfg["target"]
    enabled = target["lat"] is not None
    return {"selection": "", "source": "config" if enabled else "off", "enabled": enabled,
            "revision": revision, "latitude": target["lat"], "longitude": target["lng"]}


def apply_browser_location(context, location):
    # Only application-granted overrides are cleared; no personal profile is copied.
    context.clear_permissions()
    if not location["enabled"]:
        context.set_geolocation(None)
        return
    context.set_geolocation({"latitude": location["latitude"], "longitude": location["longitude"]})
    for origin in GOOGLE_ORIGINS:
        context.grant_permissions(["geolocation"], origin=origin)
