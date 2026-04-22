from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import socket
import sys

from aiohttp import web

from keyward.config import daemon_file, ensure_dirs

logger = logging.getLogger("keyward.daemon")


async def handle(request: web.Request) -> web.Response:
    logger.info("%s %s", request.method, request.path)
    return web.Response(status=200, text="keyward daemon ok\n", content_type="text/plain")


async def _run() -> None:
    ensure_dirs()

    # Bind first to learn the assigned port, then hand the socket to aiohttp.
    # aiohttp's TCPSite(port=0) doesn't expose the bound port before start().
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    host, port = sock.getsockname()[:2]

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handle)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.SockSite(runner, sock)
    await site.start()

    daemon_file().write_text(
        json.dumps({"host": host, "port": port, "pid": os.getpid()})
    )
    logger.info("listening on %s:%d", host, port)

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
