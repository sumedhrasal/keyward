from __future__ import annotations

from pathlib import Path

import keyring
from typer.testing import CliRunner

from keyward import store
from keyward.cli import app

runner = CliRunner()


def test_help_exits_zero() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "keyward" in result.stdout.lower()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "keyward" in result.stdout.lower()


def test_run_requires_command() -> None:
    result = runner.invoke(app, ["run"])
    assert result.exit_code == 2


def test_add_list_rm_cycle(isolated_env: Path) -> None:
    result = runner.invoke(
        app, ["add", "openai", "--endpoint", "api.openai.com"], input="sk-secret\n"
    )
    assert result.exit_code == 0, result.stdout
    assert "added 'openai'" in result.stdout
    assert "kw_" in result.stdout
    assert "OPENAI_API_KEY" in result.stdout

    assert keyring.get_password("keyward", "openai") == "sk-secret"

    entries = store.list_keys()
    assert len(entries) == 1
    assert entries[0].name == "openai"
    assert entries[0].endpoint == "api.openai.com"
    assert entries[0].token.startswith("kw_")
    assert entries[0].env_vars == ["OPENAI_API_KEY"]
    assert entries[0].base_url_env == "OPENAI_BASE_URL"

    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "openai" in result.stdout
    assert "api.openai.com" in result.stdout

    result = runner.invoke(app, ["rm", "openai", "-y"])
    assert result.exit_code == 0
    assert keyring.get_password("keyward", "openai") is None
    assert store.list_keys() == []


def test_add_rejects_duplicate(isolated_env: Path) -> None:
    runner.invoke(app, ["add", "openai", "--endpoint", "api.openai.com"], input="sk-a\n")
    result = runner.invoke(app, ["add", "openai", "--endpoint", "api.openai.com"], input="sk-b\n")
    assert result.exit_code == 1
    assert "already exists" in result.stderr


def test_rotate_keeps_token(isolated_env: Path) -> None:
    runner.invoke(app, ["add", "openai", "--endpoint", "api.openai.com"], input="sk-a\n")
    original_token = store.list_keys()[0].token

    result = runner.invoke(app, ["rotate", "openai"], input="sk-b\n")
    assert result.exit_code == 0
    assert "token unchanged" in result.stdout

    assert store.list_keys()[0].token == original_token
    assert keyring.get_password("keyward", "openai") == "sk-b"


def test_rotate_unknown_key(isolated_env: Path) -> None:
    result = runner.invoke(app, ["rotate", "nonexistent"], input="x\n")
    assert result.exit_code == 1


def test_custom_env_var(isolated_env: Path) -> None:
    result = runner.invoke(
        app,
        ["add", "claude", "--endpoint", "api.anthropic.com", "--env", "ANTHROPIC_API_KEY"],
        input="sk-ant-xxx\n",
    )
    assert result.exit_code == 0
    assert store.list_keys()[0].env_vars == ["ANTHROPIC_API_KEY"]


def test_add_x_api_key_style(isolated_env: Path) -> None:
    result = runner.invoke(
        app,
        ["add", "anthropic", "--endpoint", "api.anthropic.com", "--auth-style", "x-api-key"],
        input="sk-ant-xxx\n",
    )
    assert result.exit_code == 0, result.stdout
    assert "x-api-key" in result.stdout
    entry = store.list_keys()[0]
    assert entry.auth_style == "x-api-key"


def test_add_rejects_invalid_auth_style(isolated_env: Path) -> None:
    result = runner.invoke(
        app,
        ["add", "foo", "--endpoint", "api.foo.com", "--auth-style", "basic"],
        input="secret\n",
    )
    assert result.exit_code == 2
    assert "bearer" in result.stderr
    assert store.list_keys() == []


def test_default_auth_style_is_bearer(isolated_env: Path) -> None:
    runner.invoke(app, ["add", "openai", "--endpoint", "api.openai.com"], input="sk-x\n")
    assert store.list_keys()[0].auth_style == "bearer"
