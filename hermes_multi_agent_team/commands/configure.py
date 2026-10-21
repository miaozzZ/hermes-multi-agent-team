"""configure command — interactive .env configuration for team profiles."""

from __future__ import annotations

import shlex
from dataclasses import dataclass

import click

from hermes_multi_agent_team.utils.profile import (
    is_standalone_profile,
    list_team_profiles,
    read_env,
    team_metadata_corrupt,
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

# Standalone bots (new-bot) get the opposite default: they should stay quiet
# unless explicitly @-mentioned. Kept as a named field so the shared-settings
# flow can re-prompt it per standalone profile in mixed (team + bot) runs.
_REQUIRE_MENTION_FIELD = EnvField(
    "FEISHU_REQUIRE_MENTION",
    "Require @mention",
    "false",
    confirm=True,
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
    _REQUIRE_MENTION_FIELD,
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
    existing: dict[str, str | None],
    fields: tuple[EnvField, ...] = SETTINGS_FIELDS,
    default_overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Prompt for the given settings fields, defaulting to each key's existing value."""
    overrides = default_overrides or {}
    values: dict[str, str] = {}
    click.echo("\n  ⚙️  Platform settings")
    for field in fields:
        current = existing.get(field.key) or overrides.get(field.key, field.default)
        values[field.key] = _prompt_field(field, current)
    return values


def _bot_like_profile(profile_name: str) -> bool:
    """A standalone bot (new-bot) — or a profile failing closed as one.

    An unreadable .hermes-team.json may hide a standalone marker, so such
    profiles get the bot treatment (standalone mention default, never the
    shared-settings reference) instead of plain team defaults.
    """
    return is_standalone_profile(profile_name) or team_metadata_corrupt(profile_name)


def _standalone_defaults(profile_name: str) -> dict[str, str]:
    """Default overrides for a standalone bot (new-bot).

    Team members listen to every group message (bot @s in plain text are not
    real mentions); a single-function bot is the opposite — it should stay
    quiet unless explicitly @-mentioned. Profiles with unreadable metadata
    fail closed into the same default (_bot_like_profile).
    """
    if _bot_like_profile(profile_name):
        return {"FEISHU_REQUIRE_MENTION": "true"}
    return {}


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
    for name in profiles:
        if team_metadata_corrupt(name):
            # Fail closed: the file may hide a standalone marker, so this
            # profile gets the bot treatment (mention default true, never the
            # shared-settings reference) instead of plain team defaults.
            click.echo(
                f"   ⚠️  {name}: unreadable .hermes-team.json — it may be a standalone "
                "bot; it gets standalone defaults (Require @mention=true)"
            )
    if dry_run:
        click.echo("   📋 DRY RUN — no changes will be made")

    share_settings = click.confirm(
        "\n💡 Use the same platform settings (domain/mode/policies) for all profiles?",
        default=True,
    )

    # Whether EVERY profile in this run is bot-like (standalone, or failing
    # closed as one). The shared mention default flips to true only in that
    # case: in a mixed run (team members + bots sharing the prefix) it must
    # stay the team's false — each bot gets its own mention prompt below
    # instead, so neither side inherits the other's default.
    all_standalone = all(_bot_like_profile(p) for p in profiles)

    shared_settings: dict[str, str] = {}
    if share_settings:
        # Shared settings take their defaults from a TEAM profile when one is
        # present: a standalone bot sorting first may carry a bot-specific
        # FEISHU_REQUIRE_MENTION=true in its .env, which must not leak into
        # the whole team's shared default (same for a corrupt-metadata
        # profile). An all-bot-like run keeps using the first profile and
        # flips the mention default.
        reference = next((p for p in profiles if not _bot_like_profile(p)), profiles[0])
        shared_settings = _prompt_settings(
            read_env(reference),
            default_overrides=_standalone_defaults(reference) if all_standalone else {},
        )

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
            if not all_standalone and _bot_like_profile(profile_name):
                # Mixed run: the shared Require @mention answer defaulted to
                # the team's false — re-ask just this key for the bot-like
                # profile (standalone, or unreadable metadata failing closed)
                # with its own default (true), keeping any value already in
                # its .env.
                current = existing.get("FEISHU_REQUIRE_MENTION") or "true"
                value = click.confirm(
                    f"    Require @mention for standalone bot {profile_name} "
                    f"({_REQUIRE_MENTION_FIELD.key})",
                    default=current.lower() == "true",
                )
                env_vars["FEISHU_REQUIRE_MENTION"] = str(value).lower()
            env_vars.update(_prompt_settings(existing, PER_PROFILE_SETTINGS_FIELDS))
        else:
            env_vars.update(
                _prompt_settings(
                    existing,
                    SETTINGS_FIELDS + PER_PROFILE_SETTINGS_FIELDS,
                    default_overrides=_standalone_defaults(profile_name),
                )
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
            try:
                tightened = write_env(profile_name, env_vars)
            except OSError as e:
                # The user has already answered every prompt — a raw
                # traceback here (e.g. an unwritable directory) hides what
                # failed. Nothing was written for THIS profile; earlier
                # profiles in the loop keep their completed writes.
                raise click.ClickException(
                    f"❌ Could not write {profile_name}/.env: {e}\n"
                    "   Check the directory's permissions (chmod u+w if needed) and "
                    "re-run configure."
                ) from e
            click.echo(f"  ✅ .env written for {profile_name}")
            if tightened:
                # It carries the App Secret — a group/other-readable mode
                # (0644/0664, e.g. from an older version or a manual write)
                # exposes it to other local users on every reconfigure.
                click.echo(
                    f"     🔒 Tightened {profile_name}/.env permissions to 0600 "
                    "(was group/other-readable)"
                )

    click.echo(
        f"\n✅ Configuration complete: {len(configured)}/{len(profiles)} profiles configured"
    )
    click.echo(f"\n📋 Next step: hermes-team start --prefix {shlex.quote(prefix)}")
