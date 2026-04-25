from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import pytest
from aiohttp import ClientSession, web

import keyward
from keyward import store
from keyward.config import daemon_file, ensure_dirs
from keyward.daemon import CacheEntry, create_app


def _write_daemon_json(port: int = 58765, pid: int | None = None) -> str:
    """Write a daemon.json as if a live daemon had booted. Defaults pid to this
    test process's PID so activate()'s liveness probe passes."""
    ensure_dirs()
    info = {"host": "127.0.0.1", "port": port, "pid": pid if pid is not None else os.getpid()}
    daemon_file().write_text(json.dumps(info))
    return f"http://127.0.0.1:{port}"


def test_activate_sets_base_url_when_token_is_in_env(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = store.add_key(
        "openai",
        "sk-real",
        "api.openai.com",
        ["OPENAI_API_KEY"],
        "OPENAI_BASE_URL",
    )
    daemon_url = _write_daemon_json()
    monkeypatch.setenv("OPENAI_API_KEY", entry.token)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    result = keyward.activate()

    assert result.activated == ["openai"]
    assert result.skipped_no_env == []
    assert result.skipped_no_base_url == []
    assert bool(result) is True
    assert os.environ["OPENAI_BASE_URL"] == daemon_url
    assert os.environ["OPENAI_API_KEY"] == entry.token
    assert os.environ["KEYWARD_DAEMON"] == daemon_url


def test_activate_leaves_real_key_alone(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.add_key(
        "openai",
        "sk-real",
        "api.openai.com",
        ["OPENAI_API_KEY"],
        "OPENAI_BASE_URL",
    )
    _write_daemon_json()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-this-is-a-real-key-not-a-token")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    result = keyward.activate()

    assert result.activated == []
    assert result.skipped_no_env == ["openai"]
    assert bool(result) is False
    assert "OPENAI_BASE_URL" not in os.environ


def test_activate_skips_unset_env_vars(isolated_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store.add_key(
        "openai",
        "sk-real",
        "api.openai.com",
        ["OPENAI_API_KEY"],
        "OPENAI_BASE_URL",
    )
    _write_daemon_json()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    result = keyward.activate()

    assert result.activated == []
    assert result.skipped_no_env == ["openai"]
    assert "OPENAI_BASE_URL" not in os.environ


def test_activate_skips_entry_with_no_base_url(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = store.add_key(
        "openai",
        "sk-real",
        "api.openai.com",
        ["OPENAI_API_KEY"],
        None,  # no base_url_env
    )
    _write_daemon_json()
    monkeypatch.setenv("OPENAI_API_KEY", entry.token)

    result = keyward.activate()

    assert result.activated == []
    assert result.skipped_no_base_url == ["openai"]
    assert result.skipped_no_env == []


def test_activate_activates_only_matching_keys(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    openai = store.add_key(
        "openai",
        "sk-real-o",
        "api.openai.com",
        ["OPENAI_API_KEY"],
        "OPENAI_BASE_URL",
    )
    store.add_key(
        "anthropic",
        "sk-real-a",
        "api.anthropic.com",
        ["ANTHROPIC_API_KEY"],
        "ANTHROPIC_BASE_URL",
        "x-api-key",
    )
    daemon_url = _write_daemon_json()
    monkeypatch.setenv("OPENAI_API_KEY", openai.token)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)

    result = keyward.activate()

    assert result.activated == ["openai"]
    assert result.skipped_no_env == ["anthropic"]
    assert os.environ["OPENAI_BASE_URL"] == daemon_url
    assert "ANTHROPIC_BASE_URL" not in os.environ


def test_activate_strict_raises_when_no_daemon(isolated_env: Path) -> None:
    with pytest.raises(keyward.DaemonNotRunning, match="no live daemon"):
        keyward.activate()


def test_activate_non_strict_returns_empty_when_no_daemon(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = store.add_key(
        "openai",
        "sk-real",
        "api.openai.com",
        ["OPENAI_API_KEY"],
        "OPENAI_BASE_URL",
    )
    monkeypatch.setenv("OPENAI_API_KEY", entry.token)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    result = keyward.activate(strict=False)

    assert not result
    assert result.activated == []
    assert "OPENAI_BASE_URL" not in os.environ


def test_activate_treats_dead_pid_as_no_daemon(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = store.add_key(
        "openai",
        "sk-real",
        "api.openai.com",
        ["OPENAI_API_KEY"],
        "OPENAI_BASE_URL",
    )
    _write_daemon_json(pid=999_999_999)  # very unlikely to be a real running PID
    monkeypatch.setenv("OPENAI_API_KEY", entry.token)

    with pytest.raises(keyward.DaemonNotRunning, match="no live daemon"):
        keyward.activate()


@pytest.mark.asyncio
async def test_activate_end_to_end_with_real_daemon(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full flow: real upstream + real daemon + real HTTP client. After activate(),
    the env-configured URL points at the daemon, which swaps the token for the
    real secret before forwarding upstream."""
    seen: dict[str, str | None] = {}

    async def upstream_handler(request: web.Request) -> web.Response:
        seen["auth"] = request.headers.get("Authorization")
        return web.json_response({"ok": True})

    up_app = web.Application()
    up_app.router.add_route("*", "/{path:.*}", upstream_handler)
    up_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    up_sock.bind(("127.0.0.1", 0))
    up_host, up_port = up_sock.getsockname()[:2]
    up_runner = web.AppRunner(up_app)
    await up_runner.setup()
    await web.SockSite(up_runner, up_sock).start()
    up_base = f"http://{up_host}:{up_port}"

    entry = store.add_key(
        "echo",
        "sk-real-12345",
        up_base,
        ["ECHO_API_KEY"],
        "ECHO_BASE_URL",
    )

    cache = {entry.token: CacheEntry(entry.name, up_base, "sk-real-12345", "bearer")}
    d_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    d_sock.bind(("127.0.0.1", 0))
    d_host, d_port = d_sock.getsockname()[:2]
    d_runner = web.AppRunner(create_app(cache))
    await d_runner.setup()
    await web.SockSite(d_runner, d_sock).start()

    ensure_dirs()
    daemon_file().write_text(json.dumps({"host": d_host, "port": d_port, "pid": os.getpid()}))

    monkeypatch.setenv("ECHO_API_KEY", entry.token)
    monkeypatch.delenv("ECHO_BASE_URL", raising=False)

    try:
        result = keyward.activate()
        assert result.activated == ["echo"]
        assert os.environ["ECHO_BASE_URL"] == f"http://{d_host}:{d_port}"

        async with ClientSession() as client:
            async with client.get(
                f"{os.environ['ECHO_BASE_URL']}/v1/anything",
                headers={"Authorization": f"Bearer {os.environ['ECHO_API_KEY']}"},
            ) as resp:
                assert resp.status == 200

        assert seen["auth"] == "Bearer sk-real-12345"
    finally:
        await d_runner.cleanup()
        await up_runner.cleanup()
