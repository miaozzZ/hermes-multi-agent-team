"""init command — create Hermes profiles and generate SOUL.md for each team role."""

from __future__ import annotations

import subprocess
from importlib import resources
from pathlib import Path

import click
import jinja2
from jinja2 import Environment, FileSystemLoader, select_autoescape

from hermes_multi_agent_team.utils.gateway import find_hermes_bin
from hermes_multi_agent_team.utils.profile import get_profiles_dir, profile_exists

# Default role configurations
ROLE_DEFAULTS: dict[str, dict[str, str]] = {
    "pm": {
        "name": "P酱",
        "nickname": "小P",
        "role": "产品经理",
        "template": "pm.md.j2",
    },
    "fe": {
        "name": "F仔",
        "nickname": "小F",
        "role": "前端开发",
        "template": "frontend.md.j2",
    },
    "be": {
        "name": "B叔",
        "nickname": "小B",
        "role": "后端开发",
        "template": "backend.md.j2",
    },
    "qa": {
        "name": "Q宝",
        "nickname": "小Q",
        "role": "测试QA",
        "template": "qa.md.j2",
    },
    "ui": {
        "name": "U酱",
        "nickname": "小U",
        "role": "UI设计",
        "template": "designer.md.j2",
    },
}


def _get_templates_dir() -> Path:
    """Get the templates directory path."""
    try:
        # Python 3.9+
        return Path(resources.files("hermes_multi_agent_team.templates").joinpath("SOUL"))
    except (AttributeError, FileNotFoundError):
        # Fallback: read from filesystem
        return Path(__file__).resolve().parent.parent / "templates" / "SOUL"


def _get_jinja_env() -> Environment:
    """Create a Jinja2 environment for template rendering."""
    templates_dir = _get_templates_dir()
    return Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape([]),
        keep_trailing_newline=True,
    )


def _run_hermes(args: list[str], dry_run: bool = False) -> subprocess.CompletedProcess[str]:
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


def init_team(
    team_name: str,
    roles: str,
    prefix: str | None,
    clone_from: str | None,
    dry_run: bool,
) -> None:
    """Create Hermes profiles and generate SOUL.md for each team role."""
    prefix = prefix or team_name

    # Parse roles
    role_keys = [r.strip().lower() for r in roles.split(",") if r.strip()]
    invalid_roles = [r for r in role_keys if r not in ROLE_DEFAULTS]
    if invalid_roles:
        raise click.ClickException(
            f"❌ Unknown roles: {', '.join(invalid_roles)}. "
            f"Valid roles: {', '.join(ROLE_DEFAULTS.keys())}"
        )

    click.echo(f"\n🚀 Initializing team '{team_name}' with roles: {', '.join(role_keys)}")
    click.echo(f"   Profile prefix: {prefix}")
    if clone_from:
        click.echo(f"   Cloning from: {clone_from}")
    if dry_run:
        click.echo("   📋 DRY RUN — no changes will be made")
    click.echo()

    hermes_bin = find_hermes_bin()
    profiles_dir = get_profiles_dir()

    # Build team members list for template rendering
    team_members = []
    for role_key in role_keys:
        config = ROLE_DEFAULTS[role_key]
        team_members.append(
            {
                "name": config["name"],
                "nickname": config["nickname"],
                "role": config["role"],
                "open_id": f"ou_xxx_{role_key}",  # placeholder, filled by collect-ids
            }
        )

    # Add coordinator (the main profile)
    team_members.insert(
        0,
        {
            "name": "M总",
            "nickname": "小m",
            "role": "总管",
            "open_id": "ou_xxx_coordinator",
        },
    )

    # Add owner
    owner_open_id = "ou_xxx_owner"  # placeholder

    env = _get_jinja_env()

    success_count = 0
    fail_count = 0

    for role_key in role_keys:
        config = ROLE_DEFAULTS[role_key]
        profile_name = f"{prefix}-{role_key}"
        click.echo(f"👤 [{role_key}] {config['name']} ({config['role']}) → profile: {profile_name}")

        # Check if profile already exists
        if profile_exists(profile_name):
            click.echo(f"  ⚠️  Profile '{profile_name}' already exists, skipping creation")
        else:
            # Create profile
            cmd = [hermes_bin, "profile", "create", profile_name]
            if clone_from:
                cmd.extend(["--clone-from", clone_from])
            result = _run_hermes(cmd, dry_run=dry_run)
            if result.returncode != 0 and not dry_run:
                click.echo(f"  ❌ Failed to create profile '{profile_name}'")
                fail_count += 1
                continue

        # Generate SOUL.md from Jinja2 template
        if not dry_run:
            try:
                template = env.get_template(config["template"])
                soul_content = template.render(
                    name=config["name"],
                    nickname=config["nickname"],
                    role=config["role"],
                    team_name=team_name,
                    team_members=team_members,
                    owner_open_id=owner_open_id,
                    language="zh",
                )

                profile_dir = profiles_dir / profile_name
                profile_dir.mkdir(parents=True, exist_ok=True)
                soul_path = profile_dir / "SOUL.md"
                soul_path.write_text(soul_content, encoding="utf-8")
                click.echo(f"  ✅ Generated SOUL.md ({len(soul_content)} bytes)")
            except (OSError, jinja2.TemplateError) as e:
                click.echo(f"  ❌ Failed to render template: {e}")
                fail_count += 1
                continue
        else:
            click.echo(f"  💨 dry-run: would generate SOUL.md from {config['template']}")

        success_count += 1
        click.echo()

    # Summary
    click.echo("=" * 50)
    click.echo(f"✅ Team '{team_name}' initialized: {success_count} roles created")
    if fail_count:
        click.echo(f"❌ {fail_count} role(s) failed")
    click.echo()
    click.echo("📋 Next steps:")
    click.echo(f"   1. hermes-team configure --prefix {prefix}")
    click.echo(f"   2. hermes-team start --prefix {prefix}")
    click.echo("   3. In Feishu group: @all bots, wait 30s")
    click.echo(f"   4. hermes-team collect-ids --prefix {prefix}")
    click.echo(f"   5. hermes-team verify --prefix {prefix}")
