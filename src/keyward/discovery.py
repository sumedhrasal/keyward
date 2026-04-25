"""Daemon discovery: read daemon.json and check whether the registered process is alive."""

from __future__ import annotations

import json
import os
from typing import Any

from keyward.config import daemon_file


def live_daemon_info() -> dict[str, Any] | None:
    """Return {host, port, pid} if a daemon is registered and its PID is alive, else None."""
    path = daemon_file()
    if not path.exists():
        return None
    try:
        info = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    pid = info.get("pid")
    if not isinstance(pid, int):
        return None
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return None
    return info


def live_daemon_url() -> str | None:
    """Return http://host:port for the live daemon, else None."""
    info = live_daemon_info()
    if info is None:
        return None
    host = info.get("host")
    port = info.get("port")
    if not host or not port:
        return None
    return f"http://{host}:{port}"
