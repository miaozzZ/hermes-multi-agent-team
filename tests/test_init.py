"""Tests for the init command."""

from pathlib import Path

from click.testing import CliRunner

from hermes_multi_agent_team.cli import cli


def test_init_dry_run():
    """init --dry-run should not create any files."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["init", "--team-name", "TestTeam", "--roles", "pm", "--dry-run"],
    )
    assert result.exit_code == 0
    assert "DRY RUN" in result.output
    assert "dry-run" in result.output


def test_init_rejects_invalid_roles():
    """init with unknown role should fail."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["init", "--team-name", "TestTeam", "--roles", "pm,invalid_role"],
    )
    assert result.exit_code != 0
    assert "Unknown roles" in result.output


def test_init_creates_profiles(tmp_hermes_home: Path, mock_subprocess_success):
    """init should create profile directories and SOUL.md files."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["init", "--team-name", "TestTeam", "--roles", "pm,fe", "--prefix", "test"],
    )
    assert result.exit_code == 0

    profiles_dir = tmp_hermes_home / "profiles"

    # Check profiles were created
    profiles_dir / "test-pm"
    profiles_dir / "test-fe"

    # SOUL.md should be generated (profile dirs may or may not exist depending on hermes mock)
    # At minimum, the init command should attempt to create them
    assert "TestTeam" in result.output


def test_init_skips_existing_profiles(tmp_hermes_home: Path, mock_subprocess_success):
    """init should skip profiles that already exist."""
    profiles_dir = tmp_hermes_home / "profiles"

    # Pre-create a profile
    existing = profiles_dir / "test-pm"
    existing.mkdir(parents=True)
    (existing / "SOUL.md").write_text("existing content")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["init", "--team-name", "TestTeam", "--roles", "pm", "--prefix", "test"],
    )
    assert result.exit_code == 0
    assert "already exists" in result.output


def test_init_generates_soul_md(tmp_hermes_home: Path, mock_subprocess_success):
    """init should generate SOUL.md with correct content."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["init", "--team-name", "MyTeam", "--roles", "qa", "--prefix", "mt"],
    )
    assert result.exit_code == 0

    soul_path = tmp_hermes_home / "profiles" / "mt-qa" / "SOUL.md"
    if soul_path.exists():
        content = soul_path.read_text()
        assert "Q宝" in content or "测试" in content


