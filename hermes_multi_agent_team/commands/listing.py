"""list command — one overview of every team and standalone bot on this machine.

Teams are grouped by the prefix recorded in each profile's metadata. Profiles
without usable metadata (none at all, or none with a recorded prefix) fall
back to name-based grouping in a separate legacy section. Standalone bots
(new-bot) and kept-but-removed profiles (remove-member --keep-profile, shown
in their own section and excluded from team member counts) also get their own
sections, so `list` doubles as a "what is running on this host" inventory.
"""

from __future__ import annotations

import click

from hermes_multi_agent_team.utils.gateway import gateway_status
from hermes_multi_agent_team.utils.profile import (
    get_profiles_dir,
    list_all_profile_names,
    read_team_metadata,
    team_metadata_corrupt,
)


def _infer_prefix(profile_name: str) -> str:
    """Grouping key for profiles without recorded metadata."""
    parts = profile_name.rsplit("-", 1)
    return parts[0] if len(parts) == 2 else profile_name


def run_list() -> None:
    """Show every team (by prefix) and standalone bot on this host."""
    profiles = list_all_profile_names()
    if not profiles:
        # Real path, not a hardcoded ~/.hermes: HERMES_HOME may point elsewhere.
        click.echo(f"ℹ️  No profiles under {get_profiles_dir()} — run `hermes-team new-team` first.")
        return

    teams: dict[str, list[str]] = {}
    legacy: dict[str, list[str]] = {}
    standalone: list[str] = []
    removed: dict[str, list[str]] = {}
    corrupt: list[str] = []

    for name in profiles:
        if team_metadata_corrupt(name):
            corrupt.append(name)
            continue
        meta = read_team_metadata(name)
        if meta.get("standalone"):
            standalone.append(name)
        elif meta.get("removed"):
            # Kept on disk by remove-member --keep-profile: no longer a team
            # member (excluded from the Teams counts), but still served by the
            # gateway — give it its own section, don't hide it.
            prefix = str(meta.get("prefix") or _infer_prefix(name))
            removed.setdefault(prefix, []).append(name)
        elif meta.get("prefix"):
            teams.setdefault(str(meta["prefix"]), []).append(name)
        else:
            # No metadata at all, or metadata without a recorded prefix (very
            # old or hand-written): best-effort grouping by profile name.
            legacy.setdefault(_infer_prefix(name), []).append(name)

    running = sum(1 for p in profiles if gateway_status(p)["pid"])
    click.echo(f"\n📋 {len(profiles)} profile(s) on this host ({running} gateway-visible)\n")

    if teams:
        click.echo("🏠 Teams")
        for prefix in sorted(teams):
            members = sorted(teams[prefix])
            click.echo(f"   {prefix}  ({len(members)} profile(s))")
            click.echo(f"     {' '.join(members)}")
        click.echo()

    if removed:
        click.echo("🗑️  Removed from team, kept on disk (remove-member --keep-profile)")
        for prefix in sorted(removed):
            entries = [f"{name} (removed, kept)" for name in sorted(removed[prefix])]
            click.echo(f"   {prefix}: {' '.join(entries)}")
        click.echo()

    if legacy:
        click.echo("🗂️  Legacy / unclassified (no/unusable metadata — grouped by name)")
        for prefix in sorted(legacy):
            click.echo(f"   {prefix}?: {' '.join(sorted(legacy[prefix]))}")
        click.echo()

    if standalone:
        click.echo("🤖 Standalone bots (new-bot)")
        for name in sorted(standalone):
            meta = read_team_metadata(name)
            desc = str(meta.get("role") or "").strip()
            suffix = f" — {desc}" if desc else ""
            click.echo(f"   {name}{suffix}")
        click.echo()

    if corrupt:
        click.echo("⚠️  Unreadable metadata (skipped by team commands)")
        for name in sorted(corrupt):
            click.echo(f"   {name}")
        click.echo()

    click.echo("💡 Per-team status: hermes-team status --prefix <prefix>")
