"""Main CLI entry point for hermes-multi-agent-team."""

import click

from hermes_multi_agent_team import __version__


@click.group()
@click.version_option(version=__version__, prog_name="hermes-team")
def cli() -> None:
    """🚀 hermes-multi-agent-team — Automate multi-agent team setup for Hermes + Feishu.

    Automated setup currently covers Feishu/Lark only: `configure` writes FEISHU_*
    keys and `start` validates Feishu credentials. Other platforms (Telegram,
    Discord, Slack) are supported by Hermes itself but need manual .env editing
    and cannot pass `hermes-team start` credential validation.
    """


# Lazy imports so the CLI starts fast
@cli.command()
@click.option("--team-name", prompt="Team name", help="Name for the agent team.")
@click.option(
    "--roles", default="pm,fe,be,qa,ui", help="Comma-separated role keys (pm,fe,be,qa,ui)."
)
@click.option("--prefix", default=None, help="Profile name prefix (default: team name).")
@click.option("--clone-from", default=None, help="Clone model config from this profile.")
@click.option("--dry-run", is_flag=True, help="Show what would be created without doing it.")
def init(
    team_name: str, roles: str, prefix: str | None, clone_from: str | None, dry_run: bool
) -> None:
    """🏗️  Create Hermes profiles and generate SOUL.md for each team role."""
    from hermes_multi_agent_team.commands.init import init_team

    init_team(
        team_name=team_name, roles=roles, prefix=prefix, clone_from=clone_from, dry_run=dry_run
    )


@cli.command()
@click.option("--prefix", required=True, help="Profile name prefix to configure.")
@click.option("--dry-run", is_flag=True, help="Show what would be written without writing.")
def configure(prefix: str, dry_run: bool) -> None:
    """⚙️  Interactively configure .env for each team profile."""
    from hermes_multi_agent_team.commands.configure import configure_team

    configure_team(prefix=prefix, dry_run=dry_run)


@cli.command()
@click.option("--prefix", required=True, help="Profile name prefix.")
@click.option(
    "--standalone",
    is_flag=True,
    help="Legacy mode: start one gateway per profile (Hermes >= 0.19 requires "
    "gateway.standalone: true in each profile's config.yaml).",
)
@click.option("--dry-run", is_flag=True, help="Show commands without running them.")
def start(prefix: str, standalone: bool, dry_run: bool) -> None:
    """🔌 Start the gateway serving all team profiles (multiplexed since Hermes 0.19)."""
    from hermes_multi_agent_team.commands.start import start_team

    start_team(prefix=prefix, dry_run=dry_run, standalone=standalone)


@cli.command("collect-ids")
@click.option("--prefix", required=True, help="Profile name prefix.")
def collect_ids(prefix: str) -> None:
    """🔍 Auto-extract Feishu open_ids from gateway logs and update SOUL.md."""
    from hermes_multi_agent_team.commands.collect_ids import collect_team_ids

    collect_team_ids(prefix=prefix)


@cli.command()
@click.option("--prefix", required=True, help="Profile name prefix.")
def verify(prefix: str) -> None:
    """✅ Verify team setup: gateways, .env, SOUL.md open_ids."""
    from hermes_multi_agent_team.commands.verify import verify_team

    verify_team(prefix=prefix)


@cli.command()
@click.option("--prefix", required=True, help="Profile name prefix.")
def status(prefix: str) -> None:
    """📊 Show team status overview."""
    from hermes_multi_agent_team.commands.status import team_status

    team_status(prefix=prefix)


@cli.command()
def doctor() -> None:
    """🩺 Check environment dependencies and readiness."""
    from hermes_multi_agent_team.commands.doctor import run_doctor

    run_doctor()


@cli.command()
@click.option("--prefix", required=True, help="Profile name prefix to destroy.")
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
def destroy(prefix: str, force: bool) -> None:
    """🗑️  Remove team profiles (with confirmation)."""
    from hermes_multi_agent_team.commands.destroy import destroy_team

    destroy_team(prefix=prefix, force=force)


if __name__ == "__main__":
    cli()