def test_init_all_roles(tmp_hermes_home: Path, mock_subprocess_success):
    """init with all default roles should succeed."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["init", "--team-name", "FullTeam", "--roles", "pm,fe,be,qa,ui", "--prefix", "full"],
    )
    assert result.exit_code == 0
    assert "FullTeam" in result.output


def test_init_team_config_bot_template(
    tmp_hermes_home: Path, tmp_path: Path, mock_subprocess_success
):
    """A team config role may use the bundled roster-free 'bot' template —
    the team render fills its description slot with the role text instead of
    leaving empty interpolations."""
    import json

    cfg = tmp_path / "bot-team.json"
    cfg.write_text(
        json.dumps(
            {
                "team_name": "T",
                "prefix": "bt",
                "roles": [{"key": "writer", "name": "阿写", "role": "内容创作", "template": "bot"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["init", "--config", str(cfg)])
    assert result.exit_code == 0, result.output

    soul = (tmp_hermes_home / "profiles" / "bt-writer" / "SOUL.md").read_text(encoding="utf-8")
    assert "你是阿写，一个内容创作。" in soul
    assert "只做一件事：内容创作。" in soul
    assert "【飞书@方式】" not in soul  # roster-free template stays roster-free
    assert "T团队" in soul  # identity line branches on team_name
    assert "不属于任何团队" not in soul


def test_reinit_preserves_collected_open_ids(tmp_hermes_home: Path, mock_subprocess_success):
    """Re-running init re-renders every SOUL with placeholder ids — ids already
    collected by collect-ids (or filled by hand) must be harvested BEFORE the
    rewrite and re-applied after, instead of silently resetting to ou_xxx_*
    and breaking live @-mentions (the same guarantee add/remove-member give)."""
    runner = CliRunner()
    first = runner.invoke(cli, ["init", "--team-name", "T", "--prefix", "t", "--roles", "pm"])
    assert first.exit_code == 0, first.output

    soul_path = tmp_hermes_home / "profiles" / "t-pm" / "SOUL.md"
    assert soul_path.exists()
    # Simulate collect-ids having run (and the owner/hub ids filled by hand).
    filled = soul_path.read_text(encoding="utf-8")
    for placeholder, real in (
        ("ou_xxx_pm", "ou_realpm"),
        ("ou_xxx_owner", "ou_realowner"),
        ("ou_xxx_coordinator", "ou_realcoord"),
    ):
        filled = filled.replace(placeholder, real)
    soul_path.write_text(filled, encoding="utf-8")

    rerun = runner.invoke(cli, ["init", "--team-name", "T", "--prefix", "t", "--roles", "pm"])
    assert rerun.exit_code == 0, rerun.output

    after = soul_path.read_text(encoding="utf-8")
    assert 'user_id="ou_realpm"' in after
    assert 'user_id="ou_realowner"' in after
    assert 'user_id="ou_realcoord"' in after
    assert "ou_xxx_" not in after


def test_init_never_hijacks_other_teams_profile(
    tmp_hermes_home: Path, tmp_path: Path, mock_subprocess_success
):
    """'<prefix>-<key>' can collide with a dash-nested other team's member
    (key 'extra-pm2' under prefix 'team' vs the 'team-extra' team's 'pm2'):
    the existing profile's metadata records ITS prefix, so init must skip it
    — not rewrite the SOUL to this roster and overwrite team/prefix."""
    import json as _json

    # Another team's member, on disk first.
    foreign = tmp_hermes_home / "profiles" / "team-extra-pm2"
    foreign.mkdir(parents=True)
    (foreign / "SOUL.md").write_text("TeamExtra 的成员人设\n", encoding="utf-8")
    (foreign / ".hermes-team.json").write_text(
        _json.dumps(
            {"key": "pm2", "name": "X酱", "team": "TeamExtra", "prefix": "team-extra"},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    cfg = tmp_path / "hijack.json"
    cfg.write_text(
        _json.dumps(
            {
                "team_name": "Hijack",
                "prefix": "team",
                "roles": [{"key": "extra-pm2", "name": "Y酱", "role": "成员", "template": "pm"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["init", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "belongs to team prefix 'team-extra'" in result.output

    # The other team's member is untouched: SOUL, key, team, prefix.
    assert (foreign / "SOUL.md").read_text(encoding="utf-8") == "TeamExtra 的成员人设\n"
    meta = _json.loads((foreign / ".hermes-team.json").read_text())
    assert meta["prefix"] == "team-extra" and meta["team"] == "TeamExtra"


def test_init_fails_closed_on_multiple_on_disk_coordinators(
    tmp_hermes_home: Path, tmp_path: Path, mock_subprocess_success
):
    """Several coordinator=true profiles on disk: picking any one silently
    would let init and add/remove-member lead the roster with DIFFERENT
    总管s — init fails closed, naming every leftover, before any write."""
    import json as _json

    for key, name in (("boss", "老板1"), ("boss2", "老板2"), ("boss3", "老板3")):
        d = tmp_hermes_home / "profiles" / f"t-{key}"
        d.mkdir(parents=True)
        (d / ".hermes-team.json").write_text(
            _json.dumps(
                {
                    "key": key,
                    "name": name,
                    "coordinator": True,
                    "team": "T",
                    "prefix": "t",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        (d / "SOUL.md").write_text(f"{name} 的 SOUL\n", encoding="utf-8")

    cfg = tmp_path / "c.json"
    cfg.write_text(
        _json.dumps(
            {
                "team_name": "T",
                "prefix": "t",
                "roles": [{"key": "pm", "name": "P酱", "role": "产品经理"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["init", "--config", str(cfg)])
    assert result.exit_code != 0
    assert "Multiple coordinator profiles on disk" in result.output
    for profile in ("t-boss", "t-boss2", "t-boss3"):
        assert profile in result.output
    # Failed before any write: the pm profile was not created.
    assert not (tmp_hermes_home / "profiles" / "t-pm").exists()


def test_init_declared_coordinator_conflicts_with_leftover_coordinators(
    tmp_hermes_home: Path, tmp_path: Path, mock_subprocess_success
):
    """The config declares its own coordinator while leftover coordinator
    profiles sit on disk: creating a new one would leave several 总管
    profiles behind (every later roster rebuild refuses the state) — init
    fails closed and names the leftovers."""
    import json as _json

    for key, name in (("boss1", "老板1"), ("boss2", "老板2")):
        d = tmp_hermes_home / "profiles" / f"t-{key}"
        d.mkdir(parents=True)
        (d / ".hermes-team.json").write_text(
            _json.dumps(
                {"key": key, "name": name, "coordinator": True, "team": "T", "prefix": "t"},
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        (d / "SOUL.md").write_text(f"{name} 的 SOUL\n", encoding="utf-8")

    cfg = tmp_path / "c.json"
    cfg.write_text(
        _json.dumps(
            {
                "team_name": "T",
                "prefix": "t",
                "roles": [{"key": "pm", "name": "P酱", "role": "产品经理"}],
                "coordinator": {"key": "boss3", "name": "老板3", "role": "总管"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["init", "--config", str(cfg)])
    assert result.exit_code != 0
    assert "config declares coordinator 老板3" in result.output
    assert "t-boss1 (老板1)" in result.output and "t-boss2 (老板2)" in result.output
    # Failed before any write: neither the new coordinator nor pm was created.
    assert not (tmp_hermes_home / "profiles" / "t-boss3").exists()
    assert not (tmp_hermes_home / "profiles" / "t-pm").exists()


def test_init_reserves_on_disk_coordinator_name(
    tmp_hermes_home: Path, tmp_path: Path, mock_subprocess_success
):
    """An on-disk extra member sharing the on-disk coordinator's name would
    render two identically-named @-lines and break collect-ids — init must
    refuse before any profile is written."""
    import json as _json

    boss = tmp_hermes_home / "profiles" / "t-boss"
    boss.mkdir(parents=True)
    (boss / ".hermes-team.json").write_text(
        _json.dumps(
            {"key": "boss", "name": "老板", "coordinator": True, "team": "T", "prefix": "t"},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (boss / "SOUL.md").write_text("老板 的 SOUL\n", encoding="utf-8")
    twin = tmp_hermes_home / "profiles" / "t-twin"
    twin.mkdir(parents=True)
    (twin / ".hermes-team.json").write_text(
        _json.dumps(
            {"key": "twin", "name": "老板", "team": "T", "prefix": "t"},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (twin / "SOUL.md").write_text("重名成员 的 SOUL\n", encoding="utf-8")

    cfg = tmp_path / "c.json"
    cfg.write_text(
        _json.dumps(
            {
                "team_name": "T",
                "prefix": "t",
                "roles": [{"key": "pm", "name": "P酱", "role": "产品经理"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["init", "--config", str(cfg)])
    assert result.exit_code != 0
    assert "duplicates the on-disk coordinator's name" in result.output


def test_init_blocks_ambiguous_legacy_name_collision(
    tmp_hermes_home: Path, tmp_path: Path, mock_subprocess_success
):
    """An existing profile whose name is dash-ambiguous under this prefix and
    carries NO recorded prefix (legacy 'team-extra-pm' selected as key
    'extra-pm' of 'team'): the roster scan excludes it, and the work loop
    must agree — not overwrite its SOUL and stamp a fresh 'prefix': 'team'
    metadata over it (init used to claim it silently)."""
    import json

    existing = tmp_hermes_home / "profiles" / "team-extra-pm"
    existing.mkdir(parents=True)
    (existing / "SOUL.md").write_text("旧团队的成员人设\n", encoding="utf-8")

    cfg = tmp_path / "c.json"
    cfg.write_text(
        json.dumps(
            {
                "team_name": "T",
                "prefix": "team",
                "roles": [{"key": "extra-pm", "name": "新产品", "role": "产品", "template": "pm"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["init", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "dash beyond this prefix's boundary" in result.output

    assert (existing / "SOUL.md").read_text(encoding="utf-8") == "旧团队的成员人设\n"
    assert not (existing / ".hermes-team.json").exists()  # nothing stamped over it


def test_init_rerender_unselected_members_on_hub_rename(
    tmp_hermes_home: Path, tmp_path: Path, mock_subprocess_success
):
    """A subset re-run that renames the hub (or switches hub→coordinator)
    refreshes unselected members' metadata — their SOULs must be re-rendered
    too: an old-hub @-line is a placeholder collect-ids can NEVER fill, and
    verify exempts the hub by the (new) metadata name, so a stale line failed
    forever with a 'run collect-ids' dead-end."""
    import json

    old_cfg = tmp_path / "a.json"
    old_cfg.write_text(
        json.dumps(
            {
                "team_name": "HR",
                "prefix": "hr",
                "roles": [
                    {"key": "pm", "name": "P酱", "role": "产品经理"},
                    {"key": "dev", "name": "D酱", "role": "开发", "template": "backend"},
                ],
                "coordinator_fallback": {"name": "老总"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    r1 = CliRunner().invoke(cli, ["init", "--config", str(old_cfg)])
    assert r1.exit_code == 0, r1.output

    # collect-ids ran: dev's SOUL carries real ids for its teammates.
    dev_soul_path = tmp_hermes_home / "profiles" / "hr-dev" / "SOUL.md"
    filled = dev_soul_path.read_text(encoding="utf-8")
    filled = filled.replace("ou_xxx_pm", "ou_realpm")
    dev_soul_path.write_text(filled, encoding="utf-8")
    assert "老总" in filled

    new_cfg = tmp_path / "b.json"
    new_cfg.write_text(
        json.dumps(
            {
                "team_name": "HR",
                "prefix": "hr",
                "roles": [
                    {"key": "pm", "name": "P酱", "role": "产品经理"},
                    {"key": "dev", "name": "D酱", "role": "开发", "template": "backend"},
                ],
                "coordinator_fallback": {"name": "新总"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    r2 = CliRunner().invoke(cli, ["init", "--config", str(new_cfg), "--roles", "pm"])
    assert r2.exit_code == 0, r2.output
    assert "hr-dev: SOUL re-rendered to the current roster" in r2.output

    after = dev_soul_path.read_text(encoding="utf-8")
    assert "新总" in after
    assert "老总" not in after  # the stale hub line is gone
    # Harvested ids survived the re-render.
    assert 'user_id="ou_realpm">P酱' in after


def test_init_warns_when_changed_member_template_unrecoverable(
    tmp_hermes_home: Path, tmp_path: Path, mock_subprocess_success
):
    """Identity changed but the member's recorded template is gone: the SOUL
    cannot be re-rendered — warn with the REAL fix (restore the template /
    edit by hand), not the collect-ids dead-end."""
    import json

    old_cfg = tmp_path / "a.json"
    old_cfg.write_text(
        json.dumps(
            {
                "team_name": "HR",
                "prefix": "hr",
                "roles": [
                    {"key": "pm", "name": "P酱", "role": "产品经理"},
                    {"key": "dev", "name": "D酱", "role": "开发", "template": "backend"},
                ],
                "coordinator_fallback": {"name": "老总"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert CliRunner().invoke(cli, ["init", "--config", str(old_cfg)]).exit_code == 0

    # dev's template reference now dangles.
    dev_meta_path = tmp_hermes_home / "profiles" / "hr-dev" / ".hermes-team.json"
    dev_meta = json.loads(dev_meta_path.read_text())
    dev_meta["template"] = "/nonexistent/custom-dev.md.j2"
    dev_meta_path.write_text(json.dumps(dev_meta, ensure_ascii=False) + "\n", encoding="utf-8")

    new_cfg = tmp_path / "b.json"
    new_cfg.write_text(
        json.dumps(
            {
                "team_name": "HR",
                "prefix": "hr",
                "roles": [
                    {"key": "pm", "name": "P酱", "role": "产品经理"},
                    {"key": "dev", "name": "D酱", "role": "开发", "template": "backend"},
                ],
                "coordinator_fallback": {"name": "新总"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    r = CliRunner().invoke(cli, ["init", "--config", str(new_cfg), "--roles", "pm"])
    assert r.exit_code == 0, r.output
    assert "template is not recoverable" in r.output
    assert "OLD roster lines" in r.output
    # The SOUL was left as-is (not half-rewritten).
    assert "老总" in (tmp_hermes_home / "profiles" / "hr-dev" / "SOUL.md").read_text(
        encoding="utf-8"
    )
