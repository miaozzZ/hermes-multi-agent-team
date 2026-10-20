"""start command — start the gateway serving all team profiles.

Since Hermes 0.19 the gateway is multiplexed by default: a single host gateway
process serves every profile on the machine, and per-profile gateways are
refused (exit 78). This command therefore installs/starts the host gateway
once after validating that every team profile has its own Feishu credentials.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import click

from hermes_multi_agent_team.utils.gateway import find_hermes_bin, get_hermes_version
from hermes_multi_agent_team.utils.profile import (
    DEFAULT_PROFILE_ENV_LABEL,
    get_hermes_home,
    list_all_profile_names,
    list_team_profiles,
    profile_served_by_host,
    read_default_env,
    read_env,
)

# Hermes 0.19 introduced the multiplexed gateway (gateway.multiplex_profiles=true).
MULTIPLEX_MIN_VERSION = (0, 19, 0)


def _run_cmd(cmd: list[str], dry_run: bool, timeout: int = 120) -> bool:
    """Run a hermes CLI command. Returns True on success."""
    cmd_str = " ".join(cmd)

    if dry_run:
        click.echo(f"  💨 dry-run: {cmd_str}")
        return True

    click.echo(f"  🔧 {cmd_str}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except OSError:
        # FileNotFoundError, PermissionError (path exists but not executable), …
        click.echo(f"  ❌ Could not run Hermes binary: {cmd[0]}")
        return False
    except subprocess.TimeoutExpired:
        click.echo("  ❌ Command timed out")
        return False

    if result.returncode == 0:
        return True
    click.echo(f"  ⚠️  Exit code {result.returncode}")
    if result.stderr:
        click.echo(f"     {result.stderr.strip()}")
    if result.stdout:
        click.echo(f"     {result.stdout.strip()}")
    return False


def _validate_team_credentials(prefix: str, profiles: list[str]) -> list[str]:
    """Check every profile has complete and unique Feishu credentials."""
    problems: list[str] = []
    app_owner: dict[str, str] = {}

    # The host multiplex gateway serves EVERY named profile under profiles/
    # (Hermes' profiles_to_serve) — not just the current team's. Seed owners
    # from profiles outside this prefix (skipping parked/standalone ones, which
    # the host skips too) plus the default profile, so a shared App ID with any
    # of them is caught before the gateway parks an agent.
    for other in list_all_profile_names():
        if other in profiles or not profile_served_by_host(other):
            continue
        other_app_id = read_env(other).get("FEISHU_APP_ID")
        if other_app_id:
            app_owner[other_app_id] = f"{other} (outside prefix '{prefix}')"

    # The default profile's .env lives in ~/.hermes/.env (outside profiles/);
    # verify's duplicate check reads the same file, so both commands agree.
    default_app_id = read_default_env().get("FEISHU_APP_ID")
    if default_app_id:
        app_owner[default_app_id] = DEFAULT_PROFILE_ENV_LABEL
    elif (get_hermes_home() / ".env").exists():
        click.echo(
            "  ⚠️  ~/.hermes/.env exists but is unreadable or empty — its App ID is "
            "NOT included in the uniqueness scan. Fix its permissions/encoding."
        )

    for name in profiles:
        env = read_env(name)
        app_id = env.get("FEISHU_APP_ID")
        app_secret = env.get("FEISHU_APP_SECRET")

        if not app_id or not app_secret:
            problems.append(
                f"  ❌ {name}: missing FEISHU_APP_ID / FEISHU_APP_SECRET — "
                f"run `hermes-team configure --prefix {prefix}`"
            )
            continue

        if app_id in app_owner:
            problems.append(
                f"  ❌ {name}: FEISHU_APP_ID already used by '{app_owner[app_id]}' — "
                "each agent needs its own Feishu app (the gateway refuses/parks "
                "profiles sharing one app_id)"
            )
        else:
            app_owner[app_id] = name

    return problems


def _require_valid_credentials(prefix: str, profiles: list[str]) -> None:
    """Abort startup unless every profile has complete and unique Feishu credentials."""
    problems = _validate_team_credentials(prefix, profiles)
    if problems:
        for problem in problems:
            click.echo(problem)
        raise click.ClickException(
            f"❌ {len(problems)} credential problem(s) found. Fix them before starting the gateway."
        )


def _start_multiplex(prefix: str, profiles: list[str], hermes_bin: str, dry_run: bool) -> bool:
    """Install and start the host gateway serving all profiles."""
    _require_valid_credentials(prefix, profiles)

    click.echo(f"\n🌐 Multiplexed mode: one host gateway will serve all {len(profiles)} profile(s)")

    for action in ("install", "start"):
        if not _run_cmd([hermes_bin, "gateway", action], dry_run):
            click.echo(f"  ❌ Host gateway {action} failed")
            return False

    if not dry_run:
        status_output = ""
        try:
            result = subprocess.run(
                [hermes_bin, "gateway", "status"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass  # install/start already succeeded — don't fail the command on status
        else:
            if result.returncode == 0:
                status_output = result.stdout.strip()
        if status_output:
            click.echo(f"\n📊 Gateway status:\n{status_output}")
        else:
            click.echo(
                "\nℹ️  Could not read `hermes gateway status` (timed out or failed); "
                "run it manually to inspect the host gateway."
            )

    click.echo("\n💡 Notes:")
    click.echo("   - New or edited profiles are picked up automatically (~30s rescan).")
    click.echo("   - Run `hermes gateway restart` to reload .env changes immediately.")
    click.echo("   - Park one agent without touching the rest: `hermes -p <profile> gateway stop`")
    return True


def _start_standalone(prefix: str, profiles: list[str], hermes_bin: str, dry_run: bool) -> bool:
    """Legacy mode: install and start one gateway per profile (Hermes < 0.19)."""
    # Same validation as multiplex mode: a bad credential fails more obscurely
    # here (old Hermes has no gateway-side backstop), so catch it up front.
    _require_valid_credentials(prefix, profiles)
    results: dict[str, bool] = {}

    for profile_name in profiles:
        click.echo(f"👤 {profile_name}")

        ok = True
        for action in ("install", "start"):
            if not _run_cmd([hermes_bin, "--profile", profile_name, "gateway", action], dry_run):
                click.echo(f"  ❌ Gateway {action} failed for {profile_name}")
                ok = False
                break

        results[profile_name] = ok
        if ok:
            click.echo(f"  ✅ Gateway started for {profile_name}")
        if ok and not dry_run:
            time.sleep(2)

    success = sum(1 for v in results.values() if v)
    failed = len(results) - success
    if failed:
        click.echo(f"\n✅ {success} gateway(s) started, ❌ {failed} failed")
        return False
    click.echo(f"\n✅ All {success} gateways started successfully!")
    return True


def start_team(prefix: str, dry_run: bool, standalone: bool = False) -> None:
    """Start the gateway serving all team profiles."""
    profiles = list_team_profiles(prefix)

    if not profiles:
        raise click.ClickException(
            f"❌ No profiles found with prefix '{prefix}'. Run 'hermes-team init' first."
        )

    hermes_bin = find_hermes_bin()
    if not Path(hermes_bin).exists() and not dry_run:
        raise click.ClickException(
            f"❌ Hermes binary not found at {hermes_bin}\n   Please install Hermes Agent first."
        )

    version = get_hermes_version(hermes_bin)
    multiplex_capable = version is None or version >= MULTIPLEX_MIN_VERSION

    click.echo(f"\n🔌 Starting gateways for {len(profiles)} profile(s)")
    if dry_run:
        click.echo("   📋 DRY RUN — no commands will be executed")

    use_multiplex = not standalone
    if standalone and multiplex_capable:
        click.echo(
            "\n⚠️  Hermes >= 0.19 refuses per-profile gateways (exit 78) unless the profile's "
            "config.yaml sets `gateway.standalone: true`."
        )
    if use_multiplex and version is not None and version < MULTIPLEX_MIN_VERSION:
        version_str = ".".join(str(n) for n in version)
        click.echo(
            f"\n⚠️  Hermes {version_str} predates the multiplexed gateway (0.19); "
            "falling back to one gateway per profile. Consider `hermes update`."
        )
        use_multiplex = False
    elif use_multiplex and version is None:
        click.echo(
            "\nℹ️  Could not determine the Hermes version; assuming the multiplexed gateway "
            "(default since 0.19). Use --standalone for legacy per-profile gateways."
        )

    if use_multiplex:
        ok = _start_multiplex(prefix, profiles, hermes_bin, dry_run)
    else:
        ok = _start_standalone(prefix, profiles, hermes_bin, dry_run)

    if not ok:
        raise click.ClickException("❌ Gateway startup failed. See output above for details.")

    click.echo("\n📋 Next steps:")
    click.echo("   1. Wait ~30 seconds for connections to establish")
    click.echo(f"   2. hermes-team collect-ids --prefix {prefix}")
    click.echo(f"   3. hermes-team verify --prefix {prefix}")
