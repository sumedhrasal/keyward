from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from aiohttp import ClientSession, web

from keyward.config import daemon_file
from keyward.daemon import create_app


# --- helpers ---------------------------------------------------------------


async def _start_site(app: web.Application) -> tuple[web.AppRunner, str, int]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    host, port = sock.getsockname()[:2]
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.SockSite(runner, sock)
    await site.start()
    return runner, host, port


async def _make_upstream(handler) -> tuple[web.AppRunner, str]:
    """Returns (runner, base_url). Base URL has no trailing slash."""
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handler)
    runner, host, port = await _start_site(app)
    return runner, f"http://{host}:{port}"


# --- subprocess smoke test ------------------------------------------------


@pytest.mark.asyncio
async def test_daemon_subprocess_starts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    proc = subprocess.Popen([sys.executable, "-m", "keyward.daemon"], env={**os.environ})
    try:
        deadline = time.time() + 3.0
        info = None
        while time.time() < deadline:
            if daemon_file().exists():
                try:
                    info = json.loads(daemon_file().read_text())
                    break
                except json.JSONDecodeError:
                    pass
            await asyncio.sleep(0.05)
        assert info is not None
        assert info["host"] == "127.0.0.1"
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=1.0)


# --- in-process proxy tests -----------------------------------------------


