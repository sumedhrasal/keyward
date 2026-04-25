from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path

LABEL = "com.keyward.daemon"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def log_dir() -> Path:
    return Path.home() / "Library" / "Logs" / "keyward"


def _uid() -> int:
    if not hasattr(os, "getuid"):
        raise RuntimeError("LaunchAgent install is macOS-only; not supported on this OS.")
    return os.getuid()


def _bootout() -> None:
    # Idempotent: non-zero exit when not loaded is fine.
    subprocess.run(
        ["launchctl", "bootout", f"gui/{_uid()}/{LABEL}"],
        check=False,
        capture_output=True,
    )


def _bootstrap(plist: Path) -> None:
    result = subprocess.run(
        ["launchctl", "bootstrap", f"gui/{_uid()}", str(plist)],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"launchctl bootstrap failed ({result.returncode}): "
            f"{result.stderr.decode().strip() or result.stdout.decode().strip()}"
        )


def _write_plist(plist: Path, python_executable: str) -> None:
    plist.parent.mkdir(parents=True, exist_ok=True)
    log_dir().mkdir(parents=True, exist_ok=True)
    contents = {
        "Label": LABEL,
        "ProgramArguments": [python_executable, "-m", "keyward.daemon"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(log_dir() / "daemon.out"),
        "StandardErrorPath": str(log_dir() / "daemon.err"),
        # Don't run faster than once every 5s if the daemon crash-loops.
        "ThrottleInterval": 5,
    }
    with plist.open("wb") as f:
        plistlib.dump(contents, f)


def install(python_executable: str) -> Path:
    """Write the LaunchAgent plist and load it. Idempotent."""
    path = plist_path()
    _write_plist(path, python_executable)
    _bootout()
    _bootstrap(path)
    return path


def uninstall() -> bool:
    """Unload and remove the LaunchAgent. Returns True if a plist was removed."""
    path = plist_path()
    _bootout()
    if path.exists():
        path.unlink()
        return True
    return False


def restart() -> None:
    """Kickstart the LaunchAgent, forcing it to reload config and secret cache."""
    subprocess.run(
        ["launchctl", "kickstart", "-k", f"gui/{_uid()}/{LABEL}"],
        check=False,
        capture_output=True,
    )


def is_installed() -> bool:
    return plist_path().exists()
