"""Profile helper functions for managing Hermes profiles."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from dotenv import dotenv_values


def get_hermes_home() -> Path:
    """Return the Hermes home directory (~/.hermes or $HERMES_HOME)."""
    return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))


def get_profiles_dir() -> Path:
    """Return the Hermes profiles directory."""
    return get_hermes_home() / "profiles"


def get_profile_dir(name: str) -> Path:
    """Return the directory for a specific profile."""
    return get_profiles_dir() / name


def profile_exists(name: str) -> bool:
    """Check whether a Hermes profile directory exists."""
    return get_profile_dir(name).is_dir()


def read_env(name: str) -> dict[str, str | None]:
    """Read .env from a profile directory. Returns dict of key→value (None if unset).

    A .env that cannot be read (permissions, broken encoding) yields {} instead
    of raising — one unreadable profile must not crash a whole-team command.
    """
    env_path = get_profile_dir(name) / ".env"
    if not env_path.exists():
        return {}
    try:
        return dotenv_values(env_path)
    except (OSError, UnicodeError):
        return {}


# The default profile's .env lives in the Hermes home itself (outside profiles/),
# but the host multiplex gateway serves it like any team profile — its App ID
# participates in uniqueness checks.
DEFAULT_PROFILE_ENV_LABEL = "~/.hermes/.env (default profile)"


def read_default_env() -> dict[str, str | None]:
    """Read the default profile's .env from the Hermes home. Empty dict if absent.

    Same tolerance as read_env: an unreadable file (permissions, broken
    encoding) yields {} instead of raising — start/verify scan it on every run.
    """
    env_path = get_hermes_home() / ".env"
    if not env_path.exists():
        return {}
    try:
        return dotenv_values(env_path)
    except (OSError, UnicodeError):
        return {}


def write_env(name: str, env_vars: dict[str, str]) -> None:
    """Write key=value pairs to a profile's .env file."""
    env_path = get_profile_dir(name) / ".env"
    lines: list[str] = []
    for key, value in env_vars.items():
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_soul(name: str) -> str:
    """Read SOUL.md from a profile directory.

    Same tolerance as read_env: an unreadable file (permissions, broken
    encoding) yields "" instead of raising.
    """
    soul_path = get_profile_dir(name) / "SOUL.md"
    if not soul_path.exists():
        return ""
    try:
        return soul_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def write_soul(name: str, content: str) -> None:
    """Write content to a profile's SOUL.md file."""
    soul_path = get_profile_dir(name) / "SOUL.md"
    soul_path.write_text(content, encoding="utf-8")


# Hermes' _PROFILE_IDENTITY_MARKERS: a directory under profiles/ without any of
# these is a runtime side-effect (cron heartbeat, log rotation) or a ghost shell.
_PROFILE_IDENTITY_MARKERS = (
    "config.yaml",
    ".env",
    "SOUL.md",
    "profile.yaml",
    "auth.json",
    "state.db",
)


def _servable_profile_entry(profiles_dir: Path, entry: Path) -> bool:
    """Hermes' named-profile gates (_iter_named_profile_dirs): not ``default``,
    not tombstoned (``profiles/.deleted/<name>`` exists), and carries an
    identity marker — ghost shells "must never be listed, served"."""
    if entry.name == "default":
        return False
    if (profiles_dir / ".deleted" / entry.name).exists():
        return False
    return any(
        (entry / marker).is_file() or (entry / marker).is_symlink()
        for marker in _PROFILE_IDENTITY_MARKERS
    )


def list_team_profiles(prefix: str) -> list[str]:
    """List servable profile names matching the given prefix.

    Same gates as list_all_profile_names: ghost directories (runtime
    side-effects without an identity marker) and tombstoned profiles are not
    team profiles — the host never serves them, and treating them as missing
    credentials would fail start/verify spuriously.
    """
    profiles_dir = get_profiles_dir()
    if not profiles_dir.is_dir():
        return []
    return sorted(
        p.name
        for p in profiles_dir.iterdir()
        if p.is_dir() and p.name.startswith(prefix) and _servable_profile_entry(profiles_dir, p)
    )


def list_all_profile_names() -> list[str]:
    """List every servable named profile under profiles/ — other teams included.

    The host multiplex gateway serves ALL of these (Hermes' profiles_to_serve).
    """
    profiles_dir = get_profiles_dir()
    if not profiles_dir.is_dir():
        return []
    return sorted(
        p.name
        for p in profiles_dir.iterdir()
        if p.is_dir() and _servable_profile_entry(profiles_dir, p)
    )


