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


def default_env_unreadable() -> bool:
    """Whether ~/.hermes/.env exists but cannot be read/parsed at all.

    Split from read_default_env's {}-on-error: an unreadable file
    (permissions, broken encoding) blinds start's App-ID uniqueness scan and
    must fail verify, while a file that reads as {} (empty, comments only,
    absent) simply has no App ID and blinds nothing.
    """
    env_path = get_hermes_home() / ".env"
    if not env_path.exists():
        return False
    try:
        dotenv_values(env_path)
    except (OSError, UnicodeError):
        return True
    return False


def write_env(name: str, env_vars: dict[str, str]) -> bool:
    """Write key=value pairs to a profile's .env file.

    The file carries the Feishu App Secret, so it is created owner-only
    (0600) regardless of umask — a plain write_text would leave 0644/0664
    (world/group readable). os.open's mode applies only at creation; an
    existing file that is still group/other-readable is tightened to 0600
    after the rewrite (it may predate this rule or have been loosened by
    hand) — leaving it readable would expose the secret on every
    reconfigure. An existing file whose owner-write bit is missing (e.g.
    0400) gets it granted before the open: the rewrite is happening on the
    operator's explicit request, and os.open(O_WRONLY) on such a file would
    raise PermissionError. Other pre-existing mode bits are preserved.

    Returns True when an existing file's permissions were tightened to 0600.
    """
    env_path = get_profile_dir(name) / ".env"
    lines: list[str] = []
    for key, value in env_vars.items():
        lines.append(f"{key}={value}")
    if env_path.exists() and not env_path.stat().st_mode & 0o200:
        env_path.chmod(env_path.stat().st_mode | 0o200)
    fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    if env_path.stat().st_mode & 0o077:  # group/other read (or more)
        env_path.chmod(0o600)
        return True
    return False


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


def _prefix_matches(profile_name: str, prefix: str) -> bool:
    """Name-based fallback team match: exact name (a standalone bot named like
    the prefix) or exactly ``<prefix>-<key>`` with a dash-free-attributable
    key — a bare ``startswith(prefix)`` has no separator boundary (with
    prefixes ``team``/``teamq``, every team command run against ``team``
    would swallow teamq's profiles).

    Deliberately stricter than "starts with ``prefix-``": a name with a dash
    BEYOND the prefix boundary (``team-extra-pm`` under ``team``) cannot be
    attributed without metadata — it is equally a dash-keyed member of this
    team and a plain member of the ``team-extra`` team, and remove-member /
    destroy deleting another team's profile is the worse mistake. Such names
    fail closed: excluded from the team listing here, still matched under
    their LONGEST prefix (``team-extra``), and re-init/add-member records the
    ``prefix`` in metadata, which resolves the ambiguity permanently.
    """
    if profile_name == prefix:
        return True
    if not profile_name.startswith(prefix + "-"):
        return False
    return profile_name.rsplit("-", 1)[0] == prefix


def _team_profile_matches(profile_name: str, prefix: str) -> bool:
    """Whether a profile belongs to the team with this prefix.

    Profiles created by init/add-member record their team's prefix in
    .hermes-team.json — match on it exactly, so dash-nested prefixes
    (``team`` vs ``team-extra``: ``team-extra-pm`` starts with ``team-``)
    stay isolated even though their names collide. Standalone bots (no
    ``prefix`` recorded) and legacy pre-metadata profiles fall back to
    name-based matching, with its ambiguity fail-closed (see
    _prefix_matches).
    """
    recorded = read_team_metadata(profile_name).get("prefix")
    if isinstance(recorded, str) and recorded:
        return recorded == prefix
    return _prefix_matches(profile_name, prefix)


def list_name_ambiguous_profiles(prefix: str) -> list[str]:
    """Profiles whose NAMES could match this prefix but were excluded.

    Only the name-inferred case: no metadata records an owning prefix, and
    the name has a dash beyond the prefix boundary (``team-extra-pm`` queried
    as ``team``), so list_team_profiles fails closed and excludes it. (A
    profile recording a DIFFERENT prefix is simply another team's profile —
    foreign, not ambiguous — and is not listed.) Commands that would
    otherwise have swallowed it (destroy, remove-member, collect-ids,
    add-member) use this list to tell the user WHY it is missing and how to
    resolve it (re-init / add-member writes the ``prefix`` into metadata).
    """
    profiles_dir = get_profiles_dir()
    if not profiles_dir.is_dir():
        return []
    ambiguous: list[str] = []
    for entry in profiles_dir.iterdir():
        if not entry.is_dir() or not _servable_profile_entry(profiles_dir, entry):
            continue
        name = entry.name
        if name == prefix or not name.startswith(prefix + "-"):
            continue  # the name could not match this prefix at all
        if _team_profile_matches(name, prefix):
            continue  # matched — nothing to explain
        if team_metadata_corrupt(name):
            continue  # corrupt metadata is other commands' fail-closed case
        meta = read_team_metadata(name)
        if meta.get("removed"):
            continue  # kept-but-removed: no longer a team candidate at all
        if meta.get("standalone"):
            # Standalone bots are never team candidates (new-bot docs) —
            # advising a "re-init under its own team" for one would send the
            # user to overwrite their bot.
            continue
        recorded = meta.get("prefix")
        if isinstance(recorded, str) and recorded:
            continue  # another team's recorded profile: foreign, not ambiguous
        ambiguous.append(name)
    return sorted(ambiguous)


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
        if p.is_dir()
        and _team_profile_matches(p.name, prefix)
        and _servable_profile_entry(profiles_dir, p)
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


# Written by `hermes-team init` into every team profile it creates and by
# `new-bot` into every standalone bot: which role the profile plays
# (key/name/nickname/role, coordinator flag; new-bot adds "standalone": true).
# collect-ids reads it to map profiles back to SOUL.md names without relying
# on hardcoded role tables; verify reads the standalone marker and the
# recorded template (roster-free bot templates carry no @-mention roster);
# init/member/destroy read it to rebuild or exclude rosters.
TEAM_METADATA_FILENAME = ".hermes-team.json"


def _load_team_metadata(name: str) -> dict | None:
    """Parse .hermes-team.json.

    Returns {} when the file is absent, ``None`` when it exists but cannot be
    read or parsed as a JSON object (corrupt), and the dict otherwise.
    """
    metadata_path = get_profile_dir(name) / TEAM_METADATA_FILENAME
    if not metadata_path.exists():
        return {}
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    return data if isinstance(data, dict) else None


def read_team_metadata(name: str) -> dict:
    """Read a profile's team metadata written at init time.

    Returns {} when absent (teams created before this existed) or unreadable —
    callers fall back to the builtin role tables. Callers that must fail
    closed on corruption (destroy's exclusion, init/member roster rebuilds)
    check ``team_metadata_corrupt()`` first: a corrupt file hides any
    "standalone" marker it carried.
    """
    data = _load_team_metadata(name)
    return data or {}


def team_metadata_corrupt(name: str) -> bool:
    """Whether .hermes-team.json exists but cannot be parsed as a JSON object.

    A corrupt file is not "no metadata": it may hide a standalone marker or a
    removed marker, so safety-relevant paths treat such profiles as neither
    team members nor deletable.
    """
    return _load_team_metadata(name) is None


def is_standalone_profile(name: str) -> bool:
    """Whether this profile is a standalone bot (created by new-bot).

    Lives here (not in commands.bot) so every command — verify, collect-ids,
    configure, destroy, member — can import it without import cycles.
    """
    return bool(read_team_metadata(name).get("standalone"))


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
