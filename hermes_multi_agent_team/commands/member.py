"""add-member / remove-member — grow or shrink an existing team.

Both commands keep every member's SOUL.md roster in sync:

- Roster is reconstructed from the per-profile ``.hermes-team.json`` metadata
  init wrote (legacy teams without metadata fall back to the builtin tables,
  including the render-only M总 hub every pre-metadata init rendered; teams
  created since the hub is recorded in metadata rebuild it from there).
  Profiles kept on disk via ``remove-member --keep-profile`` carry a
  ``removed`` marker in their metadata and are skipped — a departed member
  must never be re-rendered back into the SOULs.
- open_ids already collected into SOULs are harvested BEFORE any rewrite and
  re-applied after, so adding a member never resets the team to placeholders.
- Each existing member's SOUL is re-rendered from its template when that
  template is recoverable (metadata template). When it is not (custom
  template whose file is gone, or a legacy pre-metadata profile — its team
  name was never recorded, so a re-render would rename the team to the
  prefix), only the 【飞书@方式】 section is patched: the new member's @-line
  inserted, or the departing member's lines dropped. For such legacy teams
  the original team name is recovered from the surviving SOULs so the new
  member's SOUL does not rename the team to the prefix.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path

import click

from hermes_multi_agent_team.commands.collect_ids import ROLE_NAME_MAP
from hermes_multi_agent_team.commands.init import (
    get_jinja_env,
    get_templates_dir,
    render_soul,
    resolve_recorded_template,
    run_hermes,
)
from hermes_multi_agent_team.team_config import (
    TeamConfigError,
    builtin_team_config,
    builtin_template_for_key,
    make_role_spec,
)
from hermes_multi_agent_team.utils.gateway import find_hermes_bin
from hermes_multi_agent_team.utils.open_id import harvest_team_open_ids, update_soul_md_open_ids
from hermes_multi_agent_team.utils.profile import (
    TEAM_METADATA_FILENAME,
    get_profile_dir,
    get_profiles_dir,
    is_standalone_profile,
    list_name_ambiguous_profiles,
    list_team_profiles,
    profile_exists,
    read_soul,
    read_team_metadata,
    remove_tombstone,
    team_metadata_corrupt,
)

# Every pre-metadata init (v0.4 and earlier) rendered this hub entry into all
# SOULs unconditionally, so legacy rosters must include it when rebuilding.
_LEGACY_HUB_KEY = "coordinator"
_LEGACY_HUB = {
    "key": _LEGACY_HUB_KEY,
    "name": "M总",
    "nickname": "小m",
    "role": "总管",
}


@dataclass
class Member:
    """One roster entry reconstructed from metadata (or the legacy tables)."""

    key: str
    name: str
    nickname: str
    role: str
    coordinator: bool
    # None → render-only hub entry (no profile, no SOUL of its own).
    profile_name: str | None
    template_name: str | None = None  # bundled template file name
    template_path: Path | None = None  # external template file

    def as_team_member(self) -> dict[str, str]:
        """The dict the SOUL templates receive in the team_members loop."""
        return {
            "name": self.name,
            "nickname": self.nickname,
            "role": self.role,
            "open_id": "ou_xxx_coordinator" if self.profile_name is None else f"ou_xxx_{self.key}",
        }


# Moved to init.py (which owns get_templates_dir and is the module member.py
# imports from): shared by member.py's roster rebuild and init's on-disk
# re-render, with the two-case semantics documented there.
_resolve_recorded_template = resolve_recorded_template


def _member_from_metadata(profile_name: str, meta: dict) -> Member:
    recorded_template = meta.get("template")
    template_name, template_path = _resolve_recorded_template(recorded_template)
    key = str(meta.get("key") or "")
    if (
        template_name is None
        and template_path is None
        and not (isinstance(recorded_template, str) and recorded_template.strip())
    ):
        # Metadata recorded NO template at all (pre-0.6 teams): the key's
        # builtin template is the documented fallback.
        template_name = builtin_template_for_key(key)
    # A template that WAS recorded but no longer resolves (external file
    # deleted, bundled name removed) deliberately stays (None, None):
    # _template_renderable → False → only the 【飞书@方式】 section is
    # patched. Falling back to the builtin template here would re-render the
    # member's hand-written persona away — the opposite of the promise in
    # this module's docstring ("自定义模板文件已不存在——不覆盖手写人设").
    return Member(
        key=key,
        name=str(meta.get("name") or ""),
        nickname=str(meta.get("nickname") or meta.get("name") or ""),
        role=str(meta.get("role") or ""),
        coordinator=bool(meta.get("coordinator")),
        profile_name=profile_name,
        template_name=template_name,
        template_path=template_path,
    )


def _hub_from_metadata(raw: object) -> Member | None:
    """Rebuild the render-only hub recorded in profile metadata at init time.

    init writes ``"hub": {"name": …, "nickname": …, "role": …}`` (null when
    the team declares a coordinator or no hub at all) so later roster
    rebuilds do not have to infer the hub from missing metadata.
    """
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    return Member(
        key=_LEGACY_HUB_KEY,
        name=name,
        nickname=str(raw.get("nickname") or name),
        role=str(raw.get("role") or "总管"),
        coordinator=True,
        profile_name=None,
        template_name="coordinator.md.j2",
    )


# Legacy SOULs rendered from the bundled templates open with
# "你是<team_name>团队的…" — the only place a pre-metadata team's real name
# survives. The character class keeps the match off the persona line
# ("你是<name>，小名"…"，团队的…" — those captures contain ，/引号), so only
# the team_name line matches.
_TEAM_NAME_RE = re.compile(r'你是([^，。"\n]{1,50}?)团队的')


def _recover_team_name(members: list[Member]) -> str | None:
    """Best-effort recovery of a legacy team's original name from its SOULs.

    Used only when no metadata recorded a team name: rendering a new member
    with the prefix as the name would rename the team (e.g. "BaGoet团队"
    silently becoming "baoget团队"). Returns None when no SOUL matches —
    the caller then falls back to the prefix.
    """
    for member in members:
        if member.profile_name is None:
            continue
        soul = read_soul(member.profile_name)
        if not soul:
            continue
        match = _TEAM_NAME_RE.search(soul)
        if match:
            recovered = match.group(1).strip()
            if recovered:
                return recovered
    return None


def _load_roster(prefix: str, profiles: list[str]) -> tuple[str, list[Member], Member | None]:
    """Rebuild (team_name, members, render-only hub) from the profiles on disk."""
    builtin = builtin_team_config()
    # Legacy profiles excluded from `profiles` because their names could
    # belong to a longer prefix: say why, or add/remove-member silently
    # building a roster without them looks like data loss.
    for name in list_name_ambiguous_profiles(prefix):
        click.echo(
            f"  ⚠️  {name}: name matches '{prefix}-…' but carries no recorded prefix — "
            f"it may belong to team '{name.rsplit('-', 1)[0]}'; excluded from the roster. "
            "Re-init it under its own team to record the prefix and remove the ambiguity."
        )
    members: list[Member] = []
    hub: Member | None = None
    team_name: str | None = None
    legacy = False
    # Whether ANY metadata-carrying profile records the "hub" key — even as
    # null. A team whose init/add-member wrote "hub": null deliberately has
    # NO render-only hub (coordinator team or hub-less config); injecting the
    # legacy M总 into it because some OTHER profile predates metadata would
    # render a hub the team never declared. Only teams with no hub record at
    # all (pure pre-metadata legacy teams) get the M总 fallback.
    hub_declared = False

    for profile_name in profiles:
        if team_metadata_corrupt(profile_name):
            # Fail closed: an unreadable metadata file hides any "standalone"
            # or "removed" marker it carried — classifying it as a legacy
            # (no-metadata) member would write a bot into every roster.
            click.echo(
                f"  ⚠️  {profile_name}: unreadable {TEAM_METADATA_FILENAME} — skipped "
                "(fix the file or remove the profile)"
            )
            continue
        meta = read_team_metadata(profile_name)
        if meta.get("removed"):
            # Kept on disk by `remove-member --keep-profile` but no longer a
            # team member: skip it, or the departed member would be
            # re-rendered back into every SOUL on the next add/remove.
            continue
        if is_standalone_profile(profile_name):
            # A new-bot agent that happens to share the team's prefix is not
            # a team member either.
            continue
        if not meta:
            # Team created before metadata existed: classify by profile
            # suffix against the builtin tables. No template is recorded —
            # legacy SOULs are only ever PATCHED, never re-rendered (the
            # original team name lives solely in their text; re-rendering
            # would rename the team to the prefix).
            legacy = True
            suffix = profile_name.rsplit("-", 1)[-1].lower()
            spec = builtin.role(suffix)
            if spec is None:
                click.echo(
                    f"  ⚠️  {profile_name}: no metadata and unknown suffix '{suffix}', "
                    "its SOUL will only be patched (not re-rendered)"
                )
                members.append(
                    Member(
                        key=suffix,
                        name=ROLE_NAME_MAP.get(suffix, suffix),
                        nickname=ROLE_NAME_MAP.get(suffix, suffix),
                        role="成员",
                        coordinator=False,
                        profile_name=profile_name,
                    )
                )
                continue
            members.append(
                Member(
                    key=spec.key,
                    name=spec.name,
                    nickname=spec.nickname,
                    role=spec.role,
                    coordinator=False,
                    profile_name=profile_name,
                )
            )
            continue
        team_name = team_name or (str(meta["team"]) if meta.get("team") else None)
        if "hub" in meta:
            # The key itself is the declaration (null = "no hub", a dict = the
            # hub); scan every profile so a hub hidden behind a null-first
            # ordering is still found in mixed old/new states.
            hub_declared = True
            if hub is None:
                hub = _hub_from_metadata(meta.get("hub"))
        members.append(_member_from_metadata(profile_name, meta))

    # Same roster invariants init enforces on its on-disk union scan — init
    # and add/remove-member must not build different (or non-unique) rosters
    # from one disk state:
    # 1. ONE coordinator: several coordinator=true profiles (e.g. left by
    #    re-running init with different configs) would render N 总管 entries
    #    into every SOUL. Picking any one of them silently would also FLIP
    #    the roster between init runs (init's config coordinator wins there,
    #    the sorted-first wins here) — fail closed instead: the disk state
    #    itself is inconsistent and must be cleaned before any roster change.
    coordinators = [m for m in members if m.coordinator]
    if len(coordinators) > 1:
        listed = ", ".join(f"{c.profile_name} ({c.name})" for c in coordinators)
        raise click.ClickException(
            f"❌ Multiple coordinator profiles on disk: {listed} — a roster renders "
            "exactly one 总管. Remove the extras (remove-member --keep-profile or "
            "rm -rf) or re-init with a single coordinator config, then retry."
        )
    # 2. Unique keys and unique names (init raises the same error): duplicate
    #    keys mean two profiles fight over one <prefix>-<key>; duplicate
    #    names make collect-ids' name→open_id mapping ambiguous and render
    #    identical @-lines.
    seen_keys: dict[str, str] = {}
    seen_names: dict[str, str] = {}
    for m in members:
        lowered = m.key.lower()
        if lowered in seen_keys:
            raise click.ClickException(
                f"❌ Duplicate role key '{m.key}' on disk: {seen_keys[lowered]} and "
                f"{m.profile_name} — remove or fix one of them before changing the roster"
            )
        seen_keys[lowered] = str(m.profile_name)
        if m.name in seen_names:
            raise click.ClickException(
                f"❌ Duplicate member name '{m.name}' on disk: {seen_names[m.name]} and "
                f"{m.profile_name} — names must be unique (collect-ids matches SOUL.md "
                "@tags by name)"
            )
        seen_names[m.name] = str(m.profile_name)
    if hub is not None and hub.name in seen_names:
        raise click.ClickException(
            f"❌ Render-only hub name '{hub.name}' duplicates the member of "
            f"{seen_names[hub.name]} — names must be unique (collect-ids matches "
            "SOUL.md @tags by name)"
        )

    # A declared coordinator (metadata coordinator=true) beats every hub —
    # recorded in metadata or the legacy fallback. Keeping both would render
    # two 总管 entries into every SOUL (e.g. a team migrated to a coordinator
    # config while some old profile still carries a hub field).
    if any(m.coordinator for m in members):
        if hub is not None:
            click.echo(
                "  ⚠️  Ignoring the render-only hub recorded in metadata: the team has a "
                "declared coordinator — keeping both would render two 总管 entries"
            )
        hub = None
    elif legacy and hub is None and not hub_declared:
        # The legacy M总 fallback is ONLY for pre-metadata teams that never
        # declared a hub (directly or via "hub": null) and no coordinator.
        hub = Member(
            key=_LEGACY_HUB["key"],
            name=_LEGACY_HUB["name"],
            nickname=_LEGACY_HUB["nickname"],
            role=_LEGACY_HUB["role"],
            coordinator=True,
            profile_name=None,
            template_name="coordinator.md.j2",
        )

    if team_name is None:
        team_name = _recover_team_name(members)
    return team_name or prefix, members, hub


def _roster_order(members: list[Member], hub: Member | None) -> list[Member]:
    """Rendering order: render-only hub / coordinator first, then the rest."""
    ordered: list[Member] = []
    if hub is not None:
        ordered.append(hub)
    ordered.extend(sorted(members, key=lambda m: not m.coordinator))
    return ordered


def _context_for(member: Member, team_name: str, team_members: list[dict[str, str]]) -> dict:
    return {
        "name": member.name,
        "nickname": member.nickname,
        "role": member.role,
        # Team renders of the bundled bot template ("template": "bot") read a
        # description slot — same context shape init's renders get.
        "description": member.role,
        "team_name": team_name,
        "team_members": team_members,
        "owner_open_id": "ou_xxx_owner",
        "language": "zh",
    }


def _template_renderable(member: Member) -> bool:
    if member.template_path is not None:
        return member.template_path.is_file()
    return (
        member.template_name is not None and (get_templates_dir() / member.template_name).is_file()
    )


def _patch_at_section(soul_path: Path, add_member: Member | None, remove_names: set[str]) -> bool:
    """Surgical roster update for members whose template is unrecoverable.

    Adds add_member's @-line (before the owner line) and drops the @-lines of
    remove_names, inside the 【飞书@方式】 section only. Returns True when the
    section was found and the file (possibly) changed.
    """
    content = soul_path.read_text(encoding="utf-8")
    section_start = content.find("【飞书@方式】")
    if section_start == -1:
        return False

    next_heading = re.search(r"\n【[^】]+】", content[section_start + 1 :])
    section_end = section_start + 1 + next_heading.start() if next_heading else len(content)

    lines = content[section_start:section_end].split("\n")
    at_re = re.compile(r"<at user_id=\"[^\"]*\">([^<]+)</at>")

    kept: list[str] = []
    for line in lines:
        match = at_re.search(line)
        if match and match.group(1) in remove_names:
            continue
        kept.append(line)

    if add_member is not None:
        new_line = (
            f"- @{add_member.name}（{add_member.role}）："
            f'`<at user_id="ou_xxx_{add_member.key}">{add_member.name}</at>`'
        )
        insert_at = len(kept)
        for i, line in enumerate(kept):
            if ">主人<" in line:
                insert_at = i
                break
        kept.insert(insert_at, new_line)

    new_content = content[:section_start] + "\n".join(kept) + content[section_end:]
    soul_path.write_text(new_content, encoding="utf-8")
    return True


# Shared with init (re-runs harvest before re-rendering): lives in
# utils/open_id.py next to harvest_open_ids, so neither command module
# imports the other for it.
_harvest_team_ids = harvest_team_open_ids


def _rebuild_souls(
    roster: list[Member],
    targets: list[Member],
    team_name: str,
    harvested: dict[str, str],
    add_member: Member | None,
    remove_names: set[str],
    dry_run: bool,
) -> int:
    """Re-render (or patch) the target members' SOULs for the given roster.

    ``roster`` is the FULL rendering roster (hub first, new member included,
    departed member excluded) — every SOUL is rendered against it, including
    the new member's own (written separately by the caller). ``targets`` is
    the subset whose SOULs get rewritten here.

    Returns the number of profiles updated.
    """
    env = get_jinja_env()
    team_members = [m.as_team_member() for m in roster]
    updated = 0

    for member in targets:
        if member.profile_name is None:
            continue  # render-only hub has no SOUL of its own
        soul_path = get_profile_dir(member.profile_name) / "SOUL.md"
        if not soul_path.exists():
            continue

        if _template_renderable(member):
            if dry_run:
                src = str(member.template_path or member.template_name)
                click.echo(f"  💨 dry-run: would re-render {member.profile_name}'s SOUL from {src}")
                updated += 1
                continue
            try:
                content = render_soul(
                    env,
                    member.template_name or "",
                    member.template_path,
                    _context_for(member, team_name, team_members),
                )
            except Exception as e:  # noqa: BLE001 — one member's broken template must not abort the team
                click.echo(
                    f"  ⚠️  {member.profile_name}: template render failed ({e}), "
                    "patching 【飞书@方式】 only"
                )
                if _patch_at_section(soul_path, add_member, remove_names):
                    update_soul_md_open_ids(soul_path, harvested)
                    updated += 1
                continue
            soul_path.write_text(content, encoding="utf-8")
            # Re-apply the ids collected earlier so a roster change never
            # resets teammates' open_ids back to placeholders.
            update_soul_md_open_ids(soul_path, harvested)
            updated += 1
        else:
            if dry_run:
                click.echo(
                    f"  💨 dry-run: would patch {member.profile_name}'s "
                    "【飞书@方式】 section (template not recoverable)"
                )
                updated += 1
                continue
            if _patch_at_section(soul_path, add_member, remove_names):
                update_soul_md_open_ids(soul_path, harvested)
                updated += 1

    return updated


def _hub_as_metadata(hub: Member | None) -> dict[str, str] | None:
    """Serialize the render-only hub for a profile's metadata (None → no hub)."""
    if hub is None:
        return None
    return {"name": hub.name, "nickname": hub.nickname, "role": hub.role}


