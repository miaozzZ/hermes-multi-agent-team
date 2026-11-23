"""Tests for CLI entry point."""

from click.testing import CliRunner

from hermes_multi_agent_team import __version__
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
    assert __version__ in result.output


def test_cli_lists_all_commands():
    """CLI help should list all 13 commands."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    for cmd in [
        "new-team",
        "configure",
        "start",
        "collect-ids",
        "list",
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


def test_cli_help_hides_init_alias():
    """The init → new-team rename must not resurface anywhere in --help: the
    alias is registered hidden, and no command description should still tell
    users to run the retired name.

    The group-level --help TRUNCATES long command descriptions (a "then run
    init --config" tail would show as "…(then run..."), so each command's own
    --help is checked too — that is where a full docstring becomes visible.
    """
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert cli.commands["init"].hidden
    assert "init" not in result.output

    for name, command in cli.commands.items():
        if getattr(command, "hidden", False):
            continue
        sub = runner.invoke(cli, [name, "--help"])
        assert sub.exit_code == 0, name
        assert "init" not in sub.output, f"{name} --help mentions the retired alias"


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
