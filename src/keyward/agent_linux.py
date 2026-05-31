from __future__ import annotations

import subprocess
from pathlib import Path

UNIT_NAME = "keyward.service"


def unit_path() -> Path:
    base = Path.home() / ".config" / "systemd" / "user"
    return base / UNIT_NAME


def _unit_content(python_executable: str) -> str:
    return f"""\
[Unit]
Description=keyward secret broker daemon
After=default.target

[Service]
ExecStart={python_executable} -m keyward.daemon
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""


def install(python_executable: str) -> Path:
    path = unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_unit_content(python_executable))
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", UNIT_NAME], check=True)
    return path


def uninstall() -> bool:
    path = unit_path()
    subprocess.run(
        ["systemctl", "--user", "disable", "--now", UNIT_NAME],
        check=False,
        capture_output=True,
    )
    if path.exists():
        path.unlink()
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            check=False,
            capture_output=True,
        )
        return True
    return False


def restart() -> None:
    subprocess.run(["systemctl", "--user", "restart", UNIT_NAME], check=True)


def is_installed() -> bool:
    return unit_path().exists()
