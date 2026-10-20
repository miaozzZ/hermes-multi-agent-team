"""init command — create Hermes profiles and generate SOUL.md for each team role."""

from __future__ import annotations

import json
import subprocess
import sys
from importlib import resources
from pathlib import Path

import click
from jinja2 import Environment, FileSystemLoader, select_autoescape

from hermes_multi_agent_team.commands.collect_ids import ROLE_NAME_MAP
from hermes_multi_agent_team.team_config import (
    RoleSpec,
    TeamConfig,
    TeamConfigError,
    builtin_team_config,
    load_team_config,
    validate_prefix,
)
from hermes_multi_agent_team.utils.gateway import find_hermes_bin
from hermes_multi_agent_team.utils.profile import (
    TEAM_METADATA_FILENAME,
    get_profiles_dir,
    list_team_profiles,
    profile_exists,
    read_team_metadata,
    remove_tombstone,
)


def get_templates_dir() -> Path:
    """Get the templates directory path."""
    try:
        # Python 3.9+
        return Path(resources.files("hermes_multi_agent_team.templates").joinpath("SOUL"))
    except (AttributeError, FileNotFoundError):
        # Fallback: read from filesystem
        return Path(__file__).resolve().parent.parent / "templates" / "SOUL"


def get_jinja_env() -> Environment:
    """Create a Jinja2 environment for template rendering."""
    templates_dir = get_templates_dir()
    return Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape([]),
        keep_trailing_newline=True,
    )


def render_soul(
    env: Environment, template_name: str, template_path: Path | None, context: dict
) -> str:
    """Render a SOUL from a bundled template name or an external file path."""
    if template_path is not None:
        template = env.from_string(template_path.read_text(encoding="utf-8"))
    else:
        template = env.get_template(template_name)
    return template.render(**context)


