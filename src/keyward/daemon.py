from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import socket
import sys

from aiohttp import ClientError, ClientSession, web

from keyward import store
from keyward.config import daemon_file, ensure_dirs

logger = logging.getLogger("keyward.daemon")

CACHE_KEY: web.AppKey[dict[str, tuple[str, str, str]]] = web.AppKey(
    "cache", dict[str, tuple[str, str, str]]
)
CLIENT_KEY: web.AppKey[ClientSession] = web.AppKey("client", ClientSession)

# Hop-by-hop headers (RFC 2616) plus ones we rewrite ourselves.
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "host",
    "authorization",
}


async def handle(request: web.Request) -> web.StreamResponse:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return web.Response(status=401, text="missing bearer token\n")
    token = auth[len("Bearer "):].strip()

    cache = request.app[CACHE_KEY]
    tup = cache.get(token)
    if tup is None:
        return web.Response(status=403, text="unknown token\n")
    name, endpoint, secret = tup

    base = endpoint if "://" in endpoint else f"https://{endpoint}"
    target_url = f"{base}{request.path_qs}"

    out_headers = {
        k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP
    }
    out_headers["Authorization"] = f"Bearer {secret}"

    body = await request.read()

    logger.info(
        "%s %s -> %s [%s]", request.method, request.path, endpoint, name
    )

    client = request.app[CLIENT_KEY]
    try:
        upstream_cm = client.request(
            request.method,
            target_url,
            headers=out_headers,
            data=body if body else None,
            allow_redirects=False,
        )
    except ClientError as e:
        logger.warning("upstream connect error: %s", e)
        return web.Response(status=502, text=f"upstream error: {e}\n")

    try:
        async with upstream_cm as upstream:
            resp_headers = {
                k: v
                for k, v in upstream.headers.items()
                if k.lower() not in HOP_BY_HOP
            }
            resp = web.StreamResponse(status=upstream.status, headers=resp_headers)
            await resp.prepare(request)
            # iter_any yields as soon as bytes arrive; important for SSE streams.
            async for chunk in upstream.content.iter_any():
                await resp.write(chunk)
            await resp.write_eof()
            return resp
    except ClientError as e:
        logger.warning("upstream stream error: %s", e)
        return web.Response(status=502, text=f"upstream error: {e}\n")


def build_cache() -> dict[str, tuple[str, str, str]]:
    cache: dict[str, tuple[str, str, str]] = {}
    for entry in store.list_keys():
        s = store.read_secret(entry.name)
        if s is None:
            logger.warning("no keychain entry for '%s'; skipping", entry.name)
            continue
        cache[entry.token] = (entry.name, entry.endpoint, s)
    return cache


def create_app(cache: dict[str, tuple[str, str, str]]) -> web.Application:
    app = web.Application()
    app[CACHE_KEY] = cache

    async def _on_startup(app: web.Application) -> None:
        app[CLIENT_KEY] = ClientSession()

    async def _on_cleanup(app: web.Application) -> None:
        await app[CLIENT_KEY].close()

    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    app.router.add_route("*", "/{path:.*}", handle)
    return app


async def _run() -> None:
    ensure_dirs()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    host, port = sock.getsockname()[:2]

    cache = build_cache()
    app = create_app(cache)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.SockSite(runner, sock)
    await site.start()

    daemon_file().write_text(
        json.dumps({"host": host, "port": port, "pid": os.getpid()})
    )
    logger.info("listening on %s:%d (%d keys cached)", host, port, len(cache))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    try:
        await stop.wait()
    finally:
        daemon_file().unlink(missing_ok=True)
        await runner.cleanup()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
