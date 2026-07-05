"""Classify any existing DMCP Studio server on a local port.

Outputs one word:
- free: nothing answered on the port
- current: Studio answered and advertises current advisor v2 routes
- stale: Studio answered but does not advertise current advisor v2 routes
- occupied: something else answered, timed out, or returned malformed health
"""

from __future__ import annotations

import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def classify(port: int) -> str:
    try:
        with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.75) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except ConnectionRefusedError:
        return "free"
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        return "occupied"

    if payload.get("capabilities", {}).get("advisor_v2") is True:
        return "current"
    if payload.get("status") == "ok":
        return "stale"
    return "occupied"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    print(classify(args.port))


if __name__ == "__main__":
    main()
