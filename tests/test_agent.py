from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from keyward import agent


@pytest.fixture
def fake_launchctl(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    class FakeResult:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = b""
            self.stderr = b""

    def fake_run(cmd, check=False, capture_output=False):
        calls.append(cmd)
        return FakeResult()

    monkeypatch.setattr("keyward.agent.subprocess.run", fake_run)
    return calls


def test_plist_path_location(isolated_env: Path) -> None:
    p = agent.plist_path()
    assert p == isolated_env / "Library" / "LaunchAgents" / "com.keyward.daemon.plist"


def test_install_writes_plist_and_calls_launchctl(
    isolated_env: Path, fake_launchctl: list[list[str]]
) -> None:
    path = agent.install("/usr/bin/python3")

    assert path.exists()
    with path.open("rb") as f:
        plist = plistlib.load(f)
    assert plist["Label"] == "com.keyward.daemon"
    assert plist["ProgramArguments"] == ["/usr/bin/python3", "-m", "keyward.daemon"]
    assert plist["RunAtLoad"] is True
    assert plist["KeepAlive"] is True

    cmds = [c[1] for c in fake_launchctl]
    assert "bootout" in cmds
    assert "bootstrap" in cmds

    # Log dir must exist so launchd can write to it on first launch.
    assert (isolated_env / "Library" / "Logs" / "keyward").is_dir()


def test_install_is_idempotent(isolated_env: Path, fake_launchctl: list[list[str]]) -> None:
    agent.install("/usr/bin/python3")
    before = len(fake_launchctl)
    agent.install("/usr/bin/python3")
    # bootout+bootstrap should run on every install; plist just gets overwritten.
    assert len(fake_launchctl) == 2 * before
    assert agent.plist_path().exists()


def test_uninstall_removes_plist(isolated_env: Path, fake_launchctl: list[list[str]]) -> None:
    agent.install("/usr/bin/python3")
    assert agent.uninstall() is True
    assert not agent.plist_path().exists()
    assert agent.uninstall() is False


def test_is_installed(isolated_env: Path, fake_launchctl: list[list[str]]) -> None:
    assert agent.is_installed() is False
    agent.install("/usr/bin/python3")
    assert agent.is_installed() is True
