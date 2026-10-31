"""Build Firefox's unsigned add-on from the existing source; signing remains manual."""
import io
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILES = ("manifest.json", "background.js", "dashboard.js", "google.js", "review_widget.js", "popup.html", "popup.css")


def firefox_sources():
    source = ROOT / "chrome_extension"
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    manifest["background"] = {"scripts": ["background.js"]}
    manifest["browser_specific_settings"] = {"gecko": {
        "id": "tasmee-personal-reviews@local.invalid",
        "strict_min_version": "142.0",
        # Local dashboard exchange and user-requested Google transmission still count.
        # Do not mislabel review/account handling as "no data collected".
        "data_collection_permissions": {"required": [
            "personallyIdentifyingInfo", "browsingActivity", "websiteContent",
            "websiteActivity", "personalCommunications", "searchTerms",
        ]},
    }}
    result = {"manifest.json": (json.dumps(manifest, indent=2) + "\n").encode()}
    for name in FILES[1:]:
        text = (source / name).read_text(encoding="utf-8")
        if name.endswith(".js"):
            # Firefox's browser namespace returns promises; chrome's alias uses callbacks.
            text = text.replace("chrome.", "browser.")
        result[name] = text.encode("utf-8")
    result["PRIVACY.md"] = (ROOT / "EXTENSION_PRIVACY.md").read_bytes()
    return result


def firefox_archive():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in firefox_sources().items():
            archive.writestr(name, data)
    buffer.seek(0)
    return buffer


def build():
    folder = ROOT / "firefox_extension"
    folder.mkdir(exist_ok=True)
    for name, data in firefox_sources().items():
        (folder / name).write_bytes(data)
    destination = ROOT / "dist"
    destination.mkdir(exist_ok=True)
    path = destination / "tasmee-firefox-unsigned.xpi"
    path.write_bytes(firefox_archive().getvalue())
    version = json.loads(firefox_sources()["manifest.json"])["version"]
    versioned = destination / f"tasmee-firefox-{version}-unsigned.xpi"
    versioned.write_bytes(path.read_bytes())
    sources = destination / f"tasmee-firefox-{version}-source.zip"
    with zipfile.ZipFile(sources, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("build_firefox_extension.py", "EXTENSION_PRIVACY.md", "FIREFOX_SOURCE_BUILD.md"):
            archive.write(ROOT / name, name)
        for name in FILES:
            archive.write(ROOT / "chrome_extension" / name, "chrome_extension/" + name)
    print(f"Firefox source: {folder}\nUnsigned XPI: {path}")
    print(f"Versioned unsigned XPI: {versioned}\nMozilla build source: {sources}")
    print("Normal Firefox requires Mozilla signing for permanent installation.")
    print("For a local trial, load manifest.json using about:debugging > This Firefox > Load Temporary Add-on.")
    print("Temporary installation lasts until Firefox closes; profile login cookies remain.")


if __name__ == "__main__":
    build()
