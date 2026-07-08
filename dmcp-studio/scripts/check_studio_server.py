"""Classify any existing DMCP Studio server on a local port.

Outputs one word:
- free: nothing answered on the port
- current: Studio answered and advertises current advisor v2 routes
- stale: Studio answered but does not advertise current advisor v2 routes
- occupied: something else answered, timed out, or returned malformed health
"""

from __future__ import annotations

import argparse
import errno
import json
import socket
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def _tcp_connects(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def _is_refused(error: URLError) -> bool:
    reason = getattr(error, "reason", None)
    if isinstance(reason, ConnectionRefusedError):
        return True
    if isinstance(reason, OSError):
        return reason.errno in {errno.ECONNREFUSED, 10061}
    return False


def classify(port: int) -> str:
    if not _tcp_connects(port):
        return "free"

    try:
        with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.75) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except ConnectionRefusedError:
        return "free"
    except URLError as error:
        if _is_refused(error):
            return "free"
        return "occupied"
    except (HTTPError, TimeoutError, OSError, json.JSONDecodeError):
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
