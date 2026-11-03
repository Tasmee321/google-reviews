"""Read-only startup check. Never launches a browser or changes review state."""
import json
import socket
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener

from dotenv import load_dotenv
from app_config import ConfigError, load_config

ROOT = Path(__file__).resolve().parent


def check_dashboard(port):
    url = f"http://127.0.0.1:{port}/"
    # Local health checks must never be sent through a configured HTTP proxy.
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(url + "api/status", timeout=3) as response:
            data = json.loads(response.read(512000))
        if (not isinstance(data, dict) or data.get("ok") is not True
                or not isinstance(data.get("browser"), dict)
                or not isinstance(data.get("reviews"), list)):
            print(f"Another service is using {url}; nothing new was started.")
            return 2
        print(f"Tasmee dashboard already running: {url}")
        print("Use the existing dashboard tab. Restart the server to apply configuration changes.")
        return 0
    except HTTPError as error:
        error.close()
        print(f"Another service responded at {url}; nothing new was started.")
        return 2
    except (ValueError, socket.timeout, TimeoutError):
        print(f"Could not verify the service at {url}; nothing new was started.")
        return 2
    except URLError as error:
        if isinstance(error.reason, (socket.timeout, TimeoutError)):
            print(f"Local server did not respond at {url}. Try again shortly.")
            return 2
        return 1
    except OSError:
        return 1


def main():
    load_dotenv(ROOT / ".env")
    try:
        port = load_config()["port"]
    except ConfigError as error:
        print(str(error))
        return 2
    return check_dashboard(port)


if __name__ == "__main__":
    raise SystemExit(main())
