"""init command — create Hermes profiles and generate SOUL.md for each team role."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path

import click
from jinja2 import Environment, FileSystemLoader, StrictUndefined, Undefined, select_autoescape

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
from hermes_multi_agent_team.utils.open_id import (
    atomic_write_text,
    fill_placeholders_in_text,
    harvest_own_soul_open_ids,
)
from hermes_multi_agent_team.utils.profile import (
    TEAM_METADATA_FILENAME,
    get_profile_dir,
    get_profiles_dir,
    is_standalone_profile,
    list_name_ambiguous_profiles,
    list_team_profiles,
    profile_exists,
    read_team_metadata,
    remove_tombstone,
    team_metadata_corrupt,
)


def get_templates_dir() -> Path:
    """Get the templates directory path."""
    try:
        # Python 3.9+
        return Path(resources.files("hermes_multi_agent_team.templates").joinpath("SOUL"))
    except (AttributeError, FileNotFoundError):
        # Fallback: read from filesystem
        return Path(__file__).resolve().parent.parent / "templates" / "SOUL"


def get_jinja_env(strict_undefined: bool = False) -> Environment:
    """Create a Jinja2 environment for template rendering.

    ``strict_undefined=True`` makes undefined variables (e.g. a custom
    template referencing team-only vars like ``team_members`` outside a team
    render) raise instead of silently rendering empty strings.
    """
    templates_dir = get_templates_dir()
    return Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape([]),
        keep_trailing_newline=True,
        undefined=StrictUndefined if strict_undefined else Undefined,
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


def resolve_recorded_template(ref: object) -> tuple[str | None, Path | None]:
    """Resolve the 'template' field recorded in metadata at init/add time.

    Recorded values are either a bundled template name ("pm.md.j2") or an
    absolute path to an external file. A ref that is not a non-blank string
    (nothing recorded) or that no longer resolves (file deleted, bundled
    name removed) yields (None, None) — the CALLER decides what that means,
    and the two cases are deliberately different:

    - nothing recorded → fall back to the key's builtin template (re-render
      allowed; pre-0.6 teams never had a template field);
    - recorded but unresolvable → patch-only / no re-render (re-rendering
      would overwrite the member's hand-written persona).

    Do not "simplify" callers by falling back to the builtin template here
    for both cases.
    """
    if not isinstance(ref, str) or not ref.strip():
        return None, None
    candidate = Path(ref)
    if candidate.is_absolute():
        return (str(candidate), candidate) if candidate.is_file() else (None, None)
    if (get_templates_dir() / ref).is_file():
        return ref, None
    return None, None


def _identity_of(meta: dict) -> tuple:
    """Comparable (team_name, hub-declaration) signature of a profile's metadata.

    Used to detect a subset re-run that changed the team's identity (team
    name, hub renamed, hub→coordinator switch): members whose OLD signature
    differs from the run's new one get their SOULs re-rendered, so SOUL and
    the refreshed metadata agree. A missing "hub" key ("absent") differs
    from an explicit null ("null") — the latter is a deliberate declaration.
    """
    hub = meta.get("hub")
    hub_sig = "absent" if "hub" not in meta else json.dumps(hub, sort_keys=True, ensure_ascii=False)
    return (meta.get("team"), hub_sig)


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
    # Whether the profile existed BEFORE this run — the gate for harvesting
    # ids below. Only a PRE-EXISTING SOUL may be harvested and re-applied
    # (re-run case): a profile created by THIS run — INCLUDING via
    # --clone-from, whose clone copies the SOURCE profile's SOUL.md — must
    # not, because the cloned ids belong to the source app's namespace and
    # are wrong for this profile's own app (collect-ids never rewrites real
    # ids, so they would stick forever). A fresh profile keeps placeholders,
    # filled later by collect-ids with its own app.
    existed = profile_exists(profile_name)
    if existed:
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

        def _cleanup_created() -> None:
            # This run created the profile (hermes CLI — possibly with a
            # --clone-from'd SOUL inside) but never finished writing ours:
            # remove the orphan dir, or a retry would see "existed" and
            # harvest the leftover CLONED SOUL's source-app ids into the
            # new profile (same rule as add_member's _cleanup_orphan).
            # Pre-existing profiles are NEVER cleaned up.
            if existed:
                return
            profile_dir = get_profiles_dir() / profile_name
            shutil.rmtree(profile_dir, ignore_errors=True)
            if profile_dir.exists():
                click.echo(
                    f"  ⚠️  Could not remove just-created profile dir "
                    f"'{profile_name}' — delete it manually before retrying"
                )

        try:
            soul_content = render_soul(env, template_name, template_path, context)
            profile_dir = get_profiles_dir() / profile_name
            profile_dir.mkdir(parents=True, exist_ok=True)
            soul_path = profile_dir / "SOUL.md"
            # THIS profile's own ids — only when the profile pre-existed this
            # run (re-run): the map re-applied to the render is harvested
            # from the SOUL that was there BEFORE the rewrite (open_ids are
            # per Feishu app; a cross-profile merge — or a --clone-from'd
            # SOUL — would write another app's namespace into this profile).
            own_ids = harvest_own_soul_open_ids(profile_name) if existed else {}
            if soul_path.is_symlink():
                # Never write THROUGH a symlink (write_text follows it): the
                # fresh placeholders would clobber the target's real ids and
                # nothing could restore them. The target keeps its roster;
                # metadata below still refreshes.
                click.echo(
                    f"  ⚠️  {profile_name}: SOUL.md is a symlink — its target is "
                    "left as-is; write the target or remove the link, then re-run"
                )
            else:
                # Apply the profile's own ids to the rendered CONTENT, then
                # write once, atomically — a failed write leaves the previous
                # SOUL exactly as it was (no truncation, no placeholder-only
                # file). By <at> TAG, so custom section headings (e.g.
                # 【飞书@格式】) keep their ids like the bundled 【飞书@方式】.
                new_content, _ = fill_placeholders_in_text(soul_content, own_ids)
                atomic_write_text(soul_path, new_content)
                click.echo(f"  ✅ Generated SOUL.md ({len(soul_content)} bytes)")
            metadata_path = profile_dir / TEAM_METADATA_FILENAME
            metadata_path.write_text(
                json.dumps({**metadata, "team": team_name, "prefix": prefix}, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )
            # A stale tombstone (profiles/.deleted/<name>) would keep hiding
            # the freshly (re-)created profile from listings and collect-ids.
            # Caught here, separately from the handlers below: the profile IS
            # written — a tombstone failure is a warning, not a per-role
            # failure.
            try:
                if remove_tombstone(profile_name):
                    click.echo(f"  🧹 Removed stale tombstone profiles/.deleted/{profile_name}")
            except OSError as e:
                click.echo(
                    f"  ⚠️  Could not remove tombstone profiles/.deleted/{profile_name}: {e}\n"
                    "     Delete it manually — until then the profile stays hidden from "
                    "collect-ids/verify"
                )
        # A write failure (unwritable dir, full disk) is reported as what it
        # is — the render may have succeeded — and still cleans up a profile
        # this run created.
        except OSError as e:
            click.echo(f"  ❌ Could not write SOUL.md/metadata for '{profile_name}': {e}")
            _cleanup_created()
            return False
        # Any render-time failure becomes a per-role failure, not an uncaught
        # crash: UnicodeError on reading, jinja2 errors, or an exception
        # raised BY a custom template's code ({{ 1/0 }} → ZeroDivisionError).
        # KeyboardInterrupt/SystemExit still propagate (they derive from
        # BaseException, not Exception).
        except Exception as e:  # noqa: BLE001 — deliberate: see comment above
            click.echo(f"  ❌ Failed to render template: {e}")
            _cleanup_created()
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

    # A selected role whose existing profile must NOT be re-rendered as a
    # team member — five fail-closed cases, all detected up front so the
    # roster/header/loop stay consistent:
    # - "removed": profiles removed via `remove-member --keep-profile` carry a
    #   "removed" marker; rewriting SOUL + metadata would silently re-activate
    #   the departed member in every roster.
    # - "standalone": the profile is a new-bot agent whose name collides with
    #   this team's role key; overwriting would erase the bot's persona and
    #   its standalone marker (and expose it to destroy).
    # - "foreign": the profile's metadata records ANOTHER team's prefix — the
    #   name <prefix>-<key> collides with a dash-nested team's member (key
    #   "extra-pm2" of this team vs the "team-extra" team's "pm2").
    #   Re-rendering would silently rewrite that team's member (SOUL swapped
    #   to this roster, metadata prefix/team overwritten) — the same guard
    #   add-member has ("already exists but is not part of team").
    # - "ambiguous": no recorded prefix AND the name carries a dash beyond
    #   this prefix's boundary (legacy "team-extra-pm" selected as key
    #   "extra-pm" of "team") — the name alone cannot tell this team's
    #   dash-keyed member from another team's profile, and writing here
    #   (SOUL + a fresh "prefix": "team" metadata) would claim it silently.
    # - "corrupt": unreadable metadata hides either marker above — fail
    #   closed instead of guessing.
    def _blocked_reason(spec: RoleSpec) -> str | None:
        profile_name = f"{prefix}-{spec.key}"
        if not profile_exists(profile_name):
            return None
        if team_metadata_corrupt(profile_name):
            return "corrupt"
        meta = read_team_metadata(profile_name)
        if meta.get("removed"):
            return "removed"
        if is_standalone_profile(profile_name):
            return "standalone"
        recorded_prefix = meta.get("prefix")
        if isinstance(recorded_prefix, str) and recorded_prefix and recorded_prefix != prefix:
            return "foreign"
        has_recorded_prefix = isinstance(recorded_prefix, str) and bool(recorded_prefix)
        if (
            not has_recorded_prefix
            and profile_name != prefix
            and (profile_name.rsplit("-", 1)[0] != prefix)
        ):
            return "ambiguous"
        return None

    blocked: dict[str, str] = {}  # role key (lowered) → reason
    for spec in ([coordinator] if coordinator else []) + specs:
        reason = _blocked_reason(spec)
        if reason is not None:
            blocked[spec.key.lower()] = reason
    removed_keys = {key for key, reason in blocked.items() if reason == "removed"}
    coordinator_blocked = coordinator is not None and coordinator.key.lower() in blocked
    coordinator_removed = (
        coordinator is not None and blocked.get(coordinator.key.lower()) == "removed"
    )

    click.echo(f"\n🚀 Initializing team '{team_name}' with roles: {', '.join(role_keys)}")
    click.echo(f"   Profile prefix: {prefix}")
    if coordinator and not coordinator_blocked:
        click.echo(f"   Coordinator: {coordinator.name} → profile: {prefix}-{coordinator.key}")
    elif coordinator and coordinator_removed:
        click.echo(
            f"   Coordinator: {coordinator.name} — profile was removed from the team "
            "(remove-member --keep-profile), skipping"
        )
    elif coordinator and blocked.get(coordinator.key.lower()) == "standalone":
        click.echo(
            f"   Coordinator: {coordinator.name} — profile is a standalone bot (new-bot), skipping"
        )
    elif coordinator and blocked.get(coordinator.key.lower()) == "foreign":
        click.echo(
            f"   Coordinator: {coordinator.name} — profile belongs to another team's "
            "prefix (see its metadata), skipping"
        )
    elif coordinator and blocked.get(coordinator.key.lower()) == "ambiguous":
        click.echo(
            f"   Coordinator: {coordinator.name} — profile name is ambiguous (no recorded "
            "prefix, dash beyond this prefix), skipping"
        )
    elif coordinator:
        click.echo(f"   Coordinator: {coordinator.name} — profile metadata unreadable, skipping")
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
    reserved_names = {spec.name for spec in specs if spec.key.lower() not in blocked}
    if coordinator is not None and not coordinator_blocked:
        reserved_names.add(coordinator.name)
    elif cfg.hub is not None:
        reserved_names.add(cfg.hub.name)

    extra_members: list[dict[str, str]] = []
    # Profile names of the on-disk roster members that CARRY metadata —
    # after rendering, their .hermes-team.json team/prefix/hub are refreshed
    # to this run's values (see below), so the roster-rebuild source of
    # truth agrees with the SOULs init just re-rendered.
    roster_metadata_profiles: list[str] = []
    # Their (team, hub) identity BEFORE the refresh: when the identity
    # changes, their own SOULs still reference the OLD roster (old hub
    # @-line, old team name) and are re-rendered after the refresh — see the
    # re-render pass below the work loop.
    old_identity: dict[str, tuple] = {}
    # Profile-backed coordinators left on disk by an earlier config. ONE
    # 总管 per team: several of them (or one alongside a config-declared
    # coordinator) is an inconsistent disk state — adjudicated fail-closed
    # after the scan, because silently keeping the sorted-first would let
    # init and add/remove-member lead the roster with DIFFERENT coordinators.
    on_disk_coordinators: list[tuple[str, str]] = []
    on_disk_coordinator: dict[str, str] | None = None
    builtin = builtin_team_config()
    # Legacy profiles whose names could belong to a LONGER prefix are
    # excluded from list_team_profiles — excluded here too (their team
    # membership cannot be attributed without metadata), with the reason.
    for ambiguous in list_name_ambiguous_profiles(prefix):
        click.echo(
            f"   ⚠️  {ambiguous}: name matches '{prefix}-…' but carries no recorded "
            f"prefix — it may belong to team '{ambiguous.rsplit('-', 1)[0]}'; excluded "
            "from the roster. Re-init it under its own team to record the prefix."
        )
    for profile_name in list_team_profiles(prefix):
        if team_metadata_corrupt(profile_name):
            # Fail closed: an unreadable metadata file hides any "standalone"
            # marker it carried — classifying it as a legacy (no-metadata)
            # member would write a bot into every team roster.
            click.echo(
                f"   ⚠️  {profile_name}: unreadable {TEAM_METADATA_FILENAME} — excluded "
                "from the roster (fix the file or remove the profile)"
            )
            continue
        meta = read_team_metadata(profile_name)
        if meta.get("removed"):
            continue  # removed members stand removed
        if meta.get("standalone"):
            # A new-bot agent that happens to share the team's prefix is not
            # a team member either — same guard as collect-ids and member.py's
            # roster rebuild (checked inline: meta is already loaded here, and
            # commands.bot cannot be imported without a circular import).
            continue
        member: dict[str, str] | None = None
        key = ""
        if meta:
            key = str(meta.get("key") or "")
            if key and key.lower() not in known_keys:
                if meta.get("coordinator"):
                    # Collected and adjudicated after the scan: ONE 总管 per
                    # team — several coordinator profiles must fail closed
                    # (see below), and a config-declared coordinator must not
                    # silently coexist with leftover ones.
                    on_disk_coordinators.append(
                        {
                            "profile": profile_name,
                            "name": str(meta.get("name") or key),
                            "nickname": str(meta.get("nickname") or meta.get("name") or key),
                            "role": str(meta.get("role") or "总管"),
                            "key": key,
                            "open_id": f"ou_xxx_{key}",
                        }
                    )
                    old_identity[profile_name] = _identity_of(meta)
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
        if meta:
            roster_metadata_profiles.append(profile_name)
            old_identity[profile_name] = _identity_of(meta)

    # ONE 总管 adjudication: a config-declared coordinator must not coexist
    # with leftover coordinator profiles, and several leftovers are ambiguous
    # on their own — fail closed BEFORE anything is written. Silently keeping
    # the sorted-first here would lead this roster with one coordinator while
    # add/remove-member's rebuild (same rule) errors or leads with another,
    # flipping every SOUL between 总管s.
    if on_disk_coordinators:
        listed = ", ".join(f"{c['profile']} ({c['name']})" for c in on_disk_coordinators)
        if coordinator is not None:
            raise click.ClickException(
                f"❌ The config declares coordinator {coordinator.name}, but coordinator "
                f"profile(s) already exist on disk: {listed} — remove them first "
                "(remove-member --keep-profile, or rm -rf the profile directories) so "
                "exactly one 总管 profile remains, then re-run init."
            )
        if len(on_disk_coordinators) > 1:
            raise click.ClickException(
                f"❌ Multiple coordinator profiles on disk: {listed} — a roster renders "
                "exactly one 总管. Remove the extras or re-init with a coordinator "
                "config declaring one, then retry."
            )
        on_disk_coordinator = on_disk_coordinators[0]
        roster_metadata_profiles.append(on_disk_coordinator["profile"])

    if extra_members:
        click.echo(
            f"   Including {len(extra_members)} on-disk member(s) outside this run's "
            f"roles: {', '.join(m['name'] for m in extra_members)}"
        )
    # The on-disk coordinator's name is as reserved as a declared one — an
    # extra member sharing it would render two identical-named 总管-adjacent
    # @-lines and break collect-ids' name→open_id matching. reserved_names
    # was consumed during the scan, so check the extras here.
    if on_disk_coordinator is not None:
        for m in extra_members:
            if m["name"] == on_disk_coordinator["name"]:
                raise click.ClickException(
                    f"❌ On-disk member '{m['name']}' duplicates the on-disk "
                    f"coordinator's name ({on_disk_coordinator['name']}) — names must "
                    "be unique (collect-ids matches SOUL.md @tags by name). Rename or "
                    "remove one of them first."
                )
    if clone_from:
        click.echo(f"   Cloning from: {clone_from}")
    if dry_run:
        click.echo("   📋 DRY RUN — no changes will be made")
    click.echo()

    hermes_bin = find_hermes_bin()

    # Build team members list for template rendering: coordinator/hub first,
    # then this run's roles, then the on-disk extras above. Blocked roles
    # (removed / standalone / corrupt) are neither rendered into teammates'
    # rosters nor given a profile write below.
    active_specs = [spec for spec in specs if spec.key.lower() not in blocked]
    team_members = [spec.as_team_member() for spec in active_specs] + extra_members
    if coordinator and not coordinator_blocked:
        team_members.insert(0, coordinator.as_team_member())
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

    # Ids already collected into a profile's SOUL are preserved PER PROFILE on
    # re-render: _create_profile (and the identity re-render below) harvests
    # each SOUL's OWN ids before the rewrite and re-applies them after —
    # re-running init must never reset collected @-mentions back to
    # placeholders, and (open_ids being per Feishu app) must never write one
    # app's namespace into another profile's SOUL. add/remove-member keep the
    # same guarantee; the harvest helper lives in utils/open_id.py so this
    # stays a plain module-level import (member.py imports THIS module, so
    # importing member back would be a cycle).

    success_count = 0
    fail_count = 0

    def _context_for(spec: RoleSpec) -> dict:
        return {
            "name": spec.name,
            "nickname": spec.nickname,
            "role": spec.role,
            # The bundled bot template is registered as a team-usable short
            # name ("template": "bot"); in a team render its description slot
            # is the member's role text.
            "description": spec.role,
            "team_name": team_name,
            "team_members": team_members,
            "owner_open_id": owner_open_id,
            "language": "zh",
        }

    # Coordinator profile is created first (it is the team's hub). Blocked
    # roles (coordinator included) stay in the list so the skip is announced
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

        # Fail closed when the existing profile must not become a team member:
        # re-running init must not resurrect a member removed with
        # `remove-member --keep-profile`, must not overwrite a standalone
        # bot's SOUL/metadata (that would erase its persona and standalone
        # marker — and expose it to destroy), must not steal another team's
        # profile (its metadata records a different prefix), and must not
        # guess when the metadata is unreadable (it may hide either marker).
        reason = blocked.get(spec.key.lower())
        if reason == "removed":
            click.echo(
                f"  ⏭️  Profile '{profile_name}' exists but was removed from the team "
                "(remove-member --keep-profile) — skipping, the removal stands\n"
                "     To re-join it: hermes-team add-member; to re-create it: "
                "delete the profile directory first"
            )
            skipped_count += 1
            click.echo()
            continue
        if reason == "standalone":
            click.echo(
                f"  ⏭️  Profile '{profile_name}' exists but is a standalone bot (new-bot) — "
                "skipping, its SOUL/metadata are kept as-is\n"
                "     To use this role key for the team: delete the bot first "
                f"(rm -rf '{get_profiles_dir() / profile_name}') or pick another prefix"
            )
            skipped_count += 1
            click.echo()
            continue
        if reason == "foreign":
            foreign_prefix = read_team_metadata(profile_name).get("prefix")
            click.echo(
                f"  ⏭️  Profile '{profile_name}' exists but belongs to team prefix "
                f"'{foreign_prefix}' (recorded in {TEAM_METADATA_FILENAME}) — skipping, "
                "its SOUL/metadata are kept as-is: re-rendering would silently rewrite "
                "that team's member\n"
                "     To use this role key here: remove the other team's profile first "
                f"(rm -rf '{get_profiles_dir() / profile_name}') or pick another prefix"
            )
            skipped_count += 1
            click.echo()
            continue
        if reason == "ambiguous":
            click.echo(
                f"  ⏭️  Profile '{profile_name}' exists, carries no recorded prefix, and "
                "its name has a dash beyond this prefix's boundary — it may be another "
                "team's profile just as well as this team's role: skipping, its "
                "SOUL/metadata are kept as-is\n"
                "     To use this role key here: delete the profile first "
                f"(rm -rf '{get_profiles_dir() / profile_name}'), or re-init it under "
                "its owning team to record that prefix"
            )
            skipped_count += 1
            click.echo()
            continue
        if reason == "corrupt":
            click.echo(
                f"  ⏭️  Profile '{profile_name}' exists but its {TEAM_METADATA_FILENAME} is "
                "unreadable — skipping, its SOUL/metadata are kept as-is (the file "
                "may hide a removed/standalone marker)\n"
                "     Fix or delete the profile, then re-run init"
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

    # On-disk members included in this run's roster were re-rendered against
    # it — their .hermes-team.json must say so too (team/prefix/hub), or the
    # next add/remove-member rebuilds the roster from stale metadata (an old
    # team name / an old hub) and flips every SOUL back. Roles written by
    # _create_profile above already carry the current values; legacy
    # no-metadata profiles stay metadata-less (patch-only, unchanged).
    if not dry_run and roster_metadata_profiles:
        for profile_name in roster_metadata_profiles:
            meta = read_team_metadata(profile_name)
            meta["team"] = team_name
            meta["prefix"] = prefix
            meta["hub"] = hub_meta
            (get_profile_dir(profile_name) / TEAM_METADATA_FILENAME).write_text(
                json.dumps(meta, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        click.echo(
            f"🔄 Refreshed team/prefix/hub metadata for {len(roster_metadata_profiles)} "
            "on-disk member(s) re-rendered into this roster"
        )

        # When this run CHANGED the team's identity (team renamed, hub
        # renamed, hub↔coordinator switch), the unselected members' own SOULs
        # still reference the OLD roster — an old-hub @-line is a placeholder
        # collect-ids can never fill, and verify's hub exemption follows the
        # (refreshed) metadata, so a stale line would fail forever. Re-render
        # those SOULs from their recorded templates (same context; each SOUL's
        # own ids re-applied as everywhere above); a template that no longer
        # resolves keeps its SOUL as-is, with a warning naming the actual fix.
        new_identity = (team_name, json.dumps(hub_meta, sort_keys=True, ensure_ascii=False))
        for profile_name in roster_metadata_profiles:
            if old_identity.get(profile_name) == new_identity:
                continue  # identity unchanged: SOUL and metadata already agree
            meta = read_team_metadata(profile_name)
            template_name, template_path = resolve_recorded_template(meta.get("template"))
            soul_path = get_profile_dir(profile_name) / "SOUL.md"
            if (template_name is None and template_path is None) or not soul_path.exists():
                click.echo(
                    f"  ⚠️  {profile_name}: team/hub identity changed but its template is "
                    "not recoverable — its SOUL keeps the OLD roster lines (an old-hub "
                    "placeholder can never be auto-filled; verify will keep failing for "
                    "it). Restore the recorded template and re-run init, or edit the "
                    "SOUL by hand."
                )
                continue
            name = str(meta.get("name") or "")
            role = str(meta.get("role") or "")
            try:
                content = render_soul(
                    env,
                    template_name or "",
                    template_path,
                    {
                        "name": name,
                        "nickname": str(meta.get("nickname") or name),
                        "role": role,
                        "description": role,  # bot-template team renders read the role text
                        "team_name": team_name,
                        "team_members": team_members,
                        "owner_open_id": owner_open_id,
                        "language": "zh",
                    },
                )
            except Exception as e:  # noqa: BLE001 — one member's broken template must not abort init
                click.echo(
                    f"  ⚠️  {profile_name}: team/hub identity changed but re-rendering "
                    f"failed ({e}) — its SOUL keeps the OLD roster lines (verify will "
                    "keep failing for it until fixed)"
                )
                continue
            # This SOUL's own ids (its app's namespace) survive the
            # re-render — harvested before the rewrite and applied to the
            # rendered CONTENT (never a teammate's namespace: per-app id
            # isolation). These members pre-exist on disk by construction, so
            # the harvest is always legitimate here (no --clone-from case).
            # By <at> tag, so custom section headings keep their ids too.
            own_ids = harvest_own_soul_open_ids(profile_name)
            if soul_path.is_symlink():
                # Same policy as everywhere a rendered SOUL is written: never
                # write through a symlink — the placeholders would clobber
                # the target's real ids and nothing could restore them.
                click.echo(
                    f"  ⚠️  {profile_name}: SOUL.md is a symlink — skipped "
                    "(writing would replace the target's ids); write the target "
                    "or remove the link, then re-run"
                )
                continue
            try:
                # Ids applied to the content, then one atomic write: a failed
                # write leaves the SOUL exactly as it was — no truncation, no
                # placeholder-only file.
                new_content, _ = fill_placeholders_in_text(content, own_ids)
                atomic_write_text(soul_path, new_content)
            except OSError as e:
                # The SOUL on disk is untouched — warn and keep going; one
                # member's write failure must not abort the loop.
                click.echo(
                    f"  ⚠️  {profile_name}: could not write its re-rendered "
                    f"SOUL ({e}) — keeps the OLD roster lines"
                )
                continue
            click.echo(f"  🔄 {profile_name}: SOUL re-rendered to the current roster")

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
            f"⏭️  {skipped_count} role(s) skipped — existing profile(s) kept: removed from "
            "the team (re-join via hermes-team add-member), standalone bot, another "
            "team's profile (recorded prefix), an ambiguous unrecorded name, or "
            "unreadable metadata (see the per-role notes above)"
        )
    click.echo()
    click.echo("📋 Next steps:")
    # Quote the prefix for copy-paste: validate_prefix allows spaces, which
    # the shell would otherwise split into arguments (same as the wizard).
    click.echo(f"   1. hermes-team configure --prefix {shlex.quote(prefix)}")
    click.echo(f"   2. hermes-team start --prefix {shlex.quote(prefix)}")
    click.echo("   3. In Feishu group: @all bots, wait 30s")
    click.echo(f"   4. hermes-team collect-ids --prefix {shlex.quote(prefix)}")
    click.echo(f"   5. hermes-team verify --prefix {shlex.quote(prefix)}")
    if fail_count:
        # Same convention as verify/doctor: non-zero exit on failure, so
        # scripts/CI can detect a partial init.
        sys.exit(1)
