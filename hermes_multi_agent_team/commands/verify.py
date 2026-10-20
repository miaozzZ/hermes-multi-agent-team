"""verify command — check team setup completeness."""

from __future__ import annotations

import re
import sys

import click

from hermes_multi_agent_team.utils.gateway import gateway_status
from hermes_multi_agent_team.utils.profile import (
    DEFAULT_PROFILE_ENV_LABEL,
    get_hermes_home,
    get_profile_dir,
    list_all_profile_names,
    list_team_profiles,
    profile_served_by_host,
    read_default_env,
    read_env,
    read_soul,
)

# Required .env keys
REQUIRED_ENV_KEYS = [
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
]

# Recommended .env keys
RECOMMENDED_ENV_KEYS = [
    "FEISHU_DOMAIN",
    "FEISHU_CONNECTION_MODE",
    "FEISHU_GROUP_POLICY",
    "FEISHU_ALLOW_BOTS",
    "FEISHU_REQUIRE_MENTION",
]


def _check_profile(profile_name: str) -> dict[str, tuple[bool, str]]:
    """Run all checks for a single profile. Returns check_name → (pass, detail)."""
    checks: dict[str, tuple[bool, str]] = {}

    # 1. Profile directory exists
    profile_dir = get_profile_dir(profile_name)
    checks["profile_dir"] = (
        profile_dir.is_dir(),
        str(profile_dir),
    )

    # 2. .env exists and has required keys
    env = read_env(profile_name)
    missing_required = [k for k in REQUIRED_ENV_KEYS if not env.get(k)]
    missing_recommended = [k for k in RECOMMENDED_ENV_KEYS if not env.get(k)]

    if env:
        if missing_required:
            checks["env_file"] = (False, f"missing required: {', '.join(missing_required)}")
        else:
            checks["env_file"] = (True, "OK")
    elif (get_profile_dir(profile_name) / ".env").exists():
        # read_env returns {} for an unreadable file (permissions/encoding).
        checks["env_file"] = (False, ".env unreadable or empty")
    else:
        checks["env_file"] = (False, ".env not found")

    if missing_recommended:
        checks["env_recommended"] = (
            False,
            f"missing recommended: {', '.join(missing_recommended)}",
        )
    else:
        checks["env_recommended"] = (True, "OK")

    # 2.5 Group policy sanity: allowlist with an empty list rejects ALL group
    # messages (README pitfall #6) — group chats go silent for this bot.
    # Hermes lowercases the policy value and strips whitespace (Feishu adapter),
    # and its _id_set splits the allowlist on commas dropping blank entries —
    # mirror both rules, so "Allowlist" or a whitespace-only list is caught too.
    group_policy = (env.get("FEISHU_GROUP_POLICY") or "").strip().lower()
    allowed_users = env.get("FEISHU_ALLOWED_USERS") or ""
    allowlist = {user.strip() for user in allowed_users.split(",") if user.strip()}
    if group_policy == "allowlist" and not allowlist:
        checks["group_policy"] = (
            False,
            (
                "FEISHU_GROUP_POLICY=allowlist with an empty FEISHU_ALLOWED_USERS "
                "rejects every group message"
            ),
        )
    else:
        checks["group_policy"] = (True, "OK")

    # 3. SOUL.md exists
    soul = read_soul(profile_name)
    checks["soul_md"] = (bool(soul), "OK" if soul else "SOUL.md not found or empty")

    # 4. SOUL.md has real open_ids (not placeholders)
    if soul:
        placeholder_pattern = re.compile(r'user_id="ou_xxx[^"]*"')
        has_placeholders = bool(placeholder_pattern.search(soul))
        real_id_pattern = re.compile(r'user_id="(ou_[a-zA-Z0-9]+)"')
        real_ids = set(real_id_pattern.findall(soul)) - {
            "ou_xxx_pm",
            "ou_xxx_fe",
            "ou_xxx_be",
            "ou_xxx_qa",
            "ou_xxx_ui",
        }

        if has_placeholders and not real_ids:
            checks["open_ids"] = (False, "SOUL.md still has placeholder open_ids")
        elif real_ids:
            checks["open_ids"] = (True, f"found {len(real_ids)} open_id(s)")
        else:
            checks["open_ids"] = (False, "no open_ids found in SOUL.md")
    else:
        checks["open_ids"] = (False, "no SOUL.md")

    # 5. Gateway connection
    gw = gateway_status(profile_name)
    pid = gw["pid"]
    connected = gw["connected"]

    if pid:
        checks["gateway_running"] = (True, f"PID {pid}")
    else:
        checks["gateway_running"] = (False, "not running")

    if connected:
        checks["gateway_connected"] = (True, "feishu connected")
    else:
        checks["gateway_connected"] = (False, "not connected")

    return checks


