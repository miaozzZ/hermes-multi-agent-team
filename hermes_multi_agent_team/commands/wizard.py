"""new-config command — interactive wizard that writes a team config JSON.

Asks for the team name, prefix, the hub arrangement (dedicated coordinator
profile / render-only hub on the main profile / none) and the role roster
(optionally starting from the builtin five), validating every answer as it
is given (via the same validators ``init --config`` uses) so the written
file loads on the first try.
"""

from __future__ import annotations

import json
import os
import shlex
import tempfile
from pathlib import Path

import click

from hermes_multi_agent_team.team_config import (
    TeamConfigError,
    builtin_team_config,
    builtin_template_for_key,
    load_team_config,
    make_role_spec,
    validate_prefix,
    validate_role_key,
    validate_role_name,
)

_HUB_CHOICES = (
    "coordinator",  # dedicated profile, created and rendered by init
    "fallback",  # render-only entry; the user's main profile plays the hub
    "none",
)


def _ask_role(existing_keys: set[str], existing_names: set[str], default_template: str = ""):
    """Prompt for one role, validating each field as it is answered.

    Key and name re-ask immediately on an invalid or duplicate value (so a
    typo never wastes the remaining answers); the remaining fields are
    validated together by make_role_spec, and a failure there restarts the
    role. default_template is the preselected template answer (the
    coordinator passes "coordinator" since its key is arbitrary).
    """
    while True:
        while True:
            key = click.prompt("    角色 key（进入 profile 名，如 writer）")
            try:
                key = validate_role_key(key)
            except TeamConfigError as e:
                click.echo(f"    ❌ {e}")
                continue
            if key.lower() in existing_keys:
                click.echo(f"    ❌ 角色 key '{key}' 已存在")
                continue
            break

        while True:
            name = click.prompt("    显示名称（如 阿写）")
            try:
                name = validate_role_name(name)
            except TeamConfigError as e:
                click.echo(f"    ❌ {e}")
                continue
            if name in existing_names:
                click.echo(f"    ❌ 名称 '{name}' 已存在（名称必须唯一——collect-ids 按名称匹配）")
                continue
            break

        role = click.prompt("    职位（如 内容创作）")
        nickname = click.prompt("    小名", default=name, show_default=True)
        template = click.prompt(
            "    SOUL 模板（内置短名 pm/frontend/backend/qa/designer/coordinator，"
            "或模板文件路径；留空 = key 对应内置模板）",
            default=default_template,
        )
        try:
            return make_role_spec(
                key=key, name=name, role=role, nickname=nickname, template=template or None
            )
        except TeamConfigError as e:
            click.echo(f"    ❌ {e}——请重新输入该角色")
            continue


def _spec_to_config_entry(spec, omit_default_template: bool = True) -> dict:
    """A role as it appears in the JSON: template only when re-loading
    without it would resolve the same value.

    The template is omitted only when it IS the key's builtin default —
    an explicitly chosen template survives even on a builtin key, else
    the user's choice would silently revert to the key's default on load.
    Callers whose reload default differs from the key lookup (the
    coordinator always reloads as coordinator.md.j2) pass
    ``omit_default_template=False`` to record it explicitly.
    """
    entry = {"key": spec.key, "name": spec.name, "nickname": spec.nickname, "role": spec.role}
    if spec.template_path is not None:
        entry["template"] = str(spec.template_path)
    elif not omit_default_template or spec.template != builtin_template_for_key(spec.key):
        entry["template"] = spec.template
    return entry


def _ask_hub_mode() -> str:
    click.echo("\n🧠 总管（Hub）安排——团队的中枢：")
    click.echo("  1) 独立总管 profile  — init 会创建它的 profile 并渲染总管 SOUL（推荐）")
    click.echo("  2) 由主 profile 担任 — 只在成员 SOUL 里保留一个可 @ 的总管条目（render-only）")
    click.echo("  3) 不要总管          — 仅适合全员自定义模板（内置模板要求成员 @总管）")
    while True:
        choice = click.prompt("  选择 [1/2/3]", default="1", show_default=False)
        if choice in {"1", "2", "3"}:
            return _HUB_CHOICES[int(choice) - 1]
        click.echo("  ❌ 请输入 1、2 或 3")


