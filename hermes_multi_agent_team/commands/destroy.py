"""destroy command — remove team profiles safely."""

from __future__ import annotations

import shutil

import click

from hermes_multi_agent_team.utils.profile import (
    get_profiles_dir,
    is_standalone_profile,
    list_name_ambiguous_profiles,
    list_team_profiles,
    team_metadata_corrupt,
)


def destroy_team(prefix: str, force: bool) -> None:
    """List matching team profiles, confirm, and delete them."""
    profiles = list_team_profiles(prefix)

    # Legacy profiles whose names could belong to a LONGER prefix (e.g.
    # team-extra-pm queried as 'team') are excluded by the listing — say why,
    # or their silence looks like an oversight right before a deletion.
    for name in list_name_ambiguous_profiles(prefix):
        click.echo(
            f"   ⚠️  {name}: name matches '{prefix}-…' but carries no recorded prefix — "
            f"it may belong to team '{name.rsplit('-', 1)[0]}'; NOT deleted. Re-init it "
            "under its own team to record the prefix and remove the ambiguity."
        )

    if not profiles:
        raise click.ClickException(
            f"❌ No profiles found with prefix '{prefix}'. Nothing to destroy."
        )

    # A standalone bot (new-bot) that happens to share the team's prefix is
    # NOT a team member — destroy must never delete it, --force included
    # (verify / collect-ids / add-member / init all skip standalone profiles
    # the same way). Profiles whose .hermes-team.json exists but cannot be
    # parsed fail closed into the same protection: the corrupt file may be
    # hiding a standalone marker.
    standalone: list[str] = []
    corrupt: list[str] = []
    team_profiles: list[str] = []
    for name in profiles:
        if team_metadata_corrupt(name):
            corrupt.append(name)
        elif is_standalone_profile(name):
            standalone.append(name)
        else:
            team_profiles.append(name)

    if not team_profiles:
        raise click.ClickException(
            f"❌ No team profiles match prefix '{prefix}' — refusing to delete "
            f"{', '.join(standalone + corrupt)} (standalone bot(s) and/or profile(s) "
            "with unreadable .hermes-team.json are not team members). Destroy removes "
            f"team profiles only; delete manually with: rm -rf '{get_profiles_dir()}/<name>'"
        )

    profiles_dir = get_profiles_dir()

    click.echo(f"\n🗑️  Destroy Team Profiles — prefix: '{prefix}'")
    click.echo(f"   Found {len(team_profiles)} team profile(s):\n")

    for name in team_profiles:
        pdir = profiles_dir / name
        # Show a rough size hint
        file_count = sum(1 for _ in pdir.rglob("*") if _.is_file()) if pdir.is_dir() else 0
        click.echo(f"   • {name}  ({file_count} files)")

    click.echo()

    for name in standalone:
        click.echo(
            f"   ⏭️  {name}: standalone bot sharing this prefix — NOT deleted "
            f"(remove it manually with: rm -rf '{profiles_dir / name}')"
        )
    for name in corrupt:
        click.echo(
            f"   ⚠️  {name}: unreadable .hermes-team.json — NOT deleted (it may be a "
            f"standalone bot hiding behind the broken file); fix or remove "
            f"'{profiles_dir / name}' manually"
        )
    if standalone or corrupt:
        click.echo()

    # Safety: confirm unless --force
    if not force:
        click.confirm(
            f"⚠️  This will permanently delete {len(team_profiles)} profile(s). Continue?",
            abort=True,
        )

    # Delete
    deleted = []
    for name in team_profiles:
        pdir = profiles_dir / name
        if pdir.is_dir():
            try:
                shutil.rmtree(pdir)
            except OSError as e:
                # Same rule as remove-member's delete mode: swallowing a
                # partial failure would print "Destroyed" for a profile whose
                # data is still on disk. Abort instead — the already-deleted
                # profiles stay deleted (and tombstoned); re-run after
                # resolving the error.
                raise click.ClickException(
                    f"❌ Failed to delete profile directory '{name}': {e}\n"
                    "   The team is only partially destroyed — already-deleted profiles "
                    "stay deleted and tombstoned. Resolve the error and re-run."
                ) from e
            # Tombstone (profiles/.deleted/<name>) — same semantics as
            # remove-member's delete mode and Hermes' own deleted-profile
            # handling: a leftover (e.g. partially deleted) shell must never
            # be listed or served again. Re-init / add-member clear it.
            (profiles_dir / ".deleted" / name).mkdir(parents=True, exist_ok=True)
            deleted.append(name)
            click.echo(f"   🗑️  Deleted: {name}")

    click.echo()
    click.echo(f"✅ Destroyed {len(deleted)} profile(s): {', '.join(deleted)}")
    click.echo()
