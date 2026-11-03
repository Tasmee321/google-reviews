"""Translate configuration into supported Playwright launch options."""
from review_store import ReviewError


def launch_options(cfg, devices):
    options = {}
    if cfg["device"]:
        if cfg["device"] not in devices:
            raise ReviewError("Unknown Playwright device in config.json. Use null for a desktop browser.")
        options.update(devices[cfg["device"]])
        options.pop("default_browser_type", None)
    else:
        options["viewport"] = {"width": 1280, "height": 900}
    # Merge options once: device descriptors also contain viewport and user_agent.
    options.update(headless=False, locale=cfg["locale"], chromium_sandbox=True)
    if cfg["browser_channel"] != "chromium":
        options["channel"] = cfg["browser_channel"]
    target = cfg["target"]
    if target["lat"] is not None:
        options["geolocation"] = {"latitude": target["lat"], "longitude": target["lng"]}
        options["permissions"] = ["geolocation"]
    if target["timezone"]:
        options["timezone_id"] = target["timezone"]
    return options
