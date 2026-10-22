"""status command — overview of team status."""

from __future__ import annotations

import time

import click

from hermes_multi_agent_team.utils.gateway import gateway_status
from hermes_multi_agent_team.utils.profile import (
    get_profile_dir,
    list_team_profiles,
    read_env,
)


def _format_time_ago(timestamp: float | None) -> str:
    """Format a timestamp as a human-readable 'X ago' string."""
    if timestamp is None:
        return "unknown"
    delta = time.time() - timestamp
    if delta < 60:
        return f"{int(delta)}s ago"
    elif delta < 3600:
        return f"{int(delta / 60)}m ago"
    elif delta < 86400:
        return f"{int(delta / 3600)}h ago"
    else:
        return f"{int(delta / 86400)}d ago"


def _get_profile_mod_time(profile_name: str) -> float | None:
    """Get the last modification time of a profile's key files."""
    profile_dir = get_profile_dir(profile_name)
    times: list[float] = []
    for fname in ("SOUL.md", ".env", "config.yaml"):
        fpath = profile_dir / fname
        if fpath.exists():
            times.append(fpath.stat().st_mtime)
    return max(times) if times else None


def team_status(prefix: str) -> None:
    """Show team status overview."""
    profiles = list_team_profiles(prefix)

    if not profiles:
        raise click.ClickException(
            f"❌ No profiles found with prefix '{prefix}'. Run 'hermes-team new-team' first."
        )

    click.echo(f"\n📊 Team Status — prefix: '{prefix}'")
    click.echo(f"   Found {len(profiles)} profile(s)\n")

    # Table header
    click.echo(
        f"   {'Profile':<20} {'Gateway':<12} {'Connected':<12} {'PID':<8} {'Last Active':<15}"
    )
    click.echo("   " + "─" * 67)

    running_count = 0
    connected_count = 0

    for profile_name in profiles:
        gw = gateway_status(profile_name)
        pid = gw["pid"]
        connected = gw["connected"]
        last_time = gw["last_message_time"]

        if pid:
            running_count += 1
        if connected:
            connected_count += 1

        gw_icon = "🟢" if pid else "⚫"
        conn_icon = "✅" if connected else "❌"
        pid_str = str(pid) if pid else "—"
        time_str = last_time if last_time else "—"

        click.echo(
            f"   {profile_name:<20} {gw_icon} {'running':<10} {conn_icon:<12} {pid_str:<8} {time_str:<15}"
        )

    click.echo("   " + "─" * 67)
    click.echo()
    click.echo("   📈 Summary:")
    click.echo(f"      Profiles:  {len(profiles)}")
    click.echo(f"      Running:   {running_count}/{len(profiles)}")
    click.echo(f"      Connected: {connected_count}/{len(profiles)}")

    # Show .env status
    click.echo()
    click.echo(f"   {'Profile':<20} {'App ID':<25} {'Domain':<15}")
    click.echo("   " + "─" * 60)

    for profile_name in profiles:
        env = read_env(profile_name)
        app_id = env.get("FEISHU_APP_ID", "")
        domain = env.get("FEISHU_DOMAIN", "")

        if app_id:
            # Mask middle of app ID for security
            masked = app_id[:6] + "****" + app_id[-4:] if len(app_id) > 10 else app_id
        else:
            masked = "⚠️ not set"

        click.echo(f"   {profile_name:<20} {masked:<25} {domain or '—':<15}")

    click.echo()
    click.echo("💡 Quick commands:")
    click.echo(f"   hermes-team configure --prefix {prefix}   # Configure .env")
    click.echo(f"   hermes-team start --prefix {prefix}       # Start gateways")
    click.echo(f"   hermes-team collect-ids --prefix {prefix}  # Extract open_ids")
    click.echo(f"   hermes-team verify --prefix {prefix}       # Full verification")