def remove_tombstone(name: str) -> bool:
    """Remove the ``profiles/.deleted/<name>`` tombstone (re-add / re-init).

    A tombstone left behind would keep hiding the freshly (re-)created
    profile from list_team_profiles/collect-ids even though add-member or
    init just rebuilt it. Returns True when a tombstone existed and was
    removed; False when there was none. Deletion failures raise OSError —
    callers must warn (the profile would stay invisible otherwise).
    """
    tombstone = get_profiles_dir() / ".deleted" / name
    if not tombstone.exists():
        return False
    shutil.rmtree(tombstone)  # raises OSError on failure — callers warn
    return True


def profile_served_by_host(name: str) -> bool:
    """Whether the host multiplex gateway serves this named profile.

    Mirrors Hermes' profiles_to_serve: a profile is skipped when it carries a
    ``gateway.parked`` marker (``hermes -p <name> gateway stop``) or opted out
    via ``gateway.standalone: true`` in its config.yaml.
    """
    profile_dir = get_profile_dir(name)
    if (profile_dir / "gateway.parked").exists():
        return False
    return not _config_gateway_standalone(profile_dir)


# Written by `hermes-team init` into every profile it creates: which role the
# profile plays (key/name/nickname/role, coordinator flag). collect-ids reads
# it to map profiles back to SOUL.md names without relying on hardcoded role
# tables. (verify does not read it — its open_id check is role-agnostic,
# excluding placeholders by their "ou_xxx" prefix.)
TEAM_METADATA_FILENAME = ".hermes-team.json"


def read_team_metadata(name: str) -> dict:
    """Read a profile's team metadata written at init time.

    Returns {} when absent (teams created before this existed) or unreadable —
    callers fall back to the builtin role tables.
    """
    metadata_path = get_profile_dir(name) / TEAM_METADATA_FILENAME
    if not metadata_path.exists():
        return {}
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _config_gateway_standalone(profile_dir: Path) -> bool:
    """Best-effort read of ``gateway.standalone`` from a profile's config.yaml.

    Line-level scan (no YAML dependency): locates the top-level ``gateway:``
    section, lets its FIRST indented key define the direct-child indent (so 2- or
    4-space YAML both work, but a deeper ``gateway.<sub>.standalone`` is ignored),
    and also understands an inline ``gateway: {standalone: true}``. Anything
    unreadable or ambiguous counts as NOT standalone: for credential-uniqueness
    checks we would rather over-report a clash than miss one.
    """
    path = profile_dir / "config.yaml"
    if not path.exists():
        return False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return False

    child_indent: int | None = None
    in_gateway = False
    for raw_line in lines:
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            key, sep, rest = line.partition(":")
            if not sep:
                in_gateway = False
                continue
            rest = rest.strip()
            in_gateway = key.strip() == "gateway"
            if in_gateway and rest.startswith("{"):
                return _flow_map_has_standalone_true(rest)
            child_indent = None
            continue
        if not in_gateway:
            continue
        if child_indent is None:
            child_indent = indent  # first nested key defines the direct-child indent
        if indent == child_indent:
            key, sep, value = line.strip().partition(":")
            if sep and key.strip() == "standalone":
                return _scalar_token(value) in _TRUTHY_TOKENS
    return False


def _flow_map_has_standalone_true(flow_map: str) -> bool:
    """Parse ``{standalone: true, ...}`` (inline flow mapping) — best effort."""
    match = re.search(r"\bstandalone\s*:\s*([^,}]+)", flow_map)
    if not match:
        return False
    return _scalar_token(match.group(1)) in _TRUTHY_TOKENS


_TRUTHY_TOKENS = ("true", "yes", "on", "1")


def _scalar_token(value: str) -> str:
    """First scalar of a YAML value: strip an unquoted inline comment and quotes."""
    value = value.strip()
    if value[:1] in ('"', "'"):
        # A '#' inside quotes is data, not a comment. An unterminated quote is
        # broken YAML: return an empty (non-truthy) token, mirroring Hermes'
        # YAMLError → not-standalone → served-by-host fallback.
        quote = value[0]
        end = value.find(quote, 1)
        if end == -1:
            return ""
        return value[1:end].strip().lower()
    return value.split("#", 1)[0].strip().lower()