def add_member(
    prefix: str,
    key: str,
    name: str,
    role: str,
    nickname: str | None,
    template: str | None,
    clone_from: str | None,
    dry_run: bool,
) -> None:
    """Add a member: create the profile, then sync every member's SOUL roster."""
    profiles = list_team_profiles(prefix)
    if not profiles:
        raise click.ClickException(
            f"❌ No profiles found with prefix '{prefix}'. Run 'hermes-team init' first."
        )

    team_name, members, hub = _load_roster(prefix, profiles)

    # Build the normalized spec FIRST and check duplicates against its
    # stripped values: raw CLI input like "--name 'P酱 '" or "--key ' PM '"
    # used to bypass these checks and land as a duplicate in the roster.
    try:
        spec = make_role_spec(key=key, name=name, role=role, nickname=nickname, template=template)
    except TeamConfigError as e:
        raise click.ClickException(f"❌ Invalid member: {e}") from e

    existing_keys = {m.key.lower() for m in members} | ({hub.key.lower()} if hub else set())
    existing_names = {m.name for m in members} | ({hub.name} if hub else set())
    if spec.key.lower() in existing_keys:
        raise click.ClickException(f"❌ Role key '{spec.key}' already exists in team '{prefix}'")
    if spec.name in existing_names:
        raise click.ClickException(
            f"❌ Name '{spec.name}' already exists in team '{prefix}' (names must be unique — "
            "collect-ids matches SOUL.md @tags by name)"
        )

    new_profile = f"{prefix}-{spec.key}"
    # A pre-existing directory is only acceptable when it is a profile kept
    # via `remove-member --keep-profile` re-joining under the same key: its
    # metadata carries the "removed" marker AND still records THIS team's
    # prefix — a removed member of ANOTHER team (dash-nested name collision,
    # e.g. team-extra's pm2 seen as key "extra-pm2" of team) must not be
    # re-used and overwritten here.
    rejoining = profile_exists(new_profile)
    if rejoining:
        existing_meta = read_team_metadata(new_profile)
        recorded_prefix = existing_meta.get("prefix")
        is_foreign = (
            isinstance(recorded_prefix, str) and recorded_prefix and recorded_prefix != prefix
        )
        if is_foreign:
            raise click.ClickException(
                f"❌ Profile '{new_profile}' belongs to team prefix '{recorded_prefix}' "
                f"(recorded in {TEAM_METADATA_FILENAME}) — it cannot re-join team "
                f"'{prefix}'. Remove that team's profile first or pick another key/prefix."
            )
        if not existing_meta.get("removed"):
            raise click.ClickException(
                f"❌ Profile '{new_profile}' already exists but is not part of team '{prefix}'"
            )

    new_member = Member(
        key=spec.key,
        name=spec.name,
        nickname=spec.nickname,
        role=spec.role,
        coordinator=False,
        profile_name=new_profile,
        template_name=None if spec.template_path else spec.template,
        template_path=spec.template_path,
    )

    click.echo(f"\n➕ Adding [{spec.key}] {spec.name} ({spec.role}) to team '{team_name}'")
    click.echo(f"   Profile: {new_profile}")
    if dry_run:
        click.echo("   📋 DRY RUN — no changes will be made")

    # Harvest BEFORE anything is rewritten.
    harvested = _harvest_team_ids(profiles)

    # 1. Create the profile via hermes CLI (aborts on failure, before any
    #    SOUL is touched). A re-joining kept profile reuses its directory.
    if rejoining:
        click.echo(f"   ♻️  Re-using kept profile '{new_profile}' (was removed from the team)")
        if clone_from:
            click.echo(
                "   ⚠️  --clone-from has no effect when re-joining an existing profile: "
                "its model config is kept as-is (clone manually via hermes if needed)"
            )
    else:
        cmd = [find_hermes_bin(), "profile", "create", new_profile]
        if clone_from:
            cmd.extend(["--clone-from", clone_from])
        result = run_hermes(cmd, dry_run=dry_run)
        if result.returncode != 0 and not dry_run:
            raise click.ClickException(f"❌ Failed to create profile '{new_profile}'")

    # 2. New member's SOUL (rendered with the full roster; existing members'
    #    harvested ids are applied right away) + metadata.
    if not dry_run:
        roster = _roster_order(members + [new_member], hub)
        team_members = [m.as_team_member() for m in roster]

        def _cleanup_orphan() -> None:
            # A freshly created profile dir must not be left behind: it would
            # block a retry with "already exists ... not part of team" once
            # the failure is fixed. (A re-joining kept profile keeps its
            # directory and its "removed" marker — nothing was overwritten.)
            if rejoining:
                return
            profile_dir = get_profile_dir(new_profile)
            shutil.rmtree(profile_dir, ignore_errors=True)
            if profile_dir.exists():
                click.echo(
                    f"  ⚠️  Could not remove just-created profile dir '{new_profile}' — "
                    "delete it manually before retrying"
                )

        try:
            content = render_soul(
                get_jinja_env(),
                spec.template,
                spec.template_path,
                _context_for(new_member, team_name, team_members),
            )
        except Exception as e:
            _cleanup_orphan()
            raise click.ClickException(f"❌ Failed to render SOUL for {spec.name}: {e}") from e
        # SOUL + metadata writes share the render failure's cleanup: an
        # OSError here (unwritable directory, full disk) used to escape as a
        # bare traceback AND leave a config.yaml-only orphan profile dir.
        try:
            profile_dir = get_profile_dir(new_profile)
            profile_dir.mkdir(parents=True, exist_ok=True)
            soul_path = profile_dir / "SOUL.md"
            soul_path.write_text(content, encoding="utf-8")
            update_soul_md_open_ids(soul_path, harvested)
            metadata = {
                "key": spec.key,
                "name": spec.name,
                "nickname": spec.nickname,
                "role": spec.role,
                "coordinator": False,
                "team": team_name,
                "prefix": prefix,
                "template": (
                    str(spec.template_path) if spec.template_path is not None else spec.template
                ),
                # Persist the render-only hub (whatever its origin: metadata or
                # the legacy fallback) so future roster rebuilds keep it.
                "hub": _hub_as_metadata(hub),
            }
            (profile_dir / TEAM_METADATA_FILENAME).write_text(
                json.dumps(metadata, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        except OSError as e:
            _cleanup_orphan()
            raise click.ClickException(
                f"❌ Could not write SOUL/metadata for {new_profile}: {e}\n"
                "   Check the profile directory's permissions/free space and retry."
            ) from e
        click.echo(f"  ✅ {new_profile}: SOUL.md + metadata written")
        # A tombstone from an earlier remove-member (delete mode) would keep
        # hiding the freshly re-added profile from list_team_profiles and
        # collect-ids even though this command just rebuilt it.
        try:
            if remove_tombstone(new_profile):
                click.echo(f"  🧹 Removed stale tombstone profiles/.deleted/{new_profile}")
        except OSError as e:
            click.echo(
                f"  ⚠️  Could not remove tombstone profiles/.deleted/{new_profile}: {e}\n"
                "     Delete it manually — until then the profile stays hidden from "
                "collect-ids/verify"
            )
    else:
        click.echo(f"  💨 dry-run: would generate SOUL.md + metadata for {new_profile}")

    # 3. Teammates' SOULs learn the new roster member.
    updated = _rebuild_souls(
        _roster_order(members + [new_member], hub),
        members,
        team_name,
        harvested,
        add_member=new_member,
        remove_names=set(),
        dry_run=dry_run,
    )

    click.echo()
    click.echo(f"✅ Member added; {updated} teammate SOUL(s) updated")
    click.echo("📋 Next steps:")
    # shlex.quote: prefixes may contain spaces (validate_prefix allows them) —
    # copy-pasting an unquoted command would split into arguments.
    click.echo(
        f"   1. hermes-team configure --prefix {shlex.quote(prefix)}   (new member needs its own Feishu app)"
    )
    click.echo("   2. Add the new bot to the Feishu group")
    click.echo("   3. Wait ~30s (host gateway rescans profiles automatically)")
    click.echo(
        f"   4. hermes-team collect-ids --prefix {shlex.quote(prefix)}  (fills the new member's open_id)"
    )
    click.echo(f"   5. hermes-team verify --prefix {shlex.quote(prefix)}")


def remove_member(
    prefix: str,
    key: str,
    keep_profile: bool,
    force: bool,
    dry_run: bool,
) -> None:
    """Remove a member: drop their profile and sync every remaining SOUL."""
    profiles = list_team_profiles(prefix)
    if not profiles:
        raise click.ClickException(
            f"❌ No profiles found with prefix '{prefix}'. Run 'hermes-team init' first."
        )

    team_name, members, hub = _load_roster(prefix, profiles)
    target = next((m for m in members if m.key.lower() == key.lower()), None)
    if target is None:
        valid = ", ".join(sorted(m.key for m in members))
        raise click.ClickException(
            f"❌ No member with key '{key}' in team '{prefix}'. Valid keys: {valid}"
        )
    if len(members) == 1:
        raise click.ClickException(
            "❌ Cannot remove the last member of a team — use `hermes-team destroy` instead"
        )

    disposition = "kept (no profile deletion)" if keep_profile else "DELETED (with its data)"
    click.echo(
        f"\n➖ Removing [{target.key}] {target.name} ({target.role}) from team '{team_name}'"
    )
    click.echo(f"   Profile {target.profile_name}: {disposition}")
    if target.coordinator:
        click.echo(
            "   ⚠️  This is the team's coordinator/hub — remaining members' SOULs will be "
            "re-rendered WITHOUT a hub entry (bundled templates still tell members to "
            "@总管); consider adding a new coordinator"
        )
    if dry_run:
        click.echo("   📋 DRY RUN — no changes will be made")
    elif not force:
        click.confirm(f"⚠️  Remove {target.name}? Their profile will be {disposition}", abort=True)

    # Harvest BEFORE the deletion (the departing SOUL may hold the only copy
    # of some teammate's id... it doesn't — ids live in every SOUL — but
    # harvesting first is free and order-safe).
    harvested = _harvest_team_ids(profiles)

    remaining = [m for m in members if m is not target]

    if keep_profile:
        if dry_run:
            click.echo(
                f"  💨 dry-run: would mark {target.profile_name} as removed from the team "
                "(profile kept)"
            )
        else:
            # Persist the removal IN the kept profile's metadata: roster
            # rebuilds and collect-ids skip "removed" profiles, otherwise the
            # next add/remove would re-render the departed member back into
            # every SOUL. Re-adding the same key overwrites the marker.
            profile_dir = get_profile_dir(str(target.profile_name))
            meta = read_team_metadata(str(target.profile_name))
            meta["removed"] = True
            (profile_dir / TEAM_METADATA_FILENAME).write_text(
                json.dumps(meta, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            click.echo(f"  📌 Profile {target.profile_name} kept and marked removed from the team")
    else:
        if dry_run:
            click.echo(
                f"  💨 dry-run: would delete profile dir + tombstone for {target.profile_name}"
            )
        else:
            profile_dir = get_profile_dir(str(target.profile_name))
            try:
                shutil.rmtree(profile_dir)
            except OSError as e:
                # Swallowing the failure (ignore_errors=True) would print
                # "Deleted" and tombstone a profile whose data is still on
                # disk. Abort instead: no tombstone, no success message, no
                # SOUL rewrites — the team is left as it was.
                raise click.ClickException(
                    f"❌ Failed to delete profile directory '{target.profile_name}': {e}\n"
                    "   Nothing was tombstoned and no SOUL was changed (the directory may "
                    "be partially deleted) — resolve the error and re-run."
                ) from e
            # Tombstone (profiles/.deleted/<name>) mirrors Hermes' own
            # deleted-profile semantics: the dir must never be listed or
            # served again, and our own listing gates respect it.
            (get_profiles_dir() / ".deleted" / str(target.profile_name)).mkdir(
                parents=True, exist_ok=True
            )
            click.echo(f"  🗑️  Deleted profile {target.profile_name}")

    remaining_hub = hub  # render-only hub (if any) is unaffected by removals
    updated = _rebuild_souls(
        _roster_order(remaining, remaining_hub),
        remaining,
        team_name,
        harvested,
        add_member=None,
        remove_names={target.name},
        dry_run=dry_run,
    )

    click.echo()
    click.echo(f"✅ Member removed; {updated} remaining SOUL(s) updated")
    click.echo("📋 Manual steps:")
    click.echo("   - Remove the bot from the Feishu group (Feishu side has no API for team roster)")
    if not keep_profile:
        click.echo("   - The host gateway drops the profile on its next rescan (~30s)")
