"""Build Firefox's unsigned add-on from the existing source; signing remains manual."""
import io
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILES = ("manifest.json", "network_guard.js", "background.js", "dashboard.js", "google.js", "review_widget.js", "popup.html", "popup.css")


def firefox_sources():
    source = ROOT / "chrome_extension"
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    manifest["background"] = {"scripts": ["network_guard.js", "background.js"]}
    manifest["browser_specific_settings"] = {"gecko": {
        "id": "tasmee-personal-reviews@local.invalid",
        "strict_min_version": "142.0",
        # Local dashboard exchange and user-requested Google transmission still count.
        # Do not mislabel review/account handling as "no data collected".
        "data_collection_permissions": {"required": [
            "personallyIdentifyingInfo", "browsingActivity", "websiteContent",
            "websiteActivity", "personalCommunications", "searchTerms", "locationInfo",
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


def deterministic_archive(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, files[name])
    buffer.seek(0)
    return buffer


def firefox_archive():
    return deterministic_archive(firefox_sources())


def source_archive():
    files = {name: (ROOT / name).read_bytes() for name in (
        "build_firefox_extension.py", "EXTENSION_PRIVACY.md", "FIREFOX_SOURCE_BUILD.md")}
    files.update({"chrome_extension/" + name: (ROOT / "chrome_extension" / name).read_bytes()
                  for name in FILES})
    return deterministic_archive(files)


def build():
    extension_sources = firefox_sources()
    folder = ROOT / "firefox_extension"
    folder.mkdir(exist_ok=True)
    for name, data in extension_sources.items():
        (folder / name).write_bytes(data)
    destination = ROOT / "dist"
    destination.mkdir(exist_ok=True)
    path = destination / "tasmee-firefox-unsigned.xpi"
    path.write_bytes(deterministic_archive(extension_sources).getvalue())
    version = json.loads(extension_sources["manifest.json"])["version"]
    versioned = destination / f"tasmee-firefox-{version}-unsigned.xpi"
    versioned.write_bytes(path.read_bytes())
    sources = destination / f"tasmee-firefox-{version}-source.zip"
    sources.write_bytes(source_archive().getvalue())
    print(f"Firefox source: {folder}\nUnsigned XPI: {path}")
    print(f"Versioned unsigned XPI: {versioned}\nMozilla build source: {sources}")
    print("Normal Firefox requires Mozilla signing for permanent installation.")
    print("For a local trial, load manifest.json using about:debugging > This Firefox > Load Temporary Add-on.")
    print("Temporary installation lasts until Firefox closes; profile login cookies remain.")


if __name__ == "__main__":
    build()
