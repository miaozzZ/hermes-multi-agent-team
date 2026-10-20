"""Tests for CLI entry point."""

from click.testing import CliRunner

from hermes_multi_agent_team.cli import cli


def test_cli_help():
    """CLI --help should exit 0 and show usage."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert (
        "hermes-team" in result.output.lower() or "hermes-multi-agent-team" in result.output.lower()
    )


def test_cli_version():
    """CLI --version should show version."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.4.0" in result.output


def test_cli_lists_all_commands():
    """CLI help should list all 7 commands."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    for cmd in [
        "init",
        "configure",
        "start",
        "collect-ids",
        "verify",
        "status",
        "doctor",
        "destroy",
    ]:
        assert cmd in result.output, f"Command '{cmd}' not found in help output"
