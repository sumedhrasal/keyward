from __future__ import annotations

import contextlib
import json
import os
import platform
import signal
import subprocess
import sys
import time

import typer

from keyward import __version__, agent, store
from keyward.config import daemon_file, ensure_dirs
from keyward.discovery import live_daemon_info

app = typer.Typer(
    name="keyward",
    help="Local secret broker. Keeps API keys out of files AI agents can read.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_cb(value: bool) -> None:
    if value:
        typer.echo(f"keyward {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_cb,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    pass


def _hint_restart_if_running() -> None:
    if live_daemon_info() is not None:
        typer.echo("hint: a daemon is running. Run 'keyward restart' to reload the change.")


@app.command()
def init(
    uninstall: bool = typer.Option(False, "--uninstall", help="Remove the login agent."),
) -> None:
    """Create config/state dirs and install the daemon as a login agent."""
    ensure_dirs()

    if uninstall:
        if platform.system() != "Darwin":
            typer.echo("uninstalling a login agent is only wired up for macOS in v0.2", err=True)
            raise typer.Exit(1)
        removed = agent.uninstall()
        typer.echo("removed LaunchAgent" if removed else "no LaunchAgent was installed")
        return

    typer.echo(f"config dir ready: {daemon_file().parent}")

    system = platform.system()
    if system == "Darwin":
        try:
            path = agent.install(sys.executable)
        except RuntimeError as e:
            typer.echo(f"error: {e}", err=True)
            raise typer.Exit(1) from None
        typer.echo(f"installed LaunchAgent at {path}")
        typer.echo("daemon will start at login (and is running now).")
    elif system == "Linux":
        typer.echo("TODO: systemd user-unit install (Linux) lands in v0.2.1")
    elif system == "Windows":
        typer.echo("TODO: scheduled-task install (Windows) lands in v0.2.1")
    else:
        typer.echo(f"unsupported platform: {system}", err=True)
        raise typer.Exit(1)


@app.command()
def restart() -> None:
    """Restart the daemon to reload config and refresh the secret cache."""
    if platform.system() == "Darwin" and agent.is_installed():
        agent.restart()
        typer.echo("kickstarted LaunchAgent daemon")
        return
    info = live_daemon_info()
    if info is None:
        typer.echo("no daemon is running")
        return
    try:
        os.kill(info["pid"], signal.SIGTERM)
        typer.echo("sent SIGTERM to ephemeral daemon; next 'keyward run' will start a fresh one")
    except ProcessLookupError:
        typer.echo("daemon not running")


@app.command()
def add(
    name: str = typer.Argument(..., help="Short name for this key, e.g. openai."),
    endpoint: str = typer.Option(..., "--endpoint", help="Allowlisted host, e.g. api.openai.com."),
    env: list[str] = typer.Option(
        None,
        "--env",
        help="Env var to set to the token (repeatable). Defaults to <NAME>_API_KEY.",
    ),
    base_url_env: str | None = typer.Option(
        None,
        "--base-url-env",
        help="Env var for the base URL pointing at the daemon. Defaults to <NAME>_BASE_URL.",
    ),
    auth_style: str = typer.Option(
        "bearer",
        "--auth-style",
        help="Upstream auth style: 'bearer' (OpenAI-style) or 'x-api-key' (Anthropic-style).",
    ),
) -> None:
    """Store a secret in the OS keychain and mint a token for it."""
    if auth_style not in store.AUTH_STYLES:
        typer.echo(
            f"error: --auth-style must be one of {store.AUTH_STYLES}, got {auth_style!r}",
            err=True,
        )
        raise typer.Exit(2)
    secret = typer.prompt("secret", hide_input=True)
    env_vars = list(env) if env else [f"{name.upper()}_API_KEY"]
    if base_url_env is None:
        base_url_env = f"{name.upper()}_BASE_URL"
    try:
        entry = store.add_key(name, secret, endpoint, env_vars, base_url_env, auth_style)
    except KeyError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from None
    typer.echo(f"added '{entry.name}' -> {entry.endpoint} ({entry.auth_style})")
    typer.echo(f"  token:    {entry.token}")
    typer.echo(f"  env vars: {', '.join(entry.env_vars)}")
    if entry.base_url_env:
        typer.echo(f"  base url: {entry.base_url_env}")
    _hint_restart_if_running()


@app.command()
def rotate(name: str) -> None:
    """Replace the secret for an existing token. Token stays the same."""
    secret = typer.prompt("new secret", hide_input=True)
    entry = store.rotate_secret(name, secret)
    if entry is None:
        typer.echo(f"error: no key named '{name}'", err=True)
        raise typer.Exit(1)
    typer.echo(f"rotated secret for '{name}' (token unchanged: {entry.token})")
    _hint_restart_if_running()


@app.command("rm")
def remove(
    name: str,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Delete a secret and revoke its token."""
    if store.get_key(name) is None:
        typer.echo(f"error: no key named '{name}'", err=True)
        raise typer.Exit(1)
    if not yes and not typer.confirm(f"remove '{name}' and delete its secret?"):
        raise typer.Exit(0)
    store.remove_key(name)
    typer.echo(f"removed '{name}'")
    _hint_restart_if_running()


@app.command("list")
def list_() -> None:
    """Print registered keys, tokens, and endpoints."""
    entries = store.list_keys()
    if not entries:
        typer.echo("(no keys registered; run 'keyward add <name> --endpoint <host>')")
        return
    width = max(len(e.name) for e in entries)
    for e in entries:
        style = f"[{e.auth_style}]" if e.auth_style != "bearer" else ""
        typer.echo(f"{e.name.ljust(width)}  {e.token}  -> {e.endpoint} {style}".rstrip())


@app.command()
def approve(
    name: str = typer.Argument(..., help="Key name."),
    host: str = typer.Argument(..., help="Host to add to this key's allowlist."),
) -> None:
    """Add a new host to a key's allowlist. (Multi-endpoint support lands in v0.3.)"""
    typer.echo(f"TODO: approve {host} for '{name}' (single-endpoint only in v0.2)")


@app.command()
def log(
    since: str = typer.Option("1h", "--since", help="Time window, e.g. 10m, 2h, 1d."),
    key: str | None = typer.Option(None, "--key", help="Filter to one key name."),
) -> None:
    """Tail the audit log."""
    typer.echo(f"TODO: show audit log since={since} key={key}")


def _wait_for_daemon(timeout: float = 2.0) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if daemon_file().exists():
            try:
                return json.loads(daemon_file().read_text())
            except json.JSONDecodeError:
                pass
        time.sleep(0.05)
    return None


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def run(ctx: typer.Context) -> None:
    """Run a command with daemon env vars injected.

    Example: keyward run -- python app.py
    """
    argv = list(ctx.args)
    if not argv:
        typer.echo("error: provide a command after --, e.g. keyward run -- echo hi", err=True)
        raise typer.Exit(2)

    ensure_dirs()

    info = live_daemon_info()
    daemon_proc: subprocess.Popen | None = None
    if info is None:
        daemon_proc = subprocess.Popen([sys.executable, "-m", "keyward.daemon"])
        info = _wait_for_daemon()
        if info is None:
            daemon_proc.terminate()
            typer.echo("error: daemon did not start in time", err=True)
            raise typer.Exit(1)

    daemon_url = f"http://{info['host']}:{info['port']}"
    env = {**os.environ, "KEYWARD_DAEMON": daemon_url}
    for entry in store.list_keys():
        for var in entry.env_vars:
            env[var] = entry.token
        if entry.base_url_env:
            env[entry.base_url_env] = daemon_url

    try:
        exit_code = subprocess.run(argv, env=env).returncode
    finally:
        if daemon_proc is not None:
            # This process started the daemon; clean it up. An existing long-running
            # daemon (e.g. the LaunchAgent) is left alone.
            with contextlib.suppress(ProcessLookupError):
                os.kill(info["pid"], signal.SIGTERM)
            try:
                daemon_proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                daemon_proc.kill()
                daemon_proc.wait(timeout=1.0)

    raise typer.Exit(exit_code)


if __name__ == "__main__":
    app()
