"""Runtime activation: rewrite env vars holding keyward tokens so SDKs talk to the daemon."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from keyward.discovery import live_daemon_url
from keyward.store import list_keys


class DaemonNotRunning(RuntimeError):
    """Raised by activate(strict=True) when no live keyward daemon is registered."""


@dataclass
class ActivateResult:
    """Outcome of a keyward.activate() call.

    Truthy when at least one key was activated, so existing ``if keyward.activate():``
    checks keep working without modification.
    """

    activated: list[str] = field(default_factory=list)
    """Keys whose base_url_env was rewritten to point at the daemon."""

    skipped_no_env: list[str] = field(default_factory=list)
    """Keys whose token was not found in any of their configured env_vars."""

    skipped_no_base_url: list[str] = field(default_factory=list)
    """Keys that have no base_url_env configured — nothing to rewrite."""

    def __bool__(self) -> bool:
        return bool(self.activated)


def activate(*, strict: bool = True) -> ActivateResult:
    """Point SDKs at the local keyward daemon for any env var holding a keyward token.

    For each registered key, if any of its env_vars is set in os.environ to the
    entry's token, set the entry's base_url_env to the daemon URL. Real keys
    (values that don't match a registered token) and unset vars are left alone.

    Returns an ActivateResult with three lists: activated, skipped_no_env,
    skipped_no_base_url. The result is truthy when at least one key was activated.

    With strict=True (default), raises DaemonNotRunning if no live daemon is
    registered. With strict=False, returns an empty result and leaves env untouched.
    """
    url = live_daemon_url()
    if url is None:
        if strict:
            raise DaemonNotRunning(
                "keyward: no live daemon. Run 'keyward init' to install the login "
                "agent, or wrap the process with 'keyward run'."
            )
        return ActivateResult()

    result = ActivateResult()
    for entry in list_keys():
        if not entry.base_url_env:
            result.skipped_no_base_url.append(entry.name)
            continue
        if not any(os.environ.get(var) == entry.token for var in entry.env_vars):
            result.skipped_no_env.append(entry.name)
            continue
        os.environ[entry.base_url_env] = url
        result.activated.append(entry.name)

    os.environ.setdefault("KEYWARD_DAEMON", url)
    return result
