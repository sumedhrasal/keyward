from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time

import typer

from keyward import __version__
from keyward.config import daemon_file, ensure_dirs

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
        False, "--version", callback=_version_cb, is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    pass


@app.command()
def init() -> None:
    """Create config and state dirs. (LaunchAgent install lands in v0.2.)"""
    ensure_dirs()
    typer.echo(f"config dir ready: {daemon_file().parent}")
    typer.echo("TODO: install LaunchAgent/systemd unit to pre-warm daemon at login")


@app.command()
def add(
    name: str = typer.Argument(..., help="Short name for this key, e.g. openai."),
    endpoint: str = typer.Option(..., "--endpoint", help="Allowlisted host, e.g. api.openai.com."),
) -> None:
    """Store a secret in the OS keychain and mint a token for it."""
    typer.echo(f"TODO: prompt for secret, store as '{name}', allowlist '{endpoint}'")


@app.command()
def rotate(name: str) -> None:
    """Replace the secret for an existing token. Token stays the same."""
    typer.echo(f"TODO: rotate secret for '{name}'")


@app.command("rm")
def remove(name: str) -> None:
    """Delete a secret and revoke its token."""
    typer.echo(f"TODO: remove '{name}'")


@app.command("list")
def list_() -> None:
    """Print registered keys, tokens, and allowlists."""
    typer.echo("TODO: list registered keys")


@app.command()
def approve(
    name: str = typer.Argument(..., help="Key name."),
    host: str = typer.Argument(..., help="Host to add to this key's allowlist."),
) -> None:
    """Add a new host to a key's allowlist."""
    typer.echo(f"TODO: approve {host} for '{name}'")


@app.command()
def log(
    since: str = typer.Option("1h", "--since", help="Time window, e.g. 10m, 2h, 1d."),
    key: str | None = typer.Option(None, "--key", help="Filter to one key name."),
) -> None:
    """Tail the audit log."""
    typer.echo(f"TODO: show audit log since={since} key={key}")


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def run(ctx: typer.Context) -> None:
    """Run a command with the daemon env vars injected.

    Example: keyward run -- python app.py
    """
    argv = list(ctx.args)
    if not argv:
        typer.echo("error: provide a command after --, e.g. keyward run -- echo hi", err=True)
        raise typer.Exit(2)

    ensure_dirs()

    # Start the daemon as a child process; tear it down when the command exits.
    # v0.2 will prefer a long-running daemon managed by LaunchAgent/systemd.
    daemon_proc = subprocess.Popen([sys.executable, "-m", "keyward.daemon"])

    info = None
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if daemon_file().exists():
            try:
                info = json.loads(daemon_file().read_text())
                break
            except json.JSONDecodeError:
                pass
        time.sleep(0.05)

    if info is None:
        daemon_proc.terminate()
        typer.echo("error: daemon did not start in time", err=True)
        raise typer.Exit(1)

    env = {**os.environ, "KEYWARD_DAEMON": f"http://{info['host']}:{info['port']}"}

    try:
        exit_code = subprocess.run(argv, env=env).returncode
    finally:
        try:
            os.kill(info["pid"], signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            daemon_proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            daemon_proc.kill()
            daemon_proc.wait(timeout=1.0)

    raise typer.Exit(exit_code)


if __name__ == "__main__":
    app()
