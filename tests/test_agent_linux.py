from __future__ import annotations

from pathlib import Path

import pytest

from keyward import agent_linux


@pytest.fixture
def fake_systemctl(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    class FakeResult:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(cmd, check=False, capture_output=False):
        calls.append(list(cmd))
        if check and FakeResult.returncode != 0:
            import subprocess

            raise subprocess.CalledProcessError(FakeResult.returncode, cmd)
        return FakeResult()

    monkeypatch.setattr("keyward.agent_linux.subprocess.run", fake_run)
    return calls


def test_unit_path_location(isolated_env: Path) -> None:
    p = agent_linux.unit_path()
    assert p == isolated_env / ".config" / "systemd" / "user" / "keyward.service"


def test_install_writes_unit_file_and_calls_systemctl(
    isolated_env: Path, fake_systemctl: list[list[str]]
) -> None:
    path = agent_linux.install("/usr/bin/python3")

    assert path.exists()
    content = path.read_text()
    assert "ExecStart=/usr/bin/python3 -m keyward.daemon" in content
    assert "Restart=on-failure" in content
    assert "WantedBy=default.target" in content

    flat = [" ".join(c) for c in fake_systemctl]
    assert any("daemon-reload" in c for c in flat)
    assert any("enable" in c and "keyward.service" in c for c in flat)


def test_install_is_idempotent(isolated_env: Path, fake_systemctl: list[list[str]]) -> None:
    agent_linux.install("/usr/bin/python3")
    before = len(fake_systemctl)
    agent_linux.install("/usr/bin/python3")
    assert len(fake_systemctl) == 2 * before
    assert agent_linux.unit_path().exists()


def test_uninstall_removes_unit_file(isolated_env: Path, fake_systemctl: list[list[str]]) -> None:
    agent_linux.install("/usr/bin/python3")
    assert agent_linux.uninstall() is True
    assert not agent_linux.unit_path().exists()
    assert agent_linux.uninstall() is False


def test_is_installed(isolated_env: Path, fake_systemctl: list[list[str]]) -> None:
    assert agent_linux.is_installed() is False
    agent_linux.install("/usr/bin/python3")
    assert agent_linux.is_installed() is True


def test_restart_calls_systemctl(isolated_env: Path, fake_systemctl: list[list[str]]) -> None:
    agent_linux.restart()
    flat = [" ".join(c) for c in fake_systemctl]
    assert any("restart" in c and "keyward.service" in c for c in flat)