@pytest.mark.asyncio
async def test_proxy_swaps_auth_and_forwards_body() -> None:
    seen = {}

    async def upstream_handler(request: web.Request) -> web.Response:
        seen["auth"] = request.headers.get("Authorization")
        seen["path"] = request.path
        seen["method"] = request.method
        seen["body"] = await request.read()
        return web.json_response({"ok": True})

    up_runner, up_base = await _make_upstream(upstream_handler)
    cache = {"kw_abc123": ("openai", up_base, "sk-real-secret", "bearer")}
    daemon_runner, _, daemon_port = await _start_site(create_app(cache))

    try:
        async with ClientSession() as client:
            async with client.post(
                f"http://127.0.0.1:{daemon_port}/v1/chat/completions",
                headers={"Authorization": "Bearer kw_abc123"},
                json={"model": "gpt-4", "messages": []},
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data == {"ok": True}

        assert seen["auth"] == "Bearer sk-real-secret"
        assert seen["path"] == "/v1/chat/completions"
        assert seen["method"] == "POST"
        assert b"gpt-4" in seen["body"]
    finally:
        await daemon_runner.cleanup()
        await up_runner.cleanup()


@pytest.mark.asyncio
async def test_proxy_rejects_missing_bearer() -> None:
    async def upstream_handler(request: web.Request) -> web.Response:
        return web.Response(text="should not reach upstream")

    up_runner, up_base = await _make_upstream(upstream_handler)
    cache = {"kw_abc123": ("openai", up_base, "sk-real", "bearer")}
    daemon_runner, _, daemon_port = await _start_site(create_app(cache))

    try:
        async with ClientSession() as client:
            async with client.get(f"http://127.0.0.1:{daemon_port}/x") as resp:
                assert resp.status == 401
    finally:
        await daemon_runner.cleanup()
        await up_runner.cleanup()


@pytest.mark.asyncio
async def test_proxy_rejects_unknown_token() -> None:
    async def upstream_handler(request: web.Request) -> web.Response:
        return web.Response(text="should not reach upstream")

    up_runner, up_base = await _make_upstream(upstream_handler)
    daemon_runner, _, daemon_port = await _start_site(create_app({}))

    try:
        async with ClientSession() as client:
            async with client.get(
                f"http://127.0.0.1:{daemon_port}/x",
                headers={"Authorization": "Bearer kw_not_registered"},
            ) as resp:
                assert resp.status == 403
    finally:
        await daemon_runner.cleanup()
        await up_runner.cleanup()


@pytest.mark.asyncio
async def test_proxy_streams_sse() -> None:
    chunks = [b"data: one\n\n", b"data: two\n\n", b"data: three\n\n"]

    async def upstream_handler(request: web.Request) -> web.StreamResponse:
        resp = web.StreamResponse(
            status=200, headers={"Content-Type": "text/event-stream"}
        )
        await resp.prepare(request)
        for c in chunks:
            await resp.write(c)
            await asyncio.sleep(0.01)
        await resp.write_eof()
        return resp

    up_runner, up_base = await _make_upstream(upstream_handler)
    cache = {"kw_stream": ("openai", up_base, "sk-real", "bearer")}
    daemon_runner, _, daemon_port = await _start_site(create_app(cache))

    try:
        async with ClientSession() as client:
            async with client.get(
                f"http://127.0.0.1:{daemon_port}/v1/stream",
                headers={"Authorization": "Bearer kw_stream"},
            ) as resp:
                assert resp.status == 200
                assert "text/event-stream" in resp.headers.get("Content-Type", "")
                received = b""
                async for chunk in resp.content.iter_any():
                    received += chunk
                assert received == b"".join(chunks)
    finally:
        await daemon_runner.cleanup()
        await up_runner.cleanup()


@pytest.mark.asyncio
async def test_proxy_x_api_key_in_and_out() -> None:
    seen = {}

    async def upstream_handler(request: web.Request) -> web.Response:
        seen["auth"] = request.headers.get("Authorization")
        seen["x_api_key"] = request.headers.get("x-api-key")
        return web.json_response({"ok": True})

    up_runner, up_base = await _make_upstream(upstream_handler)
    cache = {"kw_ant1": ("anthropic", up_base, "sk-ant-real", "x-api-key")}
    daemon_runner, _, daemon_port = await _start_site(create_app(cache))

    try:
        async with ClientSession() as client:
            async with client.post(
                f"http://127.0.0.1:{daemon_port}/v1/messages",
                headers={"x-api-key": "kw_ant1"},
                json={"model": "claude-opus", "messages": []},
            ) as resp:
                assert resp.status == 200

        # Real secret must have replaced the client's token in x-api-key,
        # and Authorization must not leak any value (bearer style not used here).
        assert seen["x_api_key"] == "sk-ant-real"
        assert seen["auth"] is None
    finally:
        await daemon_runner.cleanup()
        await up_runner.cleanup()


@pytest.mark.asyncio
async def test_proxy_bearer_incoming_x_api_key_entry() -> None:
    """SDK might send Bearer while the upstream wants x-api-key.
    The daemon should still accept the token and forward in the entry's style."""
    seen = {}

    async def upstream_handler(request: web.Request) -> web.Response:
        seen["auth"] = request.headers.get("Authorization")
        seen["x_api_key"] = request.headers.get("x-api-key")
        return web.json_response({"ok": True})

    up_runner, up_base = await _make_upstream(upstream_handler)
    cache = {"kw_ant2": ("anthropic", up_base, "sk-ant-real", "x-api-key")}
    daemon_runner, _, daemon_port = await _start_site(create_app(cache))

    try:
        async with ClientSession() as client:
            async with client.post(
                f"http://127.0.0.1:{daemon_port}/v1/messages",
                headers={"Authorization": "Bearer kw_ant2"},
                json={"model": "claude-opus"},
            ) as resp:
                assert resp.status == 200

        assert seen["x_api_key"] == "sk-ant-real"
        # Authorization should be stripped (not forwarded with the fake token).
        assert seen["auth"] is None
    finally:
        await daemon_runner.cleanup()
        await up_runner.cleanup()


@pytest.mark.asyncio
async def test_proxy_forwards_upstream_error_status() -> None:
    async def upstream_handler(request: web.Request) -> web.Response:
        return web.json_response({"error": "invalid_api_key"}, status=401)

    up_runner, up_base = await _make_upstream(upstream_handler)
    cache = {"kw_bad": ("openai", up_base, "sk-wrong", "bearer")}
    daemon_runner, _, daemon_port = await _start_site(create_app(cache))

    try:
        async with ClientSession() as client:
            async with client.get(
                f"http://127.0.0.1:{daemon_port}/v1/anything",
                headers={"Authorization": "Bearer kw_bad"},
            ) as resp:
                assert resp.status == 401
                data = await resp.json()
                assert data["error"] == "invalid_api_key"
    finally:
        await daemon_runner.cleanup()
        await up_runner.cleanup()
