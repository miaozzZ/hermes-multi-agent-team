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
    assert "0.8.0" in result.output


def test_cli_lists_all_commands():
    """CLI help should list all 12 commands."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    for cmd in [
        "init",
        "configure",
        "start",
        "collect-ids",
        "new-config",
        "new-bot",
        "add-member",
        "remove-member",
        "verify",
        "status",
        "doctor",
        "destroy",
    ]:
        assert cmd in result.output, f"Command '{cmd}' not found in help output"


def test_cli_rejects_empty_prefix_on_every_command(tmp_hermes_home):
    """An empty --prefix used to flow into list_team_profiles and match every
    team's profiles (remove-member/destroy would target them). Every prefixed
    command must reject it at the entry point instead."""
    runner = CliRunner()
    for command in (
        ["configure", "--prefix", ""],
        ["start", "--prefix", ""],
        ["collect-ids", "--prefix", ""],
        ["add-member", "--prefix", "", "--key", "k", "--name", "N", "--role", "R"],
        ["remove-member", "--prefix", "", "--key", "k"],
        ["verify", "--prefix", ""],
        ["status", "--prefix", ""],
        ["destroy", "--prefix", "", "--force"],
        ["init", "--team-name", "T", "--prefix", "", "--roles", "pm"],
    ):
        result = runner.invoke(cli, command)
        assert result.exit_code == 2, (command, result.output)  # usage error, not a run
        assert "non-empty" in result.output, command

    # A whitespace-only prefix is empty for this purpose too.
    result = runner.invoke(cli, ["verify", "--prefix", "   "])
    assert result.exit_code == 2
    assert "non-empty" in result.output
