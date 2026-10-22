"""Main CLI entry point for hermes-multi-agent-team."""

import re

import click

from hermes_multi_agent_team import __version__

_CHAT_ID_RE = re.compile(r"^oc_[0-9A-Za-z]+$")


def _prefix_param(ctx: click.Context, param: click.Parameter, value: str | None) -> str | None:
    """Entry gate for every --prefix value: non-empty after stripping.

    An empty/blank prefix would otherwise flow into list_team_profiles and
    match OTHER teams' profiles ("" startswith-matches everything; " "
    matches any name with a leading space) — remove-member/destroy would
    target them. Stripping matches validate_prefix's normalization.
    """
    if value is None:
        return value
    cleaned = value.strip()
    if not cleaned:
        raise click.BadParameter(
            "must be a non-empty string (an empty prefix would match other teams' profiles)"
        )
    return cleaned


def _chat_id_param(ctx: click.Context, param: click.Parameter, value: str | None) -> str | None:
    """Entry gate for --chat-id: must be a Feishu chat id (oc_ + alnum).

    Anything else (spaces, quotes, a pasted URL fragment…) is rejected here
    with a usage error — it would otherwise reach http.client as a malformed
    URL and crash the command with an InvalidURL traceback.
    """
    if value is None:
        return value
    cleaned = value.strip()
    if not _CHAT_ID_RE.match(cleaned):
        raise click.BadParameter(
            "must be a Feishu chat id like oc_xxxxxxxxx (letters/digits only, no spaces)"
        )
    return cleaned


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
@click.option("--team-name", default=None, help="Name for the agent team.")
@click.option(
    "--roles",
    default=None,
    help="Comma-separated role keys, a subset of the team's roles (default: all of them).",
)
@click.option(
    "--prefix",
    default=None,
    callback=_prefix_param,
    help="Profile name prefix (default: team name).",
)
@click.option("--clone-from", default=None, help="Clone model config from this profile.")
@click.option(
    "--config",
    "config",
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="Team config JSON defining custom roles/names/templates (see examples/).",
)
@click.option("--dry-run", is_flag=True, help="Show what would be created without doing it.")
def init(
    team_name: str | None,
    roles: str | None,
    prefix: str | None,
    clone_from: str | None,
    config: str | None,
    dry_run: bool,
) -> None:
    """🏗️  Create Hermes profiles and generate SOUL.md for each team role."""
    from hermes_multi_agent_team.commands.init import init_team

    init_team(
        team_name=team_name,
        roles=roles,
        prefix=prefix,
        clone_from=clone_from,
        dry_run=dry_run,
        config=config,
    )


@cli.command()
@click.option(
    "--prefix", required=True, callback=_prefix_param, help="Profile name prefix to configure."
)
@click.option("--dry-run", is_flag=True, help="Show what would be written without writing.")
def configure(prefix: str, dry_run: bool) -> None:
    """⚙️  Interactively configure .env for each team profile."""
    from hermes_multi_agent_team.commands.configure import configure_team

    configure_team(prefix=prefix, dry_run=dry_run)


@cli.command()
@click.option("--prefix", required=True, callback=_prefix_param, help="Profile name prefix.")
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
@click.option("--prefix", required=True, callback=_prefix_param, help="Profile name prefix.")
@click.option(
    "--via-api",
    is_flag=True,
    help="Read group message history via the Feishu API with each profile's own app "
    "credentials (complete mentions, no new messages needed; needs the "
    "im:message.group_msg scope — the tool prints a one-click grant link if missing).",
)
@click.option(
    "--chat-id",
    default=None,
    callback=_chat_id_param,
    help="Group chat id (oc_xxx) for --via-api; default: latest GROUP chat_id in "
    "each profile's gateway log (any chat id only when no group line exists).",
)
def collect_ids(prefix: str, via_api: bool, chat_id: str | None) -> None:
    """🔍 Fill each profile's SOUL.md open_ids from its own logs (or the API)."""
    if chat_id is not None and not via_api:
        # Fail fast instead of silently ignoring: --chat-id only feeds the
        # --via-api history request, and a caller passing it without the flag
        # believes the API route ran when only logs were parsed.
        raise click.UsageError(
            "--chat-id only applies together with --via-api; add --via-api or drop --chat-id"
        )
    from hermes_multi_agent_team.commands.collect_ids import collect_team_ids

    collect_team_ids(prefix=prefix, via_api=via_api, chat_id=chat_id)


