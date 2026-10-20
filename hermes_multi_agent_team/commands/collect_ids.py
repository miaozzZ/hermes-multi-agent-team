"""collect-ids command — auto-extract open_ids from gateway logs and update SOUL.md."""

from __future__ import annotations

import click

from hermes_multi_agent_team.utils.open_id import (
    extract_open_id_with_names,
    update_soul_md_open_ids,
)
from hermes_multi_agent_team.utils.profile import (
    get_profile_dir,
    list_team_profiles,
    read_soul,
    read_team_metadata,
)

# Legacy fallback for teams created before per-profile metadata existed:
# profile suffix → the name used in SOUL.md @tags.
ROLE_NAME_MAP: dict[str, str] = {
    "pm": "P酱",
    "fe": "F仔",
    "be": "B叔",
    "qa": "Q宝",
    "ui": "U酱",
}


def _agent_name_for_profile(profile_name: str) -> str | None:
    """The SOUL.md @tag name of this profile's agent, or None if unknown.

    Prefers the .hermes-team.json metadata init wrote (custom roles, the
    coordinator); falls back to the builtin suffix table for legacy teams.
    """
    metadata = read_team_metadata(profile_name)
    name = metadata.get("name")
    if isinstance(name, str) and name:
        return name
    parts = profile_name.rsplit("-", 1)
    if len(parts) == 2 and parts[1] in ROLE_NAME_MAP:
        return ROLE_NAME_MAP[parts[1]]
    return None


def collect_team_ids(prefix: str) -> None:
    """Auto-extract Feishu open_ids from gateway logs and update SOUL.md."""
    profiles = list_team_profiles(prefix)
    # Profiles kept on disk via `remove-member --keep-profile` carry a
    # "removed" marker: they are no longer team members, so their logs must
    # not feed the name→open_id mapping nor their SOULs be rewritten.
    profiles = [p for p in profiles if not read_team_metadata(p).get("removed")]

    if not profiles:
        raise click.ClickException(
            f"❌ No profiles found with prefix '{prefix}'. Run 'hermes-team init' first."
        )

    click.echo(f"\n🔍 Collecting open_ids from {len(profiles)} profile(s)")
    click.echo()

    # First pass: collect all bot and user open_ids from all profiles
    all_bots: dict[str, set[str]] = {}  # profile_name → set of bot open_ids
    all_users: dict[str, set[str]] = {}  # profile_name → set of user open_ids

    for profile_name in profiles:
        log_path = get_profile_dir(profile_name) / "logs" / "gateway.log"
        if not log_path.exists():
            click.echo(f"  ⚠️  {profile_name}: no gateway.log found")
            all_bots[profile_name] = set()
            all_users[profile_name] = set()
            continue

        ids = extract_open_id_with_names(log_path)
        bot_ids = set(ids["bot"].keys())
        user_ids = set(ids["user"].keys())
        all_bots[profile_name] = bot_ids
        all_users[profile_name] = user_ids

        click.echo(f"  📋 {profile_name}: found {len(bot_ids)} bot(s), {len(user_ids)} user(s)")

    # Build a global mapping: agent name → open_id.
    # Each profile's own bot open_id is that agent's ID (open_ids are per-app,
    # so each agent appears under a different id in every other app's logs —
    # the one id reliably visible in a profile's own log is its own bot).
    global_mapping: dict[str, str] = {}  # name → open_id

    for profile_name in profiles:
        agent_name = _agent_name_for_profile(profile_name)
        if not agent_name:
            click.echo(f"  ⚠️  {profile_name}: could not determine agent name, skipping")
            continue

        bot_ids = all_bots.get(profile_name, set())

        if len(bot_ids) == 1:
            # Single bot — this is the agent's own bot
            global_mapping[agent_name] = bot_ids.pop()
            click.echo(f"  ✅ {agent_name} → {global_mapping[agent_name]}")
        elif len(bot_ids) > 1:
            click.echo(f"  ⚠️  {profile_name}: multiple bot IDs found, using first one")
            global_mapping[agent_name] = min(bot_ids)
        else:
            click.echo(f"  ⚠️  {profile_name}: no bot IDs found in logs")

    if not global_mapping:
        click.echo(
            "\n❌ No open_ids found! Make sure gateways are running and have received messages."
        )
        click.echo("   Tips:")
        click.echo("   - Send a message in the Feishu group to trigger bot responses")
        click.echo("   - Wait a minute for logs to accumulate")
        click.echo(f"   - Check logs: ~/.hermes/profiles/{prefix}-*/logs/gateway.log")
        return

    click.echo(f"\n📊 Collected {len(global_mapping)} open_id mapping(s):")
    for name, oid in global_mapping.items():
        click.echo(f"  {name}: {oid}")

    # Second pass: update SOUL.md in each profile
    click.echo("\n📝 Updating SOUL.md files...")
    updated_count = 0

    for profile_name in profiles:
        soul_content = read_soul(profile_name)
        if not soul_content:
            click.echo(f"  ⚠️  {profile_name}: no SOUL.md found")
            continue

        if "【飞书@方式】" not in soul_content:
            click.echo(f"  ⚠️  {profile_name}: SOUL.md has no 【飞书@方式】 section")
            continue

        ok = update_soul_md_open_ids(
            get_profile_dir(profile_name) / "SOUL.md",
            global_mapping,
        )
        if ok:
            click.echo(f"  ✅ {profile_name}: SOUL.md updated")
            updated_count += 1
        else:
            click.echo(f"  ⚠️  {profile_name}: failed to update SOUL.md")

    click.echo(f"\n✅ Done! Updated {updated_count}/{len(profiles)} SOUL.md files")

    if updated_count < len(profiles):
        missing = len(profiles) - updated_count
        click.echo(f"   ⚠️  {missing} profile(s) could not be updated")
        click.echo("   You may need to manually set open_ids in their SOUL.md")

    click.echo(f"\n📋 Next step: hermes-team verify --prefix {prefix}")
