"""configure command — interactive .env configuration for team profiles."""

from __future__ import annotations

from dataclasses import dataclass

import click

from hermes_multi_agent_team.utils.profile import (
    list_team_profiles,
    read_env,
    write_env,
)

# Keys written by older versions of this tool that current Hermes no longer
# documents. They are dropped from existing .env files on reconfigure.
# NOTE: FEISHU_ALLOW_ALL_USERS is deliberately NOT listed — Hermes 0.22.x still
# reads and writes it, so deleting it would silently flip profiles that set it
# to true into allowlist-based DM rejection. It is preserved as an unmanaged key.
OBSOLETE_ENV_KEYS = ("FEISHU_DM_POLICY",)

APP_ID_KEY = "FEISHU_APP_ID"
APP_SECRET_KEY = "FEISHU_APP_SECRET"


@dataclass(frozen=True)
class EnvField:
    """One .env entry: how to prompt it and what values are valid."""

    key: str
    prompt: str
    default: str
    secret: bool = False
    choices: tuple[str, ...] | None = None
    confirm: bool = False


# Credential fields are prompted per profile (each agent needs its own Feishu app);
# settings fields describe how the bot behaves and are typically shared by the team.
CREDENTIAL_FIELDS = (
    EnvField(APP_ID_KEY, "Feishu App ID", ""),
    EnvField(APP_SECRET_KEY, "Feishu App Secret", "", secret=True),
)

SETTINGS_FIELDS = (
    EnvField(
        "FEISHU_DOMAIN",
        "Feishu Domain",
        "feishu",
        choices=("feishu", "lark"),
    ),
    EnvField(
        "FEISHU_CONNECTION_MODE",
        "Connection Mode",
        "websocket",
        choices=("websocket", "webhook"),
    ),
    # Hermes defaults FEISHU_GROUP_POLICY to "allowlist", and an empty allowlist
    # rejects every group message — team group chats need "open" to hear anyone.
    EnvField(
        "FEISHU_GROUP_POLICY",
        "Group Policy",
        "open",
        choices=("open", "allowlist", "disabled"),
    ),
    # "all" (not Hermes' default "none") because teammates are bots, and bot @s in
    # plain text are not real mentions, so "mentions" would not catch them either.
    EnvField(
        "FEISHU_ALLOW_BOTS",
        "Allow Bots",
        "all",
        choices=("none", "mentions", "all"),
    ),
    EnvField(
        "FEISHU_REQUIRE_MENTION",
        "Require @mention",
        "false",
        confirm=True,
    ),
)

# FEISHU_ALLOWED_USERS must NOT be shared: open_ids are isolated per Feishu app,
# so one profile's open_id list matches nobody in another app's allowlist —
# sharing it would make every other bot reject all group messages under
# group policy "allowlist". It is therefore prompted per profile.
PER_PROFILE_SETTINGS_FIELDS = (
    EnvField(
        "FEISHU_ALLOWED_USERS",
        "Allowed Users (comma-separated open_ids for THIS app; under group policy "
        "'allowlist' an empty list rejects ALL group messages)",
        "",
    ),
)


def _prompt_field(field: EnvField, current: str) -> str:
    """Prompt for one field, using click validation for choice/confirm fields."""
    label = f"    {field.prompt} ({field.key})"
    if field.confirm:
        value = click.confirm(label, default=current.lower() == "true")
        return str(value).lower()
    if field.choices is not None:
        if current and current.lower() not in field.choices:
            click.echo(
                f"    ⚠️  existing {field.key}='{current}' is not a valid value, "
                f"using default '{field.default}'"
            )
            current = field.default
        value = click.prompt(
            label,
            type=click.Choice(field.choices, case_sensitive=False),
            default=current,
        )
        return str(value).lower()
    return str(click.prompt(label, default=current, hide_input=field.secret))


def _prompt_settings(
    existing: dict[str, str | None], fields: tuple[EnvField, ...] = SETTINGS_FIELDS
) -> dict[str, str]:
    """Prompt for the given settings fields, defaulting to each key's existing value."""
    values: dict[str, str] = {}
    click.echo("\n  ⚙️  Platform settings")
    for field in fields:
        current = existing.get(field.key) or field.default
        values[field.key] = _prompt_field(field, current)
    return values


