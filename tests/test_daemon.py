import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from aiohttp import ClientSession

from keyward.config import daemon_file


@pytest.mark.asyncio
async def test_daemon_starts_and_responds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    env = {**os.environ}
    proc = subprocess.Popen([sys.executable, "-m", "keyward.daemon"], env=env)

    info = None
    try:
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if daemon_file().exists():
                try:
                    info = json.loads(daemon_file().read_text())
                    break
                except json.JSONDecodeError:
                    pass
            await asyncio.sleep(0.05)

        assert info is not None, "daemon did not write daemon.json in time"
        assert info["host"] == "127.0.0.1"
        assert isinstance(info["port"], int) and info["port"] > 0

        async with ClientSession() as s:
            async with s.get(f"http://{info['host']}:{info['port']}/ping") as r:
                assert r.status == 200
                assert "keyward daemon ok" in await r.text()
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=1.0)
