"""Verify the keyward key swap by hitting an echo endpoint through the local daemon.

Prereq (one-time):
    keyward add <name> --endpoint httpbin.org
      (at the prompt, enter a distinctive fake secret, e.g. sk-fake-secret-12345)
    keyward restart

Run:
    uv run python scripts/verify_swap.py <name>

If the swap worked, the printed headers.Authorization (or headers.X-Api-Key) will
show the real secret, not 'Bearer kw_...'.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

import keyward
from keyward import store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("name", help="The keyward key name to verify (e.g. echotest).")
    parser.add_argument(
        "--path",
        default="/anything",
        help="Upstream path to hit (default: /anything, which works for httpbin.org).",
    )
    args = parser.parse_args(argv)

    entry = store.get_key(args.name)
    if entry is None:
        print(
            f"error: no key named '{args.name}'. Run:\n"
            f"  keyward add {args.name} --endpoint <host>\n"
            f"  keyward restart",
            file=sys.stderr,
        )
        return 1

    if not entry.env_vars or not entry.base_url_env:
        print(
            f"error: '{args.name}' has no env_vars or base_url_env configured.",
            file=sys.stderr,
        )
        return 1

    os.environ[entry.env_vars[0]] = entry.token

    try:
        result = keyward.activate()
    except keyward.DaemonNotRunning as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.name not in result.activated:
        print(
            f"error: keyward.activate() did not activate '{args.name}'.\n"
            f"  activated:        {result.activated}\n"
            f"  skipped (no env): {result.skipped_no_env}\n"
            f"  skipped (no url): {result.skipped_no_base_url}",
            file=sys.stderr,
        )
        return 1

    base_url = os.environ[entry.base_url_env]
    api_key = os.environ[entry.env_vars[0]]

    headers: dict[str, str] = {}
    if entry.auth_style == "x-api-key":
        headers["x-api-key"] = api_key
    else:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(f"{base_url}{args.path}", headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            status = resp.status
            body = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode(errors='replace')}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"error: could not reach daemon at {base_url}: {e}", file=sys.stderr)
        return 1

    print(f"status: {status}")
    print(f"daemon: {base_url}")
    print("response:")
    print(json.dumps(body, indent=2))

    echoed = body.get("headers", {})
    field = "X-Api-Key" if entry.auth_style == "x-api-key" else "Authorization"
    echoed_value = echoed.get(field, "")
    print()

    looks_like_token = echoed_value.startswith("kw_") or "Bearer kw_" in echoed_value
    if looks_like_token:
        print(f"FAIL: upstream saw '{echoed_value}' — the swap did not happen.")
        return 1
    if echoed_value:
        preview = echoed_value[:24] + ("..." if len(echoed_value) > 24 else "")
        print(f"OK: upstream saw the real secret ('{preview}'). Swap worked.")
        return 0
    print(f"WARN: upstream did not echo {field}; can't confirm swap.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