def _prompt_unique_app_id(
    profile_name: str, existing: dict[str, str | None], used_app_ids: dict[str, str]
) -> str:
    """Prompt for this profile's Feishu App ID, enforcing one app per agent."""
    while True:
        app_id = str(
            click.prompt(
                f"    Feishu App ID for {profile_name}",
                default=existing.get(APP_ID_KEY) or "",
            )
        )
        if not app_id:
            click.echo("    ❌ App ID cannot be empty")
            continue
        owner = used_app_ids.get(app_id)
        if owner is not None and owner != profile_name:
            click.echo(
                f"    ❌ This App ID is already used by '{owner}'. Each agent needs its own "
                "Feishu app — the gateway parks profiles that share one app_id."
            )
            continue
        if not app_id.startswith("cli_"):
            click.echo("    ⚠️  Feishu App IDs usually look like 'cli_xxx'.")
        return app_id


def _prompt_app_secret(profile_name: str, existing: dict[str, str | None]) -> str:
    """Prompt for this profile's Feishu App Secret.

    The default (an existing secret) is never shown — not even as ``[sec1]`` —
    so a real secret can never leak to the terminal or CI logs. Pressing Enter
    keeps the existing secret; a profile without one must get a non-empty value.
    """
    while True:
        value = str(
            click.prompt(
                f"    Feishu App Secret for {profile_name}",
                default=existing.get(APP_SECRET_KEY) or "",
                hide_input=True,
                show_default=False,
            )
        )
        if value:
            return value
        click.echo("    ❌ App Secret cannot be empty")


_SENSITIVE_KEY_MARKERS = ("SECRET", "KEY", "TOKEN", "PASSWORD", "ENCRYPT")


def _is_sensitive_key(key: str) -> bool:
    """Heuristic: keys holding credentials (incl. preserved model API keys)."""
    upper = key.upper()
    return any(marker in upper for marker in _SENSITIVE_KEY_MARKERS)


def configure_team(prefix: str, dry_run: bool) -> None:
    """Interactively configure .env for each team profile."""
    profiles = list_team_profiles(prefix)

    if not profiles:
        raise click.ClickException(
            f"❌ No profiles found with prefix '{prefix}'. Run 'hermes-team init' first."
        )

    click.echo(f"\n⚙️  Configuring {len(profiles)} profile(s) with prefix '{prefix}'")
    click.echo(
        "   ⚠️  Every agent needs its own Feishu app — one app_id can only serve "
        "one Hermes instance."
    )
    if dry_run:
        click.echo("   📋 DRY RUN — no changes will be made")

    share_settings = click.confirm(
        "\n💡 Use the same platform settings (domain/mode/policies) for all profiles?",
        default=True,
    )

    shared_settings: dict[str, str] = {}
    if share_settings:
        shared_settings = _prompt_settings(read_env(profiles[0]))

    configured: dict[str, dict[str, str]] = {}
    used_app_ids: dict[str, str] = {}

    for profile_name in profiles:
        existing = read_env(profile_name)
        click.echo(f"\n  📝 Configuring Feishu credentials for: {profile_name}")

        app_id = _prompt_unique_app_id(profile_name, existing, used_app_ids)
        used_app_ids[app_id] = profile_name
        app_secret = _prompt_app_secret(profile_name, existing)

        env_vars: dict[str, str] = {APP_ID_KEY: app_id, APP_SECRET_KEY: app_secret}
        if share_settings:
            env_vars.update(shared_settings)
            env_vars.update(_prompt_settings(existing, PER_PROFILE_SETTINGS_FIELDS))
        else:
            env_vars.update(
                _prompt_settings(existing, SETTINGS_FIELDS + PER_PROFILE_SETTINGS_FIELDS)
            )

        if env_vars.get("FEISHU_GROUP_POLICY") == "allowlist" and not env_vars.get(
            "FEISHU_ALLOWED_USERS"
        ):
            click.echo(
                f"    ⚠️  {profile_name}: group policy is 'allowlist' but FEISHU_ALLOWED_USERS "
                "is empty — this bot will reject EVERY group message. Fill in open_ids for "
                "this app or switch the policy to 'open'."
            )

        # Preserve keys this tool does not manage (e.g. model API keys) so a
        # reconfigure never wipes them; drop keys Hermes no longer documents.
        for key, value in existing.items():
            if value is None or key in env_vars or key in OBSOLETE_ENV_KEYS:
                continue
            env_vars[key] = value

        configured[profile_name] = env_vars

    click.echo()
    for profile_name, env_vars in configured.items():
        if dry_run:
            click.echo(f"  💨 dry-run: would write .env for {profile_name}")
            for key, value in env_vars.items():
                display_v = "****" if _is_sensitive_key(key) else value
                click.echo(f"     {key}={display_v}")
        else:
            write_env(profile_name, env_vars)
            click.echo(f"  ✅ .env written for {profile_name}")

    click.echo(
        f"\n✅ Configuration complete: {len(configured)}/{len(profiles)} profiles configured"
    )
    click.echo(f"\n📋 Next step: hermes-team start --prefix {prefix}")