def _check_duplicate_app_ids(profiles: list[str], prefix: str) -> list[tuple[str, list[str]]]:
    """Find Feishu App IDs shared by multiple profiles.

    The host gateway serves every named profile under profiles/ (not just this
    prefix) plus the default profile's ~/.hermes/.env — all of them are scanned
    so verify reaches the same verdict as `start`'s credential check.

    Returns a list of (masked_app_id, owner_names) duplicates.
    """
    app_owners: dict[str, list[str]] = {}
    team_profiles = set(profiles)

    default_app_id = read_default_env().get("FEISHU_APP_ID")
    if default_app_id:
        app_owners.setdefault(default_app_id, []).append(DEFAULT_PROFILE_ENV_LABEL)

    for other in list_all_profile_names():
        if other in team_profiles or not profile_served_by_host(other):
            continue
        app_id = read_env(other).get("FEISHU_APP_ID")
        if app_id:
            app_owners.setdefault(app_id, []).append(f"{other} (outside prefix '{prefix}')")

    for profile_name in profiles:
        app_id = read_env(profile_name).get("FEISHU_APP_ID")
        if app_id:
            app_owners.setdefault(app_id, []).append(profile_name)
    return [
        (_mask_app_id(app_id), names)
        for app_id, names in sorted(app_owners.items())
        if len(names) > 1
    ]


def _mask_app_id(app_id: str) -> str:
    if len(app_id) > 10:
        return app_id[:6] + "****" + app_id[-4:]
    return app_id


def verify_team(prefix: str) -> None:
    """Verify team setup: gateways, .env, SOUL.md open_ids."""
    profiles = list_team_profiles(prefix)

    if not profiles:
        raise click.ClickException(
            f"❌ No profiles found with prefix '{prefix}'. Run 'hermes-team init' first."
        )

    click.echo(f"\n✅ Verifying {len(profiles)} profile(s) with prefix '{prefix}'\n")

    all_pass = True
    profile_results: dict[str, dict[str, tuple[bool, str]]] = {}

    for profile_name in profiles:
        results = _check_profile(profile_name)
        profile_results[profile_name] = results

        profile_pass = all(ok for ok, _ in results.values())
        if not profile_pass:
            all_pass = False

        # Display results
        status_icon = "✅" if profile_pass else "❌"
        click.echo(f"{status_icon} {profile_name}")

        for check_name, (ok, detail) in results.items():
            icon = "✅" if ok else "❌"
            click.echo(f"   {icon} {check_name}: {detail}")
        click.echo()

    # Team-level check: one Feishu app per agent (the gateway parks duplicates).
    # Duplicates can involve profiles OUTSIDE this prefix (other teams, the
    # default profile) — those still block `start`, so they must surface here.
    duplicates = _check_duplicate_app_ids(profiles, prefix)
    team_profiles = set(profiles)
    duplicate_profiles: set[str] = set()
    duplicate_outside_owners: set[str] = set()
    if duplicates:
        all_pass = False
        click.echo("❌ Duplicate Feishu App IDs — each agent needs its own app:")
        for masked, names in duplicates:
            for owner in names:
                if owner in team_profiles:
                    duplicate_profiles.add(owner)
                else:
                    duplicate_outside_owners.add(owner)
            click.echo(f"   {masked}: {', '.join(names)}")
        click.echo()

    # start's uniqueness scan reads the default profile's .env too — when it
    # cannot be read that scan runs blind, and the user should know here.
    default_env_path = get_hermes_home() / ".env"
    default_env_unreadable = default_env_path.exists() and not read_default_env()
    if default_env_unreadable:
        all_pass = False
        click.echo(
            f"❌ {DEFAULT_PROFILE_ENV_LABEL} exists but is unreadable or empty — "
            "start's App-ID uniqueness scan cannot see it. "
            "Fix its permissions/encoding."
        )
        click.echo()

    # Summary
    click.echo("=" * 60)
    if all_pass:
        click.echo("🎉 ALL CHECKS PASSED! Your team is ready to go!")
        return

    failed_profiles = [
        name for name, checks in profile_results.items() if not all(ok for ok, _ in checks.values())
    ]
    # Profiles sharing an App ID count as failed even if their own checks passed.
    failed_profiles += [
        name for name in profiles if name in duplicate_profiles and name not in failed_profiles
    ]
    # Outside-prefix owners in a duplicate cannot be listed as team profiles,
    # but they are still part of what blocks `start` — show them here instead
    # of an empty list.
    shown_failures = failed_profiles + sorted(
        owner for owner in duplicate_outside_owners if owner not in failed_profiles
    )
    if default_env_unreadable and DEFAULT_PROFILE_ENV_LABEL not in shown_failures:
        shown_failures.append(DEFAULT_PROFILE_ENV_LABEL)
    click.echo(f"⚠️  Some checks failed for: {', '.join(shown_failures)}")
    click.echo()
    click.echo("🔧 Common fixes:")
    if duplicates:
        click.echo(
            "   - Duplicate App IDs: hermes-team configure --prefix "
            + prefix
            + " (one Feishu app per agent)"
        )
        for owner in sorted(duplicate_outside_owners):
            if owner == DEFAULT_PROFILE_ENV_LABEL:
                click.echo(
                    f"     - {owner}: not managed by configure — edit ~/.hermes/.env directly"
                )
            else:
                name = owner.split(" (", 1)[0]
                click.echo(f"     - {owner}: edit ~/.hermes/profiles/{name}/.env directly")
    if default_env_unreadable:
        click.echo(
            f"   - {DEFAULT_PROFILE_ENV_LABEL}: not readable — fix permissions/encoding "
            "of ~/.hermes/.env (configure cannot manage it)"
        )
    click.echo("   - Missing .env: hermes-team configure --prefix " + prefix)
    click.echo("   - No open_ids: hermes-team collect-ids --prefix " + prefix)
    click.echo("   - Gateway not running: hermes-team start --prefix " + prefix)
    sys.exit(1)
