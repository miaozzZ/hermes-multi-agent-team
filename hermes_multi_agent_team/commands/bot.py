"""new-bot command — standalone single-function agents, no team required.

The host gateway serves every profile under profiles/, with or without a
team. ``new-bot`` gives that fact a first-class entry point: it creates the
profile, renders a simple roster-free SOUL, and marks the profile with
``standalone`` metadata so the team commands (verify / collect-ids /
add-member / remove-member) treat it as what it is — not a team member.
"""

from __future__ import annotations

import json
import shlex

import click

from hermes_multi_agent_team.commands.init import (
    get_jinja_env,
    render_soul,
    run_hermes,
)
from hermes_multi_agent_team.team_config import (
    RoleSpec,
    TeamConfigError,
    make_role_spec,
    validate_role_key,
    validate_role_name,
)
from hermes_multi_agent_team.utils.gateway import find_hermes_bin
from hermes_multi_agent_team.utils.profile import (
    TEAM_METADATA_FILENAME,
    get_profile_dir,
    profile_exists,
    remove_tombstone,
)


def new_bot(
    name: str,
    display_name: str | None,
    description: str | None,
    template: str | None,
    clone_from: str | None,
    dry_run: bool,
) -> None:
    """Create a standalone single-function agent profile."""
    # The name IS the profile name (no prefix-key joining), so it gets the
    # same filename-safety validation role keys have.
    try:
        name = validate_role_key(name)
    except TeamConfigError as e:
        raise click.ClickException(f"❌ Invalid bot name: {e}") from e

    # Hermes' default profile is special: it lives in ~/.hermes itself (never
    # under profiles/), so every listing gate (_servable_profile_entry)
    # excludes the name — a bot created here would be invisible to
    # configure/verify/collect-ids. Reject it up front, case-insensitively.
    if name.lower() == "default":
        raise click.ClickException(
            "❌ Bot name 'default' is reserved: Hermes' default profile lives in ~/.hermes "
            "itself (never under profiles/), so a profile with this name would be invisible "
            "to hermes-team (configure --prefix default finds no profiles). Pick another name."
        )

    if profile_exists(name):
        raise click.ClickException(f"❌ Profile '{name}' already exists")

    # Field-level validation with field-specific messages: a bad
    # --display-name or --description used to surface as "Invalid template"
    # because make_role_spec validates everything at once.
    try:
        display_name = validate_role_name(display_name or name)
    except TeamConfigError as e:
        raise click.ClickException(f"❌ Invalid display name: {e}") from e

    # dry-run must stay preview-only: prompting here would abort in non-TTY
    # contexts (CI) and surprise interactive users who only wanted a preview.
    # A placeholder keeps the spec buildable; the real run prompts as usual.
    if not description and not dry_run:
        description = click.prompt(f"  {display_name} 的功能描述（一句话，如：签到打卡机器人）")
    description = (description or "").strip()
    if not description:
        if dry_run:
            description = "(dry-run placeholder — pass --description to set one)"
        else:
            raise click.ClickException("❌ Invalid description: must be a non-empty string")
    # Same at-safety rule make_role_spec enforces for roles, checked here so
    # the error names the actual field.
    if any(ch in description for ch in "<>\n\r"):
        raise click.ClickException(
            "❌ Invalid description: must not contain '<', '>' or newlines "
            "(it is embedded in SOUL.md)"
        )

    # Template resolution mirrors the rest of the tool: an explicit --template
    # is a file path (resolved against the cwd — the user typed it) or a
    # builtin short name. The default (omitted --template) is the PACKAGED
    # roster-free bot SOUL, built directly: make_role_spec resolves names
    # against the cwd first, so a stray file named 'bot' (or 'bot.md.j2') in
    # the working directory would silently shadow the default.
    # name/role were validated above, so the direct RoleSpec is safe.
    if template is None:
        spec = RoleSpec(
            key=name,
            name=display_name,
            role=description,
            nickname=display_name,
            template="bot.md.j2",
        )
    else:
        try:
            spec = make_role_spec(key=name, name=display_name, role=description, template=template)
        except TeamConfigError as e:
            raise click.ClickException(f"❌ Invalid template: {e}") from e

    # Bundled TEAM templates (coordinator/pm/frontend/…) render a roster, hub
    # rules and an @主人 line whose open_id collect-ids never fills for a
    # standalone bot — with only a name/description context they used to
    # render silently-broken SOULs (empty interpolations, exit 0). Reject
    # them; standalone bots get the roster-free `bot` template or a custom file.
    if spec.template_path is None and spec.template != "bot.md.j2":
        raise click.ClickException(
            f"❌ Template '{spec.template}' is a team template — it renders a team roster "
            "and @-mention lines that a standalone bot has no context for. Use the "
            "roster-free builtin 'bot' template (default) or pass a custom template file."
        )

    click.echo(f"\n🤖 Creating standalone bot '{name}'")
    click.echo(f"   功能：{description}")
    template_src = str(spec.template_path) if spec.template_path else spec.template
    click.echo(f"   SOUL 模板：{template_src}")
    if clone_from:
        click.echo(f"   Cloning model config from: {clone_from}")
    if dry_run:
        click.echo("   📋 DRY RUN — no changes will be made")

    # Render BEFORE creating the profile — and before the dry-run returns: a
    # broken template (syntax error, {{ 1/0 }}, or a custom template
    # referencing team-only variables like team_members) must fail here
    # rather than leave a half-created profile blocking a retry (same
    # guarantee add-member's cleanup gives), and a --dry-run preview must not
    # promise a SOUL the real run cannot produce. Rendering is side-effect
    # free. StrictUndefined turns silent empty interpolations into errors.
    try:
        soul = render_soul(
            get_jinja_env(strict_undefined=True),
            spec.template,
            spec.template_path,
            {"name": display_name, "description": description, "language": "zh"},
        )
    except Exception as e:
        raise click.ClickException(f"❌ Failed to render SOUL for {name}: {e}") from e

    cmd = [find_hermes_bin(), "profile", "create", name]
    if clone_from:
        cmd.extend(["--clone-from", clone_from])
    if dry_run:
        click.echo(f"  💨 dry-run: {' '.join(cmd)}")
        click.echo(f"  💨 dry-run: would generate SOUL.md + metadata for {name}")
        return

    result = run_hermes(cmd)
    if result.returncode != 0:
        raise click.ClickException(f"❌ Failed to create profile '{name}'")

    profile_dir = get_profile_dir(name)
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "SOUL.md").write_text(soul, encoding="utf-8")
    metadata = {
        "standalone": True,
        "key": name,
        "name": display_name,
        "nickname": display_name,
        "role": description,
        "coordinator": False,
        "template": (str(spec.template_path) if spec.template_path is not None else spec.template),
    }
    (profile_dir / TEAM_METADATA_FILENAME).write_text(
        json.dumps(metadata, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    click.echo(f"  ✅ {name}: SOUL.md + metadata written")
    # A stale tombstone (profiles/.deleted/<name>) from an earlier deletion
    # would keep hiding the freshly created profile from listings,
    # collect-ids and the host — same cleanup init/add-member do.
    try:
        if remove_tombstone(name):
            click.echo(f"  🧹 Removed stale tombstone profiles/.deleted/{name}")
    except OSError as e:
        click.echo(
            f"  ⚠️  Could not remove tombstone profiles/.deleted/{name}: {e}\n"
            "     Delete it manually — until then the profile stays hidden from "
            "collect-ids/verify"
        )

    click.echo()
    click.echo(f"✅ Standalone bot '{name}' created")
    click.echo("📋 Next steps:")
    click.echo(
        f"   1. hermes-team configure --prefix {shlex.quote(name)}   (needs its own Feishu app)"
    )
    click.echo("   2. Add the bot to a Feishu group (it is served by the host gateway)")
    click.echo(
        f"   3. Daily use: hermes -p {shlex.quote(name)} chat / cron; park with hermes -p {shlex.quote(name)} gateway stop"
    )