@cli.command("add-member")
@click.option(
    "--prefix", required=True, callback=_prefix_param, help="Profile name prefix of the team."
)
@click.option("--key", required=True, help="Role key (becomes profile name <prefix>-<key>).")
@click.option("--name", required=True, help="Display name used in SOUL.md @tags (must be unique).")
@click.option("--role", required=True, help="Job title.")
@click.option("--nickname", default=None, help="Nickname (default: same as --name).")
@click.option(
    "--template",
    default=None,
    help="SOUL template: a file path or a builtin name "
    "(pm/frontend/backend/qa/designer/coordinator); default: the builtin template for --key, if any.",
)
@click.option("--clone-from", default=None, help="Clone model config from this profile.")
@click.option("--dry-run", is_flag=True, help="Show what would change without doing it.")
def add_member(
    prefix: str,
    key: str,
    name: str,
    role: str,
    nickname: str | None,
    template: str | None,
    clone_from: str | None,
    dry_run: bool,
) -> None:
    """➕ Add a member to an existing team (syncs every member's SOUL roster)."""
    from hermes_multi_agent_team.commands.member import add_member as add_member_impl

    add_member_impl(
        prefix=prefix,
        key=key,
        name=name,
        role=role,
        nickname=nickname,
        template=template,
        clone_from=clone_from,
        dry_run=dry_run,
    )


@cli.command("remove-member")
@click.option(
    "--prefix", required=True, callback=_prefix_param, help="Profile name prefix of the team."
)
@click.option("--key", required=True, help="Role key of the member to remove.")
@click.option(
    "--keep-profile",
    is_flag=True,
    help="Keep the Hermes profile (only remove it from the team roster and SOULs).",
)
@click.option("--force", is_flag=True, help="Skip the removal confirmation prompt.")
@click.option("--dry-run", is_flag=True, help="Show what would change without doing it.")
def remove_member(prefix: str, key: str, keep_profile: bool, force: bool, dry_run: bool) -> None:
    """➖ Remove a member from a team (deletes their profile unless --keep-profile)."""
    from hermes_multi_agent_team.commands.member import remove_member as remove_member_impl

    remove_member_impl(
        prefix=prefix, key=key, keep_profile=keep_profile, force=force, dry_run=dry_run
    )


@cli.command("new-config")
@click.argument("output_path", required=False)
def new_config(output_path: str | None) -> None:
    """🪄 Interactively build a team config JSON (then run init --config with it)."""
    from hermes_multi_agent_team.commands.wizard import run_wizard

    run_wizard(output_path)


@cli.command("new-bot")
@click.argument("name")
@click.option("--display-name", default=None, help="Persona display name (default: same as NAME).")
@click.option(
    "--description",
    default=None,
    help="One-line function description (prompted when omitted).",
)
@click.option(
    "--template",
    default=None,
    help="SOUL template: a file path or the builtin roster-free 'bot' template (default). "
    "Team templates (pm/frontend/…) need a team roster and are rejected here.",
)
@click.option("--clone-from", default=None, help="Clone model config from this profile.")
@click.option("--dry-run", is_flag=True, help="Show what would be created without doing it.")
def new_bot(
    name: str,
    display_name: str | None,
    description: str | None,
    template: str | None,
    clone_from: str | None,
    dry_run: bool,
) -> None:
    """🤖 Create a standalone single-function agent (no team, served by the host gateway)."""
    from hermes_multi_agent_team.commands.bot import new_bot as new_bot_impl

    new_bot_impl(
        name=name,
        display_name=display_name,
        description=description,
        template=template,
        clone_from=clone_from,
        dry_run=dry_run,
    )


@cli.command()
@click.option("--prefix", required=True, callback=_prefix_param, help="Profile name prefix.")
def verify(prefix: str) -> None:
    """✅ Verify team setup: gateways, .env, SOUL.md open_ids."""
    from hermes_multi_agent_team.commands.verify import verify_team

    verify_team(prefix=prefix)


@cli.command()
@click.option("--prefix", required=True, callback=_prefix_param, help="Profile name prefix.")
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
@click.option(
    "--prefix", required=True, callback=_prefix_param, help="Profile name prefix to destroy."
)
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
def destroy(prefix: str, force: bool) -> None:
    """🗑️  Remove team profiles (with confirmation)."""
    from hermes_multi_agent_team.commands.destroy import destroy_team

    destroy_team(prefix=prefix, force=force)


if __name__ == "__main__":
    cli()
