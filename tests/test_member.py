"""Tests for add-member / remove-member."""

from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest
from click.testing import CliRunner

from hermes_multi_agent_team.cli import cli


def _fake_hermes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    binary = tmp_path / "bin" / "hermes"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setattr("shutil.which", lambda name: str(binary) if name == "hermes" else None)

    def _fake_run(cmd, **kwargs):
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", _fake_run)
    return binary


def _make_member(
    home: Path,
    profile: str,
    key: str,
    name: str,
    role: str,
    template: str,
    *,
    coordinator: bool = False,
    soul_at_names: dict[str, str] | None = None,
    nickname: str | None = None,
) -> None:
    """A profile with metadata and a SOUL whose @-section carries given ids."""
    profile_dir = home / "profiles" / profile
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / ".hermes-team.json").write_text(
        json.dumps(
            {
                "key": key,
                "name": name,
                "nickname": nickname or name,
                "role": role,
                "coordinator": coordinator,
                "team": "T",
                "prefix": "team",
                "template": template,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    # soul_at_names: display name → open_id (placeholder ids allowed)
    at_lines = "\n".join(
        f'- @{n}（成员）：`<at user_id="{oid}">{n}</at>`'
        for n, oid in (soul_at_names or {}).items()
    )
    (profile_dir / "SOUL.md").write_text(
        f'【飞书@方式】\n{at_lines}\n- @主人：`<at user_id="ou_xxx_owner">主人</at>`\n',
        encoding="utf-8",
    )


def test_add_member_syncs_rosters_and_keeps_collected_ids(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _fake_hermes(tmp_path, monkeypatch)
    _make_member(
        tmp_hermes_home,
        "team-pm",
        "pm",
        "P酱",
        "产品经理",
        "pm.md.j2",
        soul_at_names={"P酱": "ou_realpm", "Q宝": "ou_realqa"},
    )
    _make_member(
        tmp_hermes_home,
        "team-qa",
        "qa",
        "Q宝",
        "测试QA",
        "qa.md.j2",
        soul_at_names={"P酱": "ou_realpm", "Q宝": "ou_realqa"},
    )

    result = CliRunner().invoke(
        cli,
        [
            "add-member",
            "--prefix",
            "team",
            "--key",
            "writer",
            "--name",
            "阿写",
            "--role",
            "内容创作",
            "--template",
            "pm",
        ],
    )
    assert result.exit_code == 0, result.output

    # New profile with SOUL + metadata (template recorded for future rebuilds).
    writer_dir = tmp_hermes_home / "profiles" / "team-writer"
    assert (writer_dir / "SOUL.md").exists()
    meta = json.loads((writer_dir / ".hermes-team.json").read_text())
    assert meta["name"] == "阿写" and meta["template"] == "pm.md.j2"

    # Existing members' SOULs were re-rendered: new roster member present,
    # previously collected open_ids preserved (not reset to placeholders).
    pm_soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert "阿写" in pm_soul
    assert 'user_id="ou_realpm">P酱' in pm_soul
    assert 'user_id="ou_realqa">Q宝' in pm_soul
    qa_soul = (tmp_hermes_home / "profiles" / "team-qa" / "SOUL.md").read_text()
    assert "阿写" in qa_soul and 'user_id="ou_realpm"' in qa_soul

    # The new member's SOUL already carries teammates' real ids.
    writer_soul = (writer_dir / "SOUL.md").read_text()
    assert 'user_id="ou_realpm">P酱' in writer_soul


def test_add_member_rejects_duplicate_key_and_name(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _fake_hermes(tmp_path, monkeypatch)
    _make_member(tmp_hermes_home, "team-pm", "pm", "P酱", "产品经理", "pm.md.j2")

    dup_key = CliRunner().invoke(
        cli,
        [
            "add-member",
            "--prefix",
            "team",
            "--key",
            "PM",
            "--name",
            "新人",
            "--role",
            "X",
            "--template",
            "pm",
        ],
    )
    assert dup_key.exit_code != 0 and "'PM'" in dup_key.output

    dup_name = CliRunner().invoke(
        cli,
        [
            "add-member",
            "--prefix",
            "team",
            "--key",
            "new",
            "--name",
            "P酱",
            "--role",
            "X",
            "--template",
            "pm",
        ],
    )
    assert dup_name.exit_code != 0 and "names must be unique" in dup_name.output


def test_add_member_external_template(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _fake_hermes(tmp_path, monkeypatch)
    tpl = tmp_path / "soul.md.j2"
    tpl.write_text("你是{{ name }}（{{ role }}）\n", encoding="utf-8")
    _make_member(tmp_hermes_home, "team-pm", "pm", "P酱", "产品经理", "pm.md.j2")

    result = CliRunner().invoke(
        cli,
        [
            "add-member",
            "--prefix",
            "team",
            "--key",
            "writer",
            "--name",
            "阿写",
            "--role",
            "内容创作",
            "--template",
            str(tpl),
        ],
    )
    assert result.exit_code == 0, result.output
    writer_soul = (tmp_hermes_home / "profiles" / "team-writer" / "SOUL.md").read_text()
    assert "你是阿写（内容创作）" in writer_soul
    meta = json.loads(
        (tmp_hermes_home / "profiles" / "team-writer" / ".hermes-team.json").read_text()
    )
    assert meta["template"] == str(tpl)


def test_add_member_patches_soul_when_template_unrecoverable(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _fake_hermes(tmp_path, monkeypatch)
    # Custom member whose recorded external template no longer exists and whose
    # key has no builtin template → its hand-written SOUL must be patched, not
    # replaced.
    custom_dir = tmp_hermes_home / "profiles" / "team-custom"
    custom_dir.mkdir(parents=True)
    (custom_dir / ".hermes-team.json").write_text(
        json.dumps(
            {
                "key": "custom",
                "name": "阿甲",
                "nickname": "阿甲",
                "role": "神秘角色",
                "coordinator": False,
                "team": "T",
                "prefix": "team",
                "template": "/nonexistent/custom.md.j2",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (custom_dir / "SOUL.md").write_text(
        "这是手工写的独特人设，不能被模板覆盖。\n"
        "【飞书@方式】\n"
        '- @阿甲（神秘角色）：`<at user_id="ou_realjia">阿甲</at>`\n'
        '- @主人：`<at user_id="ou_xxx_owner">主人</at>`\n',
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "add-member",
            "--prefix",
            "team",
            "--key",
            "writer",
            "--name",
            "阿写",
            "--role",
            "内容创作",
            "--template",
            "pm",
        ],
    )
    assert result.exit_code == 0, result.output

    soul = (custom_dir / "SOUL.md").read_text()
    assert "这是手工写的独特人设" in soul  # untouched persona text
    assert 'user_id="ou_xxx_writer">阿写' in soul  # new @-line inserted
    assert 'user_id="ou_realjia">阿甲' in soul  # collected id preserved


def test_add_member_legacy_team_keeps_render_only_hub(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _fake_hermes(tmp_path, monkeypatch)
    # A v0.4-era team: no metadata; SOULs were rendered with the M总 hub.
    # (open_ids are alnum-only, like real Feishu ids.)
    for profile, name, oid in (
        ("team-pm", "P酱", "ou_realpm"),
        ("team-qa", "Q宝", "ou_realqa"),
    ):
        d = tmp_hermes_home / "profiles" / profile
        d.mkdir(parents=True)
        (d / "SOUL.md").write_text(
            "【飞书@方式】\n"
            f'- @{name}：`<at user_id="{oid}">{name}</at>`\n'
            '- @M总：`<at user_id="ou_xxx_coordinator">M总</at>`\n',
            encoding="utf-8",
        )

    result = CliRunner().invoke(
        cli,
        [
            "add-member",
            "--prefix",
            "team",
            "--key",
            "writer",
            "--name",
            "阿写",
            "--role",
            "内容创作",
            "--template",
            "pm",
        ],
    )
    assert result.exit_code == 0, result.output

    pm_soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert "M总" in pm_soul  # legacy hub preserved on rebuild
    assert "阿写" in pm_soul
    assert 'user_id="ou_realpm">P酱' in pm_soul


def test_remove_member_deletes_profile_and_updates_souls(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _fake_hermes(tmp_path, monkeypatch)
    _make_member(
        tmp_hermes_home,
        "team-pm",
        "pm",
        "P酱",
        "产品经理",
        "pm.md.j2",
        soul_at_names={"P酱": "ou_realpm", "F仔": "ou_realfe"},
    )
    _make_member(tmp_hermes_home, "team-fe", "fe", "F仔", "前端开发", "frontend.md.j2")

    result = CliRunner().invoke(
        cli,
        ["remove-member", "--prefix", "team", "--key", "fe", "--force"],
    )
    assert result.exit_code == 0, result.output

    # Profile dir gone, tombstone created (Hermes' deleted-profile semantics).
    assert not (tmp_hermes_home / "profiles" / "team-fe").exists()
    assert (tmp_hermes_home / "profiles" / ".deleted" / "team-fe").is_dir()

    # Remaining SOUL re-rendered without the departed member, ids preserved.
    pm_soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert "F仔" not in pm_soul
    assert 'user_id="ou_realpm">P酱' in pm_soul


def test_remove_member_keep_profile(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _fake_hermes(tmp_path, monkeypatch)
    _make_member(tmp_hermes_home, "team-pm", "pm", "P酱", "产品经理", "pm.md.j2")
    _make_member(tmp_hermes_home, "team-fe", "fe", "F仔", "前端开发", "frontend.md.j2")

    result = CliRunner().invoke(
        cli,
        ["remove-member", "--prefix", "team", "--key", "fe", "--force", "--keep-profile"],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_hermes_home / "profiles" / "team-fe" / "SOUL.md").exists()
    pm_soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert "F仔" not in pm_soul


def test_remove_member_errors(tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _fake_hermes(tmp_path, monkeypatch)
    _make_member(tmp_hermes_home, "team-pm", "pm", "P酱", "产品经理", "pm.md.j2")
    _make_member(tmp_hermes_home, "team-qa", "qa", "Q宝", "测试QA", "qa.md.j2")

    unknown = CliRunner().invoke(
        cli,
        ["remove-member", "--prefix", "team", "--key", "nope", "--force"],
    )
    assert unknown.exit_code != 0 and "Valid keys" in unknown.output

    # Removal needs confirmation without --force.
    aborted = CliRunner().invoke(
        cli,
        ["remove-member", "--prefix", "team", "--key", "qa"],
        input="n\n",
    )
    assert aborted.exit_code != 0
    assert (tmp_hermes_home / "profiles" / "team-qa" / "SOUL.md").exists()

    # Last member cannot be removed.
    CliRunner().invoke(cli, ["remove-member", "--prefix", "team", "--key", "qa", "--force"])
    last = CliRunner().invoke(
        cli,
        ["remove-member", "--prefix", "team", "--key", "pm", "--force"],
    )
    assert last.exit_code != 0 and "destroy" in last.output


def test_member_dry_run_changes_nothing(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _fake_hermes(tmp_path, monkeypatch)
    _make_member(tmp_hermes_home, "team-pm", "pm", "P酱", "产品经理", "pm.md.j2")
    _make_member(tmp_hermes_home, "team-qa", "qa", "Q宝", "测试QA", "qa.md.j2")
    pm_soul_before = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()

    add = CliRunner().invoke(
        cli,
        [
            "add-member",
            "--prefix",
            "team",
            "--key",
            "writer",
            "--name",
            "阿写",
            "--role",
            "内容创作",
            "--template",
            "pm",
            "--dry-run",
        ],
    )
    assert add.exit_code == 0, add.output
    assert not (tmp_hermes_home / "profiles" / "team-writer").exists()
    assert (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text() == pm_soul_before

    rm = CliRunner().invoke(
        cli,
        ["remove-member", "--prefix", "team", "--key", "pm", "--dry-run"],
    )
    assert rm.exit_code == 0, rm.output
    assert (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text() == pm_soul_before


def test_metadata_team_keeps_recorded_hub_across_add_and_remove(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """init records the render-only hub in each profile's metadata: roster
    rebuilds must keep that hub in every SOUL instead of silently dropping
    it (README: members always have a 总管 to @)."""
    _fake_hermes(tmp_path, monkeypatch)
    init = CliRunner().invoke(cli, ["init", "--team-name", "T", "--prefix", "t", "--roles", "pm"])
    assert init.exit_code == 0, init.output
    pm_meta = json.loads((tmp_hermes_home / "profiles" / "t-pm" / ".hermes-team.json").read_text())
    assert pm_meta["hub"] == {"name": "M总", "nickname": "小m", "role": "总管"}

    add = CliRunner().invoke(
        cli,
        [
            "add-member",
            "--prefix",
            "t",
            "--key",
            "writer",
            "--name",
            "阿写",
            "--role",
            "内容创作",
            "--template",
            "pm",
        ],
    )
    assert add.exit_code == 0, add.output
    for profile in ("t-pm", "t-writer"):
        soul = (tmp_hermes_home / "profiles" / profile / "SOUL.md").read_text()
        assert '<at user_id="ou_xxx_coordinator">M总</at>' in soul
    # The hub propagates into the new member's metadata for future rebuilds.
    w_meta = json.loads(
        (tmp_hermes_home / "profiles" / "t-writer" / ".hermes-team.json").read_text()
    )
    assert w_meta["hub"]["name"] == "M总"

    rm = CliRunner().invoke(cli, ["remove-member", "--prefix", "t", "--key", "writer", "--force"])
    assert rm.exit_code == 0, rm.output
    soul = (tmp_hermes_home / "profiles" / "t-pm" / "SOUL.md").read_text()
    assert '<at user_id="ou_xxx_coordinator">M总</at>' in soul


def test_coordinator_fallback_team_keeps_hub_across_add_and_remove(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Same as above for a custom config's coordinator_fallback hub: the hub
    has no profile of its own, so only metadata can carry it across roster
    rebuilds."""
    _fake_hermes(tmp_path, monkeypatch)
    cfg = tmp_path / "team.json"
    cfg.write_text(
        json.dumps(
            {
                "team_name": "T",
                "prefix": "t",
                "roles": [{"key": "w", "name": "阿写", "role": "内容创作", "template": "pm"}],
                "coordinator_fallback": {"name": "老板"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    init = CliRunner().invoke(cli, ["init", "--config", str(cfg)])
    assert init.exit_code == 0, init.output

    add = CliRunner().invoke(
        cli,
        [
            "add-member",
            "--prefix",
            "t",
            "--key",
            "ops",
            "--name",
            "老运",
            "--role",
            "运维",
            "--template",
            "backend",
        ],
    )
    assert add.exit_code == 0, add.output
    for profile in ("t-w", "t-ops"):
        soul = (tmp_hermes_home / "profiles" / profile / "SOUL.md").read_text()
        assert '<at user_id="ou_xxx_coordinator">老板</at>' in soul

    rm = CliRunner().invoke(cli, ["remove-member", "--prefix", "t", "--key", "ops", "--force"])
    assert rm.exit_code == 0, rm.output
    soul = (tmp_hermes_home / "profiles" / "t-w" / "SOUL.md").read_text()
    assert '<at user_id="ou_xxx_coordinator">老板</at>' in soul


def test_remove_keep_profile_stays_out_of_roster_and_can_rejoin(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """ "--keep-profile" must persist the removal: later roster rebuilds skip
    the kept profile instead of re-rendering the departed member back into
    every SOUL, and re-adding the same key re-joins it."""
    _fake_hermes(tmp_path, monkeypatch)
    _make_member(
        tmp_hermes_home,
        "team-pm",
        "pm",
        "P酱",
        "产品经理",
        "pm.md.j2",
        soul_at_names={"P酱": "ou_realpm", "F仔": "ou_realfe"},
    )
    _make_member(tmp_hermes_home, "team-fe", "fe", "F仔", "前端开发", "frontend.md.j2")

    rm = CliRunner().invoke(
        cli, ["remove-member", "--prefix", "team", "--key", "fe", "--force", "--keep-profile"]
    )
    assert rm.exit_code == 0, rm.output
    # Removal persisted in the kept profile's metadata (rest preserved).
    fe_meta = json.loads(
        (tmp_hermes_home / "profiles" / "team-fe" / ".hermes-team.json").read_text()
    )
    assert fe_meta["removed"] is True
    assert fe_meta["name"] == "F仔"

    # A later add must not resurrect the departed member into any SOUL.
    add = CliRunner().invoke(
        cli,
        [
            "add-member",
            "--prefix",
            "team",
            "--key",
            "writer",
            "--name",
            "阿写",
            "--role",
            "内容创作",
            "--template",
            "pm",
        ],
    )
    assert add.exit_code == 0, add.output
    for profile in ("team-pm", "team-writer"):
        soul = (tmp_hermes_home / "profiles" / profile / "SOUL.md").read_text()
        assert "F仔" not in soul

    # Re-adding the same key re-joins the kept profile and clears the marker.
    readd = CliRunner().invoke(
        cli,
        [
            "add-member",
            "--prefix",
            "team",
            "--key",
            "fe",
            "--name",
            "F仔",
            "--role",
            "前端开发",
            "--template",
            "frontend",
        ],
    )
    assert readd.exit_code == 0, readd.output
    fe_meta = json.loads(
        (tmp_hermes_home / "profiles" / "team-fe" / ".hermes-team.json").read_text()
    )
    assert not fe_meta.get("removed")
    pm_soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert "F仔" in pm_soul


def test_remove_member_delete_failure_aborts_cleanly(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A failed profile deletion must not print success nor tombstone the
    profile: the data is still on disk and the team is left as it was."""
    _fake_hermes(tmp_path, monkeypatch)
    _make_member(tmp_hermes_home, "team-pm", "pm", "P酱", "产品经理", "pm.md.j2")
    _make_member(tmp_hermes_home, "team-qa", "qa", "Q宝", "测试QA", "qa.md.j2")
    soul_before = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()

    def _boom(path, *args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr("hermes_multi_agent_team.commands.member.shutil.rmtree", _boom)

    result = CliRunner().invoke(
        cli, ["remove-member", "--prefix", "team", "--key", "qa", "--force"]
    )
    assert result.exit_code != 0
    assert "Failed to delete profile directory" in result.output
    assert "Deleted profile" not in result.output
    # No tombstone, no SOUL rewrite: nothing else changed.
    assert not (tmp_hermes_home / "profiles" / ".deleted" / "team-qa").exists()
    assert (tmp_hermes_home / "profiles" / "team-qa" / "SOUL.md").exists()
    assert (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text() == soul_before


def test_add_member_dup_checks_use_stripped_values(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Padded CLI input (" PM ", "P酱 ") used to bypass the duplicate
    key/name checks and land as a duplicate in the roster."""
    _fake_hermes(tmp_path, monkeypatch)
    _make_member(tmp_hermes_home, "team-pm", "pm", "P酱", "产品经理", "pm.md.j2")

    padded_key = CliRunner().invoke(
        cli,
        [
            "add-member",
            "--prefix",
            "team",
            "--key",
            " PM ",
            "--name",
            "新人",
            "--role",
            "X",
            "--template",
            "qa",
        ],
    )
    assert padded_key.exit_code != 0 and "'PM'" in padded_key.output
    assert not (tmp_hermes_home / "profiles" / "team-PM").exists()

    padded_name = CliRunner().invoke(
        cli,
        [
            "add-member",
            "--prefix",
            "team",
            "--key",
            "new",
            "--name",
            "P酱 ",
            "--role",
            "X",
            "--template",
            "qa",
        ],
    )
    assert padded_name.exit_code != 0 and "names must be unique" in padded_name.output


def test_add_member_rejects_at_tag_breaking_name(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A name like "A<B" cannot be matched back by collect-ids' <at>-tag
    regex; "主人" is reserved for the owner line."""
    _fake_hermes(tmp_path, monkeypatch)
    _make_member(tmp_hermes_home, "team-pm", "pm", "P酱", "产品经理", "pm.md.j2")

    for bad_name, msg in (("A<B", "must not contain"), ("主人", "reserved")):
        result = CliRunner().invoke(
            cli,
            [
                "add-member",
                "--prefix",
                "team",
                "--key",
                "new",
                "--name",
                bad_name,
                "--role",
                "X",
                "--template",
                "qa",
            ],
        )
        assert result.exit_code != 0, bad_name
        assert msg in result.output


def test_add_member_render_failure_cleans_up_and_retry_succeeds(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A profile dir created by `hermes profile create` right before a render
    failure must be cleaned up — otherwise the retry trips "already exists
    but is not part of team" forever."""
    broken = tmp_path / "broken.md.j2"
    broken.write_text("{{ 1/0 }}\n", encoding="utf-8")
    # A hermes stub that really creates the profile dir, like the real CLI.
    binary = tmp_path / "bin" / "hermes"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setattr("shutil.which", lambda name: str(binary) if name == "hermes" else None)

    def _fake_run(cmd, **kwargs):
        if len(cmd) >= 4 and cmd[1:3] == ["profile", "create"]:
            (tmp_hermes_home / "profiles" / cmd[3]).mkdir(parents=True, exist_ok=True)
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", _fake_run)
    _make_member(tmp_hermes_home, "team-pm", "pm", "P酱", "产品经理", "pm.md.j2")

    fail = CliRunner().invoke(
        cli,
        [
            "add-member",
            "--prefix",
            "team",
            "--key",
            "writer",
            "--name",
            "阿写",
            "--role",
            "内容创作",
            "--template",
            str(broken),
        ],
    )
    assert fail.exit_code != 0
    assert "Failed to render SOUL" in fail.output
    assert not (tmp_hermes_home / "profiles" / "team-writer").exists()

    # Template fixed → the retry completes instead of hitting "already exists".
    broken.write_text("你是{{ name }}\n", encoding="utf-8")
    retry = CliRunner().invoke(
        cli,
        [
            "add-member",
            "--prefix",
            "team",
            "--key",
            "writer",
            "--name",
            "阿写",
            "--role",
            "内容创作",
            "--template",
            str(broken),
        ],
    )
    assert retry.exit_code == 0, retry.output
    assert (tmp_hermes_home / "profiles" / "team-writer" / "SOUL.md").exists()


def test_corrupted_metadata_does_not_duplicate_hub_with_coordinator(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """One unreadable metadata file must not flip the whole team to 'legacy'
    and inject the M总 fallback hub next to the declared coordinator."""
    _fake_hermes(tmp_path, monkeypatch)
    _make_member(
        tmp_hermes_home, "team-boss", "boss", "老板", "总管", "coordinator.md.j2", coordinator=True
    )
    # A profile whose metadata is gone (lost/corrupt) → legacy-classified.
    legacy_dir = tmp_hermes_home / "profiles" / "team-pm"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "SOUL.md").write_text(
        '【飞书@方式】\n- @P酱：`<at user_id="ou_realpm">P酱</at>`\n', encoding="utf-8"
    )

    result = CliRunner().invoke(
        cli,
        [
            "add-member",
            "--prefix",
            "team",
            "--key",
            "writer",
            "--name",
            "阿写",
            "--role",
            "内容创作",
            "--template",
            "pm",
        ],
    )
    assert result.exit_code == 0, result.output

    boss_soul = (tmp_hermes_home / "profiles" / "team-boss" / "SOUL.md").read_text()
    assert "M总" not in boss_soul  # no injected second 总管 entry
    assert "老板" in boss_soul


def test_legacy_team_add_member_preserves_team_name_in_souls(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Legacy (pre-metadata) teams never recorded their team name: their
    SOULs must be patched only — a re-render would rename the team to the
    profile prefix (README's --team-name BaGoet --prefix baoget combo). The
    new member's SOUL reuses the team name recovered from the old SOULs."""
    _fake_hermes(tmp_path, monkeypatch)
    d = tmp_hermes_home / "profiles" / "baoget-pm"
    d.mkdir(parents=True)
    (d / "SOUL.md").write_text(
        "你是BaGoet团队的产品经理。\n"
        "【飞书@方式】\n"
        '- @P酱：`<at user_id="ou_realpm">P酱</at>`\n'
        '- @M总：`<at user_id="ou_xxx_coordinator">M总</at>`\n'
        '- @主人：`<at user_id="ou_xxx_owner">主人</at>`\n',
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "add-member",
            "--prefix",
            "baoget",
            "--key",
            "writer",
            "--name",
            "阿写",
            "--role",
            "内容创作",
            "--template",
            "pm",
        ],
    )
    assert result.exit_code == 0, result.output

    soul = (d / "SOUL.md").read_text()
    assert "你是BaGoet团队的" in soul  # original persona text untouched
    assert "baoget团队" not in soul  # team not renamed to the prefix
    assert 'user_id="ou_xxx_writer">阿写' in soul  # new @-line inserted
    assert "M总" in soul  # legacy hub entry preserved

    # The NEW member's SOUL also uses the recovered team name, not the prefix.
    writer_soul = (tmp_hermes_home / "profiles" / "baoget-writer" / "SOUL.md").read_text()
    assert "你是BaGoet团队的" in writer_soul
    assert "baoget团队" not in writer_soul


def test_init_rerun_does_not_resurrect_removed_member(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Re-running init rewrites SOUL + metadata of existing profiles — it must
    not clear the "removed" marker a `remove-member --keep-profile` left."""
    _fake_hermes(tmp_path, monkeypatch)
    init = CliRunner().invoke(
        cli, ["init", "--team-name", "T", "--prefix", "t", "--roles", "pm,fe"]
    )
    assert init.exit_code == 0, init.output

    rm = CliRunner().invoke(
        cli, ["remove-member", "--prefix", "t", "--key", "fe", "--force", "--keep-profile"]
    )
    assert rm.exit_code == 0, rm.output

    rerun = CliRunner().invoke(
        cli, ["init", "--team-name", "T", "--prefix", "t", "--roles", "pm,fe"]
    )
    assert rerun.exit_code == 0, rerun.output
    assert "skipping, the removal stands" in rerun.output
    assert "1 role(s) skipped" in rerun.output

    fe_meta = json.loads((tmp_hermes_home / "profiles" / "t-fe" / ".hermes-team.json").read_text())
    assert fe_meta.get("removed") is True  # marker survived the re-run
    pm_soul = (tmp_hermes_home / "profiles" / "t-pm" / "SOUL.md").read_text()
    assert "F仔" not in pm_soul  # not re-rendered back into the roster


def test_rejoin_warns_when_clone_from_given(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """--clone-from cannot apply when re-joining a kept profile (no profile
    creation happens): the user must be told instead of silent no-op."""
    _fake_hermes(tmp_path, monkeypatch)
    _make_member(tmp_hermes_home, "team-pm", "pm", "P酱", "产品经理", "pm.md.j2")
    _make_member(tmp_hermes_home, "team-fe", "fe", "F仔", "前端开发", "frontend.md.j2")
    rm = CliRunner().invoke(
        cli, ["remove-member", "--prefix", "team", "--key", "fe", "--force", "--keep-profile"]
    )
    assert rm.exit_code == 0, rm.output

    result = CliRunner().invoke(
        cli,
        [
            "add-member",
            "--prefix",
            "team",
            "--key",
            "fe",
            "--name",
            "F仔",
            "--role",
            "前端开发",
            "--template",
            "frontend",
            "--clone-from",
            "main",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "--clone-from has no effect" in result.output


def test_remove_then_readd_clears_tombstone(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """remove-member (delete mode) tombstones the profile; re-adding the same
    key must clear the tombstone, or list_team_profiles/collect-ids keep
    hiding the freshly rebuilt profile while add-member reports success."""
    _fake_hermes(tmp_path, monkeypatch)
    _make_member(tmp_hermes_home, "team-pm", "pm", "P酱", "产品经理", "pm.md.j2")
    _make_member(tmp_hermes_home, "team-fe", "fe", "F仔", "前端开发", "frontend.md.j2")

    rm = CliRunner().invoke(cli, ["remove-member", "--prefix", "team", "--key", "fe", "--force"])
    assert rm.exit_code == 0, rm.output
    assert (tmp_hermes_home / "profiles" / ".deleted" / "team-fe").is_dir()

    add = CliRunner().invoke(
        cli,
        [
            "add-member",
            "--prefix",
            "team",
            "--key",
            "fe",
            "--name",
            "F仔",
            "--role",
            "前端开发",
            "--template",
            "frontend",
        ],
    )
    assert add.exit_code == 0, add.output
    assert "Removed stale tombstone" in add.output
    assert not (tmp_hermes_home / "profiles" / ".deleted" / "team-fe").exists()
    # The re-added profile is visible to team tooling again.
    from hermes_multi_agent_team.utils.profile import list_team_profiles

    assert "team-fe" in list_team_profiles("team")


def test_init_recreates_profile_clears_tombstone(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Same tombstone rule for init: re-initializing a deleted role must make
    the profile servable again."""
    _fake_hermes(tmp_path, monkeypatch)
    init = CliRunner().invoke(cli, ["init", "--team-name", "T", "--prefix", "t", "--roles", "pm"])
    assert init.exit_code == 0, init.output
    (tmp_hermes_home / "profiles" / ".deleted" / "t-pm").mkdir(parents=True)  # stale tombstone

    rerun = CliRunner().invoke(cli, ["init", "--team-name", "T", "--prefix", "t", "--roles", "pm"])
    assert rerun.exit_code == 0, rerun.output
    assert not (tmp_hermes_home / "profiles" / ".deleted" / "t-pm").exists()
    from hermes_multi_agent_team.utils.profile import list_team_profiles

    assert list_team_profiles("t") == ["t-pm"]


def test_harvest_skips_removed_profiles(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A kept-but-removed profile's SOUL may carry stale open_ids; the
    last-profile-wins harvest merge must not push them into every SOUL."""
    _fake_hermes(tmp_path, monkeypatch)
    _make_member(
        tmp_hermes_home,
        "team-pm",
        "pm",
        "P酱",
        "产品经理",
        "pm.md.j2",
        soul_at_names={"P酱": "ou_fresh11"},
    )
    # Sorts AFTER team-pm, so without the filter its stale id wins the merge.
    _make_member(
        tmp_hermes_home,
        "team-zz",
        "zz",
        "老Z",
        "机动",
        "pm.md.j2",
        soul_at_names={"P酱": "ou_stale99"},
    )
    zz_meta_path = tmp_hermes_home / "profiles" / "team-zz" / ".hermes-team.json"
    zz_meta = json.loads(zz_meta_path.read_text())
    zz_meta["removed"] = True
    zz_meta_path.write_text(json.dumps(zz_meta, ensure_ascii=False) + "\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "add-member",
            "--prefix",
            "team",
            "--key",
            "writer",
            "--name",
            "阿写",
            "--role",
            "内容创作",
            "--template",
            "pm",
        ],
    )
    assert result.exit_code == 0, result.output

    for profile in ("team-pm", "team-writer"):
        soul = (tmp_hermes_home / "profiles" / profile / "SOUL.md").read_text()
        assert 'user_id="ou_fresh11">P酱' in soul
        assert "ou_stale99" not in soul


def test_recorded_hub_ignored_when_coordinator_present(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A profile carrying a stale recorded hub (e.g. the team was migrated to
    a coordinator config without wiping old metadata) must not produce two
    总管 entries — the declared coordinator wins."""
    _fake_hermes(tmp_path, monkeypatch)
    _make_member(
        tmp_hermes_home, "team-boss", "boss", "老板", "总管", "coordinator.md.j2", coordinator=True
    )
    _make_member(
        tmp_hermes_home,
        "team-pm",
        "pm",
        "P酱",
        "产品经理",
        "pm.md.j2",
        soul_at_names={"P酱": "ou_realpm"},
    )
    # Stale hub field on a member profile (left over from the hub era).
    pm_meta_path = tmp_hermes_home / "profiles" / "team-pm" / ".hermes-team.json"
    pm_meta = json.loads(pm_meta_path.read_text())
    pm_meta["hub"] = {"name": "M总", "nickname": "小m", "role": "总管"}
    pm_meta_path.write_text(json.dumps(pm_meta, ensure_ascii=False) + "\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "add-member",
            "--prefix",
            "team",
            "--key",
            "writer",
            "--name",
            "阿写",
            "--role",
            "内容创作",
            "--template",
            "pm",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Ignoring the render-only hub" in result.output

    for profile in ("team-pm", "team-boss", "team-writer"):
        soul = (tmp_hermes_home / "profiles" / profile / "SOUL.md").read_text()
        assert "M总" not in soul  # stale hub dropped
        assert "老板" in soul  # declared coordinator present


def test_readd_warns_when_tombstone_cannot_be_removed(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A tombstone that cannot be deleted must not fail silently: the profile
    stays hidden from collect-ids/verify, so the user needs the warning."""
    import shutil as shutil_mod

    _fake_hermes(tmp_path, monkeypatch)
    _make_member(tmp_hermes_home, "team-pm", "pm", "P酱", "产品经理", "pm.md.j2")
    _make_member(tmp_hermes_home, "team-fe", "fe", "F仔", "前端开发", "frontend.md.j2")
    rm = CliRunner().invoke(cli, ["remove-member", "--prefix", "team", "--key", "fe", "--force"])
    assert rm.exit_code == 0, rm.output

    real_rmtree = shutil_mod.rmtree

    def _fail_tombstone(path, *args, **kwargs):
        if ".deleted" in str(path):
            raise OSError("permission denied")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr("hermes_multi_agent_team.utils.profile.shutil.rmtree", _fail_tombstone)

    result = CliRunner().invoke(
        cli,
        [
            "add-member",
            "--prefix",
            "team",
            "--key",
            "fe",
            "--name",
            "F仔",
            "--role",
            "前端开发",
            "--template",
            "frontend",
        ],
    )
    assert result.exit_code == 0, result.output  # the profile itself was rebuilt
    assert "Could not remove tombstone" in result.output
    assert "stays hidden from" in result.output
    assert (tmp_hermes_home / "profiles" / "team-fe" / "SOUL.md").exists()
    assert (tmp_hermes_home / "profiles" / ".deleted" / "team-fe").is_dir()


def test_init_rerun_with_subset_roles_keeps_on_disk_members(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The rendering roster on a re-run is the union of the selected --roles
    and the team's on-disk members: a subset re-run must not silently drop
    still-active members (or add-member members) from every rendered SOUL."""
    _fake_hermes(tmp_path, monkeypatch)
    first = CliRunner().invoke(
        cli, ["init", "--team-name", "T", "--prefix", "t", "--roles", "pm,qa"]
    )
    assert first.exit_code == 0, first.output
    add = CliRunner().invoke(
        cli,
        [
            "add-member",
            "--prefix",
            "t",
            "--key",
            "writer",
            "--name",
            "阿写",
            "--role",
            "内容创作",
            "--template",
            "pm",
        ],
    )
    assert add.exit_code == 0, add.output

    rerun = CliRunner().invoke(cli, ["init", "--team-name", "T", "--prefix", "t", "--roles", "pm"])
    assert rerun.exit_code == 0, rerun.output
    assert "Including 2 on-disk member(s)" in rerun.output

    pm_soul = (tmp_hermes_home / "profiles" / "t-pm" / "SOUL.md").read_text()
    for name in ("M总", "P酱", "Q宝", "阿写"):  # hub + selected + on-disk extras
        assert name in pm_soul, name

    # The add-member member's own SOUL is not re-rendered by init (not a
    # config role) — its content is left as add-member wrote it.
    writer_soul = (tmp_hermes_home / "profiles" / "t-writer" / "SOUL.md").read_text()
    assert "P酱" in writer_soul


def test_init_rerun_removed_coordinator_is_announced(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A coordinator removed via --keep-profile must not be advertised as
    'will be created' nor vanish silently: the header says it is skipped and
    the skip is counted."""
    _fake_hermes(tmp_path, monkeypatch)
    cfg = tmp_path / "team.json"
    cfg.write_text(
        json.dumps(
            {
                "team_name": "T",
                "prefix": "c",
                "roles": [{"key": "w", "name": "阿写", "role": "内容创作", "template": "pm"}],
                "coordinator": {"key": "boss", "name": "老板", "role": "总管"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    init = CliRunner().invoke(cli, ["init", "--config", str(cfg)])
    assert init.exit_code == 0, init.output

    rm = CliRunner().invoke(
        cli, ["remove-member", "--prefix", "c", "--key", "boss", "--force", "--keep-profile"]
    )
    assert rm.exit_code == 0, rm.output

    rerun = CliRunner().invoke(cli, ["init", "--config", str(cfg)])
    assert rerun.exit_code == 0, rerun.output
    # Header announces the skip instead of promising profile creation.
    assert "Coordinator: 老板 — profile was removed from the team" in rerun.output
    assert "Coordinator: 老板 → profile: c-boss" not in rerun.output
    # The skip is echoed per-profile and counted in the summary.
    assert "skipping, the removal stands" in rerun.output
    assert "1 role(s) skipped" in rerun.output
    # And the removed coordinator stays out of the rendered roster.
    w_soul = (tmp_hermes_home / "profiles" / "c-w" / "SOUL.md").read_text()
    assert "老板" not in w_soul


def test_init_subset_rerun_keeps_legacy_members(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Legacy (pre-metadata) profiles must join the union roster too (classified
    by profile suffix, like member.py's rebuild): a --roles subset re-run must
    not drop them from the rendered SOUL roster."""
    _fake_hermes(tmp_path, monkeypatch)
    for profile in ("baoget-pm", "baoget-qa"):
        d = tmp_hermes_home / "profiles" / profile
        d.mkdir(parents=True)
        (d / "SOUL.md").write_text(
            f"你是BaGoet团队的成员（{profile}）。\n【飞书@方式】\n", encoding="utf-8"
        )

    result = CliRunner().invoke(
        cli, ["init", "--team-name", "BaGoet", "--prefix", "baoget", "--roles", "pm"]
    )
    assert result.exit_code == 0, result.output
    assert "Including 1 on-disk member(s)" in result.output
    assert "Q宝" in result.output  # the legacy qa profile joined the roster

    pm_soul = (tmp_hermes_home / "profiles" / "baoget-pm" / "SOUL.md").read_text()
    for name in ("M总", "P酱", "Q宝"):  # hub + selected role + legacy extra
        assert name in pm_soul, name


def test_init_extras_name_conflict_errors(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """An on-disk member whose name duplicates a config role must fail the
    re-init (names must stay unique — collect-ids matches @tags by name),
    before any profile is rewritten."""
    _fake_hermes(tmp_path, monkeypatch)
    _make_member(tmp_hermes_home, "t-pm", "pm", "P酱", "产品经理", "pm.md.j2")
    _make_member(tmp_hermes_home, "t-writer", "writer", "阿写", "内容创作", "pm.md.j2")
    pm_soul_before = (tmp_hermes_home / "profiles" / "t-pm" / "SOUL.md").read_text()

    # Config adds writer2 with the SAME display name as the on-disk writer.
    cfg = tmp_path / "team.json"
    cfg.write_text(
        json.dumps(
            {
                "team_name": "T",
                "prefix": "t",
                "roles": [
                    {"key": "pm", "name": "P酱", "role": "产品经理"},
                    {"key": "writer2", "name": "阿写", "role": "内容创作", "template": "pm"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["init", "--config", str(cfg), "--roles", "pm,writer2"])
    assert result.exit_code != 0
    assert "duplicates a name" in result.output
    # Nothing was written before the conflict was reported.
    assert (tmp_hermes_home / "profiles" / "t-pm" / "SOUL.md").read_text() == pm_soul_before
    assert not (tmp_hermes_home / "profiles" / "t-writer2").exists()


def test_init_on_disk_coordinator_leads_roster(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A coordinator profile left on disk by an earlier config leads the
    roster and suppresses the config's render-only hub — mirroring
    add-member's precedence, so the two commands stop flip-flopping the
    roster between M总 and 老板."""
    _fake_hermes(tmp_path, monkeypatch)
    coord_cfg = tmp_path / "coord.json"
    coord_cfg.write_text(
        json.dumps(
            {
                "team_name": "T",
                "prefix": "t",
                "roles": [{"key": "w", "name": "阿写", "role": "内容创作", "template": "pm"}],
                "coordinator": {"key": "boss", "name": "老板", "role": "总管"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    init = CliRunner().invoke(cli, ["init", "--config", str(coord_cfg)])
    assert init.exit_code == 0, init.output

    # Switch back to the builtin team (hub M总, no coordinator) and re-init.
    rerun = CliRunner().invoke(cli, ["init", "--team-name", "T", "--prefix", "t", "--roles", "pm"])
    assert rerun.exit_code == 0, rerun.output
    assert "On-disk coordinator 老板 leads the roster" in rerun.output
    assert "overrides the config's hub 'M总'" in rerun.output

    pm_soul = (tmp_hermes_home / "profiles" / "t-pm" / "SOUL.md").read_text()
    assert "老板" in pm_soul
    assert "M总" not in pm_soul  # hub suppressed — no two 总管 entries
    assert "阿写" in pm_soul  # the old config's member stays in the roster (union)

    # add-member agrees: the coordinator member still leads, still no M总.
    add = CliRunner().invoke(
        cli,
        [
            "add-member",
            "--prefix",
            "t",
            "--key",
            "qa",
            "--name",
            "Q宝",
            "--role",
            "测试QA",
            "--template",
            "qa",
        ],
    )
    assert add.exit_code == 0, add.output
    for profile in ("t-pm", "t-qa"):
        soul = (tmp_hermes_home / "profiles" / profile / "SOUL.md").read_text()
        assert "老板" in soul
        assert "M总" not in soul
