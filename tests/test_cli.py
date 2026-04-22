from typer.testing import CliRunner

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