def run_wizard(output_path: str | None) -> None:
    """Interactively build a team config JSON file."""
    # A directory passed as the OUTPUT_PATH argument is knowable before any
    # question is asked — fail now instead of wasting the user's answers.
    if output_path and Path(output_path).is_dir():
        raise click.ClickException(f"❌ {output_path} 是一个目录，请给出文件路径")
    click.echo("🪄 hermes-team 配置向导 — 生成团队配置 JSON（Ctrl+C 随时退出）\n")

    while True:
        team_name = click.prompt("团队名称（如 ContentTeam）").strip()
        if team_name:
            break
        click.echo("❌ 团队名称不能为空")
    prefix_default = team_name
    while True:
        prefix = click.prompt("Profile 名称前缀（默认同团队名）", default=prefix_default)
        try:
            prefix = validate_prefix(prefix)
            break
        except TeamConfigError as e:
            click.echo(f"❌ {e}")
            prefix_default = team_name

    hub_mode = _ask_hub_mode()
    coordinator_entry: dict | None = None
    fallback_entry: dict | None = None
    hub_keys: set[str] = set()
    hub_names: set[str] = set()

    if hub_mode == "coordinator":
        click.echo("\n🧠 总管角色：")
        spec = _ask_role(hub_keys, hub_names, default_template="coordinator")
        # The coordinator's key is arbitrary, so its resolved template is
        # always recorded explicitly — an omitted template would re-load as
        # the coordinator default even when the user picked another one
        # (e.g. key=pm with the coordinator SOUL, or key=pm + designer).
        coordinator_entry = _spec_to_config_entry(spec, omit_default_template=False)
        hub_keys.add(spec.key.lower())
        hub_names.add(spec.name)
    elif hub_mode == "fallback":
        while True:
            name = click.prompt("  总管显示名称（写在成员 SOUL 里供 @）", default="M总")
            try:
                # Same rules as any role name: strip, at-safe, not 主人.
                name = validate_role_name(name)
            except TeamConfigError as e:
                click.echo(f"  ❌ {e}")
                continue
            break
        fallback_entry = {"name": name}
        hub_names.add(name)

    # ---- roles ----
    click.echo("\n📋 角色名单：")
    roles: list[dict] = []
    existing_keys: set[str] = set(hub_keys)
    existing_names: set[str] = set(hub_names)

    if click.confirm("  从内置 5 角色（PM/前端/后端/QA/设计）开始？", default=True):
        for spec in builtin_team_config().roles:
            if click.confirm(f"  包含 {spec.name}（{spec.role}，key={spec.key}）？", default=True):
                if spec.key.lower() in existing_keys or spec.name in existing_names:
                    # e.g. the coordinator (asked first) already took key=pm
                    # or the name P酱 — adopting this builtin would produce a
                    # config the loader rejects (duplicate key / name), so
                    # skip it with a note instead.
                    click.echo(f"  ⚠️  跳过 {spec.name}：key 或名称与已选角色冲突")
                    continue
                roles.append(_spec_to_config_entry(spec))
                existing_keys.add(spec.key.lower())
                existing_names.add(spec.name)

    while True:
        if roles:
            roster = "、".join(r["name"] for r in roles)
            click.echo(f"\n  当前名单（{len(roles)}）：{roster}")
            if not click.confirm("  添加自定义角色？", default=False):
                break
        elif not click.confirm("  名单为空，添加一个角色？", default=True):
            click.echo("  ⚠️  团队至少需要一个角色")
            continue
        spec = _ask_role(existing_keys, existing_names)
        roles.append(_spec_to_config_entry(spec))
        existing_keys.add(spec.key.lower())
        existing_names.add(spec.name)

    if not roles:
        raise click.ClickException("❌ 团队至少需要一个角色（roles 不能为空）")

    # ---- assemble & write ----
    data: dict = {"team_name": team_name, "prefix": prefix, "roles": roles}
    if coordinator_entry is not None:
        data["coordinator"] = coordinator_entry
    if fallback_entry is not None:
        data["coordinator_fallback"] = fallback_entry

    default_path = f"{prefix}-team.json"
    path = Path(output_path) if output_path else Path(click.prompt("保存到", default=default_path))
    # A symlinked output path should update the real file (what a plain
    # write_text would do), not have os.replace swap the link itself for a
    # regular file while the real target goes stale. Path.resolve raises
    # RuntimeError on a symlink loop (even with strict=False) — that, like
    # the other path failures here, must be a clean ClickException, not a
    # traceback after the user already answered everything.
    if path.is_symlink():
        try:
            path = path.resolve()
        except (OSError, RuntimeError) as e:
            raise click.ClickException(f"❌ {path} 无法解析（符号链接环或目标不可用）：{e}") from e
    if path.is_dir():
        raise click.ClickException(f"❌ {path} 是一个目录，请给出文件路径")

    preview = json.dumps(data, ensure_ascii=False, indent=2)
    click.echo(f"\n📄 将写入 {path}：\n{preview}\n")
    if path.exists() and not click.confirm(f"⚠️  {path} 已存在，覆盖？", default=False):
        raise click.ClickException("已取消（未写入任何文件）")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise click.ClickException(f"❌ 无法创建目录 {path.parent}：{e}") from e

    # Round-trip validation with the same loader init uses — run on a temp
    # file in the target directory BEFORE the target is touched, then
    # os.replace swaps it in atomically: even the "should not happen"
    # failure path can never leave an unloadable file behind, and a valid
    # existing file is never clobbered by one the loader would reject.
    try:
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    except OSError as e:
        raise click.ClickException(f"❌ 无法写入 {path}：{e}") from e
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(preview + "\n")
        # Validate while the temp file still has mkstemp's 0600 (readable):
        # the target's own mode may be write-only (e.g. 0200 — a plain
        # write_text can still write it), and chmod'ing the temp to that
        # first would make it unreadable and fail validation misleadingly.
        cfg = load_team_config(tmp_path)
        # os.replace swaps inodes, so match what a plain write_text would
        # leave behind: keep the existing target's mode when overwriting
        # (mkstemp creates 0600), else apply the umask like a fresh file.
        try:
            tmp_path.chmod(path.stat().st_mode & 0o7777)
        except OSError:
            umask = os.umask(0)
            os.umask(umask)
            tmp_path.chmod(0o666 & ~umask)
        os.replace(tmp_path, path)
    except OSError as e:
        raise click.ClickException(f"❌ 无法写入 {path}：{e}") from e
    except TeamConfigError as e:
        raise click.ClickException(f"❌ 生成的配置未通过校验（不应发生）：{e}") from e
    finally:
        # No-op after a successful os.replace (the temp name no longer
        # exists); on any other exit — including Ctrl+C — it removes the
        # temp file instead of littering the target directory.
        tmp_path.unlink(missing_ok=True)

    hub_desc = (
        f"总管 {cfg.coordinator.name}（独立 profile）"
        if cfg.coordinator
        else f"总管 {cfg.hub.name}（主 profile 担任）"
        if cfg.hub
        else "无总管"
    )
    click.echo(f"✅ 配置已写入 {path}（{len(cfg.roles)} 个角色，{hub_desc}）")
    click.echo("\n📋 下一步：")
    # Quote for copy-paste: prefix/path may contain spaces (validate_prefix
    # allows them), which the shell would otherwise split into arguments.
    click.echo(f"   hermes-team init --config {shlex.quote(str(path))}")
    click.echo(f"   hermes-team configure --prefix {shlex.quote(prefix)}")
    click.echo(f"   hermes-team start --prefix {shlex.quote(prefix)}")
