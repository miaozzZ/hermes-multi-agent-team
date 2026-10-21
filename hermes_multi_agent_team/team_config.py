"""External team configuration — role definitions loaded from a JSON file.

A team config file makes roles customizable without touching code:

```json
{
  "team_name": "MyTeam",
  "prefix": "myteam",
  "roles": [
    {"key": "pm", "name": "P酱", "nickname": "小P", "role": "产品经理"}
  ],
  "coordinator": {"key": "coord", "name": "M总", "nickname": "小m", "role": "总管"}
}
```

- ``team_name`` / ``prefix``: optional defaults; CLI flags win over them.
- ``roles``: required, non-empty. Each entry needs ``key`` (used in the
  profile name ``<prefix>-<key>``), ``name`` (shown in SOUL.md and matched
  against ``<at>`` tags by collect-ids) and ``role`` (job title). ``nickname``
  defaults to ``name``; ``template`` names a SOUL template (see below).
- ``coordinator``: optional. When present, ``init`` also creates the
  coordinator's profile and renders the coordinator SOUL for it.
- ``coordinator_fallback``: optional; mutually exclusive with ``coordinator``
  (declaring both is a load-time error). A render-only roster entry (``name``
  required; ``role`` defaults to 总管, ``nickname`` to ``name``) so members
  still have a hub to @ — no profile is created for it and its
  ``ou_xxx_coordinator`` open_id is not auto-filled by collect-ids. The
  builtin default team ships one named M总; a custom config declaring neither
  gets no hub entry in the roster at all.

``template`` resolution order:
1. A path that exists — absolute, or relative to the config file's directory
   (the cwd is deliberately not consulted) — rendered from that file, so
   fully custom templates live outside the package.
2. A bundled template name (``pm.md.j2`` … or its short form ``pm``).
3. Omitted + builtin key (pm/fe/be/qa/ui) → that role's bundled template;
   an omitted coordinator template defaults to ``coordinator.md.j2``
   whatever its key is.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# Profile names are "<prefix>-<key>", so keys must stay filename-safe.
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

# Bundled SOUL templates: short alias → package file name.
_BUILTIN_TEMPLATES: dict[str, str] = {
    "coordinator": "coordinator.md.j2",
    "bot": "bot.md.j2",
    "pm": "pm.md.j2",
    "frontend": "frontend.md.j2",
    "backend": "backend.md.j2",
    "qa": "qa.md.j2",
    "designer": "designer.md.j2",
}

# Builtin role keys (the default team's five) → their bundled templates, so a
# config entry using one of these keys may omit "template". Keys and template
# short names differ for fe/be/ui (frontend/backend/designer).
_KEY_DEFAULT_TEMPLATES: dict[str, str] = {
    "pm": "pm.md.j2",
    "fe": "frontend.md.j2",
    "be": "backend.md.j2",
    "qa": "qa.md.j2",
    "ui": "designer.md.j2",
}


class TeamConfigError(ValueError):
    """Raised when a team config file is missing, malformed, or inconsistent."""


def validate_prefix(prefix: str) -> str:
    """Validate a profile-name prefix before it is joined into any path.

    The prefix becomes part of profile directory names
    (``profiles/<prefix>-<key>``): a path separator or ``..`` would escape
    the profiles directory (``"../escaped"`` → ``~/.hermes/escaped-pm/``)
    and a separator-containing prefix would nest profiles so deep that
    ``list_team_profiles`` (which scans direct children only) never finds
    them again.
    """
    cleaned = prefix.strip()
    if not cleaned:
        raise TeamConfigError("'prefix' must be a non-empty string")
    if any(ch in cleaned for ch in ("/", "\\", "\0")) or cleaned in (".", ".."):
        raise TeamConfigError(
            f"prefix '{cleaned}' is invalid: it becomes part of profile directory "
            "names, so path separators and '..' are not allowed"
        )
    return cleaned


def _check_at_safe(label: str, field_name: str, value: str) -> None:
    """Reject name/role text that would break SOUL.md roster lines.

    Names and roles are embedded verbatim in
    ``- @name（role）：`<at user_id="…">name</at>` `` lines: ``<``/``>`` or a
    newline breaks collect-ids' ``<at>``-tag matching (the name must match
    ``[^<]+``) and the line structure. The owner line's name 主人 is
    reserved — a member sharing it would get the owner line's open_id
    rewritten by collect-ids.
    """
    if any(ch in value for ch in "<>\n\r"):
        raise TeamConfigError(
            f"{label}: '{field_name}' must not contain '<', '>' or newlines "
            "(it is embedded in SOUL.md roster lines and <at> tags)"
        )
    if field_name == "name" and value == "主人":
        raise TeamConfigError(f"{label}: name '主人' is reserved for the SOUL.md owner line")


@dataclass(frozen=True)
class RoleSpec:
    """One agent role as declared in the config (or builtin defaults)."""

    key: str
    name: str
    role: str
    nickname: str
    template: str
    # Path to an external template file, or None when ``template`` names a
    # bundled template (resolved against the package's SOUL/ directory).
    template_path: Path | None = None

    def as_team_member(self) -> dict[str, str]:
        """The dict the SOUL templates receive in the team_members loop."""
        return {
            "name": self.name,
            "nickname": self.nickname,
            "role": self.role,
            "open_id": f"ou_xxx_{self.key}",  # placeholder, filled by collect-ids
        }


@dataclass(frozen=True)
class HubSpec:
    """A render-only roster entry for the hub when no coordinator is declared.

    The user's own main profile plays the 总管, so init creates no profile for
    it — the entry only gives members a name to @. Its open_id stays the
    "ou_xxx_coordinator" placeholder (not auto-filled by collect-ids, since
    the main profile is not one of the team's profiles).
    """

    name: str
    nickname: str
    role: str

    def as_team_member(self) -> dict[str, str]:
        """The dict the SOUL templates receive in the team_members loop."""
        return {
            "name": self.name,
            "nickname": self.nickname,
            "role": self.role,
            "open_id": "ou_xxx_coordinator",  # render-only placeholder
        }


@dataclass(frozen=True)
class TeamConfig:
    """A fully validated team definition."""

    roles: list[RoleSpec] = field(default_factory=list)
    coordinator: RoleSpec | None = None
    # Render-only hub entry used when no coordinator is declared.
    hub: HubSpec | None = None
    team_name: str | None = None
    prefix: str | None = None
    source: Path | None = None

    def role(self, key: str) -> RoleSpec | None:
        # Case-insensitive lookup: _KEY_RE allows uppercase keys, and --roles
        # should match them however the user typed them. Keys differing only
        # in case are rejected at load time (_validate_unique), so this stays
        # unambiguous.
        lowered = key.lower()
        return next((r for r in self.roles if r.key.lower() == lowered), None)


def _resolve_template(
    raw: object, key: str, config_dir: Path | None, default: str | None = None
) -> tuple[str, Path | None]:
    """Return (template_name, external_path_or_None) for a config value."""
    if raw is None:
        # An explicit default (only the coordinator passes one) wins over the
        # key-based lookups: a coordinator keyed "pm"/"FE" still gets the
        # coordinator SOUL — its key is arbitrary ("whatever its key is").
        # Keys may contain uppercase (_KEY_RE allows it) and TeamConfig.role()
        # matches case-insensitively — the key lookups follow the same rule,
        # so role key "FE" resolves like "fe".
        lowered = key.lower()
        builtin = default or _BUILTIN_TEMPLATES.get(lowered) or _KEY_DEFAULT_TEMPLATES.get(lowered)
        if builtin is None:
            raise TeamConfigError(
                f"role '{key}' needs a 'template' (no builtin template for this key)"
            )
        return builtin, None

    if not isinstance(raw, str) or not raw.strip():
        raise TeamConfigError(f"role '{key}': 'template' must be a non-empty string")

    template = raw.strip()
    # Absolute path, or relative to the config file's directory — the cwd is
    # deliberately NOT consulted: docs promise config-relative resolution, and
    # silently picking up a same-named file from the cwd would render the
    # wrong persona.
    if Path(template).is_absolute():
        candidates: list[Path] = [Path(template)]
    else:
        candidates = [config_dir / template] if config_dir else []
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve()), candidate.resolve()

    if template in _BUILTIN_TEMPLATES or template in _BUILTIN_TEMPLATES.values():
        name = _BUILTIN_TEMPLATES.get(template, template)
        return name, None

    raise TeamConfigError(
        f"role '{key}': template '{template}' is neither an existing file "
        f"nor a bundled template ({', '.join(sorted(_BUILTIN_TEMPLATES))})"
    )


def _parse_role(
    raw: object, config_dir: Path | None, kind: str, default_template: str | None = None
) -> RoleSpec:
    if not isinstance(raw, dict):
        raise TeamConfigError(f"{kind} entry must be an object, got {type(raw).__name__}")

    key = raw.get("key")
    name = raw.get("name")
    role = raw.get("role")
    for field_name, value in (("key", key), ("name", name), ("role", role)):
        if not isinstance(value, str) or not value.strip():
            raise TeamConfigError(f"{kind} entry needs a non-empty string '{field_name}'")

    key = key.strip()
    if not _KEY_RE.match(key):
        raise TeamConfigError(
            f"role key '{key}' is invalid (use letters, digits, '-' and '_'; "
            "it becomes part of the profile name)"
        )

    name = name.strip()
    role = role.strip()
    _check_at_safe(f"{kind} '{key}'", "name", name)
    _check_at_safe(f"{kind} '{key}'", "role", role)

    nickname = raw.get("nickname")
    if nickname is not None and not isinstance(nickname, str):
        raise TeamConfigError(f"role '{key}': 'nickname' must be a string")
    # A whitespace-only nickname is "no nickname": fall back to name.
    nickname = (nickname or "").strip() or name.strip()

    template_name, template_path = _resolve_template(
        raw.get("template"), key, config_dir, default_template
    )
    return RoleSpec(
        key=key,
        name=name.strip(),
        role=role.strip(),
        nickname=nickname,
        template=template_name,
        template_path=template_path,
    )


def _parse_hub(raw: object) -> HubSpec:
    """Parse the render-only hub entry (config key ``coordinator_fallback``)."""
    if not isinstance(raw, dict):
        raise TeamConfigError(f"coordinator_fallback must be an object, got {type(raw).__name__}")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise TeamConfigError("coordinator_fallback needs a non-empty string 'name'")
    role = raw.get("role", "总管")
    if not isinstance(role, str) or not role.strip():
        raise TeamConfigError("coordinator_fallback: 'role' must be a non-empty string")
    nickname = raw.get("nickname")
    if nickname is not None and not isinstance(nickname, str):
        raise TeamConfigError("coordinator_fallback: 'nickname' must be a string")
    name = name.strip()
    role = role.strip()
    _check_at_safe("coordinator_fallback", "name", name)
    _check_at_safe("coordinator_fallback", "role", role)
    # Same "whitespace-only is no nickname" rule as roles.
    nickname = (nickname or "").strip() or name
    return HubSpec(name=name, nickname=nickname, role=role)


def _validate_unique(specs: list[RoleSpec]) -> None:
    keys: set[str] = set()
    lower_keys: set[str] = set()
    names: set[str] = set()
    for spec in specs:
        if spec.key in keys:
            raise TeamConfigError(f"duplicate role key '{spec.key}'")
        # Profile names are <prefix>-<key>; keys differing only in case would
        # collide into ONE directory on case-insensitive filesystems (macOS
        # APFS default, Windows) — the second profile would silently overwrite
        # the first's SOUL.md/.hermes-team.json.
        if spec.key.lower() in lower_keys:
            raise TeamConfigError(
                f"duplicate role key '{spec.key}' (differs from another key only by case; "
                "profile names would collide on case-insensitive filesystems)"
            )
        # collect-ids fills open_ids by matching <at>NAME</at> — duplicate
        # names would make that mapping ambiguous.
        if spec.name in names:
            raise TeamConfigError(
                f"duplicate role name '{spec.name}' (keys must be unique AND names must be "
                "unique — collect-ids matches SOUL.md @tags by name)"
            )
        keys.add(spec.key)
        lower_keys.add(spec.key.lower())
        names.add(spec.name)


def load_team_config(path: str | Path) -> TeamConfig:
    """Load and validate a team config JSON file."""
    config_path = Path(path)
    if not config_path.is_file():
        raise TeamConfigError(f"team config file not found: {config_path}")

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise TeamConfigError(f"could not read team config {config_path}: {e}") from e

    if not isinstance(data, dict):
        raise TeamConfigError("team config must be a JSON object")

    config_dir = config_path.parent

    raw_roles = data.get("roles")
    if not isinstance(raw_roles, list) or not raw_roles:
        raise TeamConfigError("'roles' must be a non-empty list")

    roles = [_parse_role(entry, config_dir, "role") for entry in raw_roles]

    coordinator: RoleSpec | None = None
    raw_coordinator = data.get("coordinator")
    if raw_coordinator is not None:
        # The coordinator's key is arbitrary (coord, boss, …), so an omitted
        # template defaults to the bundled coordinator SOUL instead of being
        # looked up by key.
        coordinator = _parse_role(
            raw_coordinator, config_dir, "coordinator", default_template="coordinator.md.j2"
        )

    hub: HubSpec | None = None
    raw_hub = data.get("coordinator_fallback")
    if raw_hub is not None:
        if coordinator is not None:
            raise TeamConfigError(
                "declare either 'coordinator' or 'coordinator_fallback', not both "
                "(a declared coordinator makes the render-only fallback moot)"
            )
        hub = _parse_hub(raw_hub)

    _validate_unique(roles + ([coordinator] if coordinator else []))
    if hub is not None and any(
        spec.name == hub.name for spec in roles + ([coordinator] if coordinator else [])
    ):
        # Same ambiguity _validate_unique rejects: collect-ids matches SOUL.md
        # @tags by name, so the hub entry must not share a name with a member.
        raise TeamConfigError(
            f"coordinator_fallback name '{hub.name}' duplicates a role name "
            "(collect-ids matches SOUL.md @tags by name)"
        )

    team_name = data.get("team_name")
    prefix = data.get("prefix")
    for label, value in (("team_name", team_name), ("prefix", prefix)):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise TeamConfigError(f"'{label}' must be a non-empty string")
    # The prefix is joined into profile paths — validate before anything is
    # created from it ("../escaped" would write outside the profiles dir).
    if isinstance(prefix, str):
        prefix = validate_prefix(prefix)

    return TeamConfig(
        roles=roles,
        coordinator=coordinator,
        hub=hub,
        team_name=team_name.strip() if isinstance(team_name, str) else None,
        prefix=prefix,
        source=config_path,
    )


def builtin_team_config() -> TeamConfig:
    """The builtin five-role team — the default when no --config is given."""
    return TeamConfig(
        # The legacy render-only M总 hub entry (HEAD behaviour): the 总管 is
        # the user's own main profile, so no profile is created for it.
        hub=HubSpec(name="M总", nickname="小m", role="总管"),
        roles=[
            RoleSpec(key="pm", name="P酱", nickname="小P", role="产品经理", template="pm.md.j2"),
            RoleSpec(
                key="fe",
                name="F仔",
                nickname="小F",
                role="前端开发",
                template="frontend.md.j2",
            ),
            RoleSpec(
                key="be",
                name="B叔",
                nickname="小B",
                role="后端开发",
                template="backend.md.j2",
            ),
            RoleSpec(key="qa", name="Q宝", nickname="小Q", role="测试QA", template="qa.md.j2"),
            RoleSpec(
                key="ui", name="U酱", nickname="小U", role="UI设计", template="designer.md.j2"
            ),
        ],
    )


def builtin_template_for_key(key: str) -> str | None:
    """Bundled template for a builtin role key (case-insensitive), if any."""
    lowered = key.lower()
    return _BUILTIN_TEMPLATES.get(lowered) or _KEY_DEFAULT_TEMPLATES.get(lowered)


def make_role_spec(
    key: str,
    name: str,
    role: str,
    nickname: str | None = None,
    template: str | None = None,
) -> RoleSpec:
    """Build a validated RoleSpec from CLI-style arguments (add-member).

    Same validation as a config entry; a ``template`` path resolves against
    the working directory (the user typed it on the command line), and an
    omitted template falls back to the key's builtin template.
    """
    raw: dict[str, str] = {"key": key, "name": name, "role": role}
    if nickname is not None:
        raw["nickname"] = nickname
    if template is not None:
        raw["template"] = template
    return _parse_role(raw, Path.cwd(), "role")


def validate_role_key(key: str) -> str:
    """Strip and validate a role key for immediate interactive feedback.

    Same rule _parse_role enforces (filename-safe: it becomes part of the
    profile name); returns the stripped key or raises TeamConfigError.
    """
    cleaned = key.strip()
    if not cleaned or not _KEY_RE.match(cleaned):
        raise TeamConfigError(
            f"role key '{cleaned or key}' is invalid (use letters, digits, '-' and '_'; "
            "it becomes part of the profile name)"
        )
    return cleaned


def validate_role_name(name: str) -> str:
    """Strip and validate a display name for immediate interactive feedback.

    Non-empty, at-safe, and not the reserved owner name — the same rules
    _parse_role applies. Returns the stripped name or raises TeamConfigError.
    """
    cleaned = name.strip()
    if not cleaned:
        raise TeamConfigError("'name' must be a non-empty string")
    _check_at_safe("role", "name", cleaned)
    return cleaned