def run_hermes(args: list[str], dry_run: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a hermes CLI command."""
    cmd_str = " ".join(args)
    if dry_run:
        click.echo(f"  💨 dry-run: {cmd_str}")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    click.echo(f"  🔧 Running: {cmd_str}")
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            click.echo(f"  ⚠️  Command returned {result.returncode}")
            if result.stderr:
                click.echo(f"     stderr: {result.stderr.strip()}")
        return result
    except FileNotFoundError:
        raise click.ClickException(f"❌ Command not found: {args[0]}. Is Hermes installed?")
    except subprocess.TimeoutExpired:
        raise click.ClickException(f"❌ Command timed out: {cmd_str}")


def _load_config(config: str | None) -> TeamConfig:
    """Load the team config from --config, or the builtin five-role defaults."""
    if not config:
        return builtin_team_config()
    try:
        cfg = load_team_config(config)
    except TeamConfigError as e:
        raise click.ClickException(f"❌ Invalid team config: {e}") from e
    click.echo(f"📋 Loaded team config: {cfg.source} ({len(cfg.roles)} role(s))")
    return cfg


def _create_profile(
    *,
    env: Environment,
    hermes_bin: str,
    profile_name: str,
    team_name: str,
    prefix: str,
    template_name: str,
    template_path: Path | None,
    context: dict,
    clone_from: str | None,
    metadata: dict,
    dry_run: bool,
) -> bool:
    """Create one profile (hermes CLI) + SOUL.md + team metadata. True on success."""
    # Check if profile already exists
    if profile_exists(profile_name):
        click.echo(f"  ⚠️  Profile '{profile_name}' already exists, skipping creation")
    else:
        cmd = [hermes_bin, "profile", "create", profile_name]
        if clone_from:
            cmd.extend(["--clone-from", clone_from])
        result = run_hermes(cmd, dry_run=dry_run)
        if result.returncode != 0 and not dry_run:
            click.echo(f"  ❌ Failed to create profile '{profile_name}'")
            return False

    if not dry_run:
        try:
            soul_content = render_soul(env, template_name, template_path, context)
            profile_dir = get_profiles_dir() / profile_name
            profile_dir.mkdir(parents=True, exist_ok=True)
            soul_path = profile_dir / "SOUL.md"
            soul_path.write_text(soul_content, encoding="utf-8")
            metadata_path = profile_dir / TEAM_METADATA_FILENAME
            metadata_path.write_text(
                json.dumps({**metadata, "team": team_name, "prefix": prefix}, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )
            click.echo(f"  ✅ Generated SOUL.md ({len(soul_content)} bytes)")
            # A stale tombstone (profiles/.deleted/<name>) would keep hiding
            # the freshly (re-)created profile from listings and collect-ids.
            # Caught here, separately from the render handler below: the
            # profile IS written — a tombstone failure is a warning, not a
            # per-role failure.
            try:
                if remove_tombstone(profile_name):
                    click.echo(f"  🧹 Removed stale tombstone profiles/.deleted/{profile_name}")
            except OSError as e:
                click.echo(
                    f"  ⚠️  Could not remove tombstone profiles/.deleted/{profile_name}: {e}\n"
                    "     Delete it manually — until then the profile stays hidden from "
                    "collect-ids/verify"
                )
        # Any render-time failure becomes a per-role failure, not an uncaught
        # crash: OSError/UnicodeError on reading or writing, jinja2 errors,
        # or an exception raised BY a custom template's code ({{ 1/0 }} →
        # ZeroDivisionError). KeyboardInterrupt/SystemExit still propagate
        # (they derive from BaseException, not Exception).
        except Exception as e:  # noqa: BLE001 — deliberate: see comment above
            click.echo(f"  ❌ Failed to render template: {e}")
            return False
    else:
        click.echo(f"  💨 dry-run: would generate SOUL.md from {template_name}")
        if template_path is not None:
            click.echo(f"     (external template: {template_path})")

    return True


def init_team(
    team_name: str | None,
    roles: str | None,
    prefix: str | None,
    clone_from: str | None,
    dry_run: bool,
    config: str | None = None,
) -> None:
    """Create Hermes profiles and generate SOUL.md for each team role."""
    cfg = _load_config(config)

    # CLI flags win over config-file values; team_name is always required.
    team_name = team_name or cfg.team_name
    if not team_name:
        team_name = click.prompt("Team name")
    prefix = prefix or cfg.prefix or team_name
    # The prefix is joined into profile paths before any file is created —
    # a separator or ".." would escape the profiles directory (config-file
    # prefixes were already checked in load_team_config; this covers the
    # CLI flag and the team_name fallback).
    try:
        prefix = validate_prefix(prefix)
    except TeamConfigError as e:
        raise click.ClickException(f"❌ Invalid profile prefix: {e}") from e

    # Parse roles: a subset of the config's roles — None (option omitted)
    # means all of them. An explicitly EMPTY --roles is an error, not "all
    # roles": a script passing an empty variable must not suddenly get the
    # whole team created. Keys may contain uppercase (_KEY_RE allows it);
    # TeamConfig.role() matches them case-insensitively.
    if roles is None:
        role_keys = [spec.key for spec in cfg.roles]
    else:
        role_keys = [r.strip() for r in roles.split(",") if r.strip()]
        if not role_keys:
            raise click.ClickException(
                "❌ --roles is empty — omit --roles to create all of the team's roles"
            )
    invalid_roles = [r for r in role_keys if cfg.role(r) is None]
    if invalid_roles:
        raise click.ClickException(
            f"❌ Unknown roles: {', '.join(invalid_roles)}. "
            f"Valid roles: {', '.join(spec.key for spec in cfg.roles)}"
        )
    # `--roles pm,pm` (or case variants like `pm,PM`, which resolve to the
    # same spec) must not put one RoleSpec into the roster twice — SOUL
    # templates render a duplicate @-line per roster entry. Dedupe by the
    # resolved spec key, keeping declaration order.
    seen_keys: set[str] = set()
    unique_role_keys: list[str] = []
    for r in role_keys:
        resolved = cfg.role(r).key.lower()
        if resolved not in seen_keys:
            seen_keys.add(resolved)
            unique_role_keys.append(r)
    role_keys = unique_role_keys

    coordinator = cfg.coordinator
    # Persist the render-only hub (custom configs' coordinator_fallback and
    # the builtin team's M总) in every profile's metadata, so later
    # add/remove-member rebuilds the roster WITH the hub instead of losing
    # it (it has no profile of its own, so nothing else records it).
    hub_meta = None
    if coordinator is None and cfg.hub is not None:
        hub_meta = {"name": cfg.hub.name, "nickname": cfg.hub.nickname, "role": cfg.hub.role}

    specs = [cfg.role(key) for key in role_keys]

    # Profiles removed via `remove-member --keep-profile` carry a "removed"
    # marker: re-running init must neither rewrite them nor render them into
    # teammates' SOULs — otherwise the removal is silently undone (the marker
    # wiped and the departed member back in every roster).
    def _was_removed(spec: RoleSpec) -> bool:
        profile_name = f"{prefix}-{spec.key}"
        return profile_exists(profile_name) and bool(
            read_team_metadata(profile_name).get("removed")
        )

    removed_keys = {
        spec.key for spec in ([coordinator] if coordinator else []) + specs if _was_removed(spec)
    }
    coordinator_removed = coordinator is not None and coordinator.key in removed_keys

    click.echo(f"\n🚀 Initializing team '{team_name}' with roles: {', '.join(role_keys)}")
    click.echo(f"   Profile prefix: {prefix}")
    if coordinator and not coordinator_removed:
        click.echo(f"   Coordinator: {coordinator.name} → profile: {prefix}-{coordinator.key}")
    elif coordinator:
        click.echo(
            f"   Coordinator: {coordinator.name} — profile was removed from the team "
            "(remove-member --keep-profile), skipping"
        )
    elif cfg.hub:
        click.echo(f"   Hub (render-only, no profile): {cfg.hub.name}")
    else:
        # Custom config with neither coordinator nor coordinator_fallback
        # (the builtin team always ships its M总 hub): the roster gets no hub
        # entry, yet bundled templates tell members to 只 @总管 汇报 — say so
        # instead of failing silently.
        click.echo(
            "   ⚠️  No hub declared: bundled SOUL templates tell members to @总管, "
            "but the roster has no hub entry — declare 'coordinator' or "
            "'coordinator_fallback' (or use fully custom templates)"
        )

    # The rendering roster is the UNION of this run's selected roles and the
    # team's on-disk members (not removed): re-running init with a --roles
    # subset must not silently drop still-active members from every rendered
    # SOUL — their profiles stay on disk and keep being served. Legacy
    # (pre-metadata) profiles are classified by profile suffix against the
    # builtin tables, exactly like member.py's roster rebuild.
    known_keys = {spec.key.lower() for spec in specs} | removed_keys
    if coordinator is not None:
        known_keys.add(coordinator.key.lower())
    # Names rendered into this run's roster: collect-ids matches SOUL @tags
    # by name, so an on-disk member duplicating one is an error, not a
    # silent second @-line.
    reserved_names = {spec.name for spec in specs if spec.key not in removed_keys}
    if coordinator is not None and not coordinator_removed:
        reserved_names.add(coordinator.name)
    elif cfg.hub is not None:
        reserved_names.add(cfg.hub.name)

    extra_members: list[dict[str, str]] = []
    # A profile-backed coordinator left on disk by an earlier config: it
    # leads the roster when this config declares no coordinator of its own
    # (same precedence as member.py's _load_roster, which drops recorded
    # hubs whenever a coordinator=true member exists — keeping both would
    # have init and add-member flip the roster back and forth).
    on_disk_coordinator: dict[str, str] | None = None
    builtin = builtin_team_config()
    for profile_name in list_team_profiles(prefix):
        meta = read_team_metadata(profile_name)
        if meta.get("removed"):
            continue  # removed members stand removed
        member: dict[str, str] | None = None
        key = ""
        if meta:
            key = str(meta.get("key") or "")
            if key and key.lower() not in known_keys:
                if meta.get("coordinator"):
                    if on_disk_coordinator is None:
                        on_disk_coordinator = {
                            "name": str(meta.get("name") or key),
                            "nickname": str(meta.get("nickname") or meta.get("name") or key),
                            "role": str(meta.get("role") or "总管"),
                            "open_id": f"ou_xxx_{key}",
                        }
                else:
                    member = {
                        "name": str(meta.get("name") or key),
                        "nickname": str(meta.get("nickname") or meta.get("name") or key),
                        "role": str(meta.get("role") or ""),
                        "open_id": f"ou_xxx_{key}",  # placeholder, like init's own
                    }
        else:
            # Legacy (pre-metadata) profile: classify by suffix against the
            # builtin tables; unknown suffixes fall back to the legacy name
            # table (same as member.py's _load_roster).
            suffix = profile_name.rsplit("-", 1)[-1].lower()
            spec = builtin.role(suffix)
            if spec is not None:
                key = spec.key
                member = spec.as_team_member()
            else:
                key = suffix
                fallback_name = ROLE_NAME_MAP.get(suffix, suffix)
                member = {
                    "name": fallback_name,
                    "nickname": fallback_name,
                    "role": "成员",
                    "open_id": f"ou_xxx_{suffix}",
                }
        if member is None or key.lower() in known_keys:
            continue  # covered by this run's roles / coordinator-only entry
        known_keys.add(key.lower())
        if member["name"] in reserved_names or any(
            member["name"] == m["name"] for m in extra_members
        ):
            raise click.ClickException(
                f"❌ On-disk member '{member['name']}' ({profile_name}) duplicates a name "
                "in this run's roster — names must be unique (collect-ids matches "
                "SOUL.md @tags by name). Rename the config role or the on-disk "
                "member first."
            )
        extra_members.append(member)

    if extra_members:
        click.echo(
            f"   Including {len(extra_members)} on-disk member(s) outside this run's "
            f"roles: {', '.join(m['name'] for m in extra_members)}"
        )
    if clone_from:
        click.echo(f"   Cloning from: {clone_from}")
    if dry_run:
        click.echo("   📋 DRY RUN — no changes will be made")
    click.echo()

    hermes_bin = find_hermes_bin()

    # Build team members list for template rendering: coordinator/hub first,
    # then this run's roles, then the on-disk extras above.
    active_specs = [spec for spec in specs if spec.key not in removed_keys]
    team_members = [spec.as_team_member() for spec in active_specs] + extra_members
    if coordinator and not coordinator_removed:
        team_members.insert(0, coordinator.as_team_member())
        if on_disk_coordinator is not None:
            click.echo(
                f"   ⚠️  Ignoring on-disk coordinator {on_disk_coordinator['name']}: "
                f"the config declares {coordinator.name} — remove or re-declare the "
                "old coordinator profile"
            )
    elif on_disk_coordinator is not None:
        team_members.insert(0, on_disk_coordinator)
        click.echo(
            f"   ℹ️  On-disk coordinator {on_disk_coordinator['name']} leads the roster"
            + (f" (overrides the config's hub '{cfg.hub.name}')" if cfg.hub is not None else "")
        )
    elif cfg.hub:
        # No coordinator, but a render-only hub entry exists (the builtin
        # default team ships M总; custom teams declare "coordinator_fallback").
        # Members still have a 总管 to @ — no profile is created for it, and
        # its "ou_xxx_coordinator" open_id is not auto-filled by collect-ids.
        team_members.insert(0, cfg.hub.as_team_member())

    owner_open_id = "ou_xxx_owner"  # placeholder
    env = get_jinja_env()

    success_count = 0
    fail_count = 0

    def _context_for(spec: RoleSpec) -> dict:
        return {
            "name": spec.name,
            "nickname": spec.nickname,
            "role": spec.role,
            "team_name": team_name,
            "team_members": team_members,
            "owner_open_id": owner_open_id,
            "language": "zh",
        }

    # Coordinator profile is created first (it is the team's hub). Removed
    # members (coordinator included) stay in the list so the skip is announced
    # and counted; the loop skips them before any processing.
    work: list[tuple[RoleSpec, bool]] = ([(coordinator, True)] if coordinator else []) + [
        (spec, False) for spec in specs
    ]
    skipped_count = 0
    for spec, is_coordinator in work:
        profile_name = f"{prefix}-{spec.key}"
        coord_label = " (coordinator)" if is_coordinator else ""
        click.echo(
            f"👤 [{spec.key}] {spec.name} ({spec.role}){coord_label} → profile: {profile_name}"
        )

        # Re-running init must not resurrect a member the user removed with
        # `remove-member --keep-profile`: rewriting SOUL + metadata would
        # clear the "removed" marker and silently re-activate them. Skip and
        # say how to re-join explicitly.
        if spec.key in removed_keys:
            click.echo(
                f"  ⏭️  Profile '{profile_name}' exists but was removed from the team "
                "(remove-member --keep-profile) — skipping, the removal stands\n"
                "     To re-join it: hermes-team add-member; to re-create it: "
                "delete the profile directory first"
            )
            skipped_count += 1
            click.echo()
            continue

        ok = _create_profile(
            env=env,
            hermes_bin=hermes_bin,
            profile_name=profile_name,
            team_name=team_name,
            prefix=prefix,
            template_name=spec.template,
            template_path=spec.template_path,
            context=_context_for(spec),
            clone_from=clone_from,
            metadata={
                "key": spec.key,
                "name": spec.name,
                "nickname": spec.nickname,
                "role": spec.role,
                "coordinator": is_coordinator,
                # Template provenance so member add/remove can re-render this
                # member's SOUL later: bundled name, or the external path used.
                "template": (
                    str(spec.template_path) if spec.template_path is not None else spec.template
                ),
                # Render-only hub this team's SOULs were rendered with (null
                # for coordinator teams and hub-less custom teams) — see
                # hub_meta above.
                "hub": hub_meta,
            },
            dry_run=dry_run,
        )
        if ok:
            success_count += 1
        else:
            fail_count += 1
        click.echo()

    # Summary
    click.echo("=" * 50)
    if fail_count:
        click.echo(
            f"⚠️  Team '{team_name}' partially initialized: "
            f"{success_count} role(s) created, {fail_count} failed"
        )
    else:
        click.echo(f"✅ Team '{team_name}' initialized: {success_count} role(s) created")
    if skipped_count:
        click.echo(
            f"⏭️  {skipped_count} role(s) skipped: profile kept but removed from the "
            "team (re-join explicitly via hermes-team add-member)"
        )
    click.echo()
    click.echo("📋 Next steps:")
    click.echo(f"   1. hermes-team configure --prefix {prefix}")
    click.echo(f"   2. hermes-team start --prefix {prefix}")
    click.echo("   3. In Feishu group: @all bots, wait 30s")
    click.echo(f"   4. hermes-team collect-ids --prefix {prefix}")
    click.echo(f"   5. hermes-team verify --prefix {prefix}")
    if fail_count:
        # Same convention as verify/doctor: non-zero exit on failure, so
        # scripts/CI can detect a partial init.
        sys.exit(1)
