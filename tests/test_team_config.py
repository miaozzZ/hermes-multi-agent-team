"""Tests for the external team config (team_config.py) and init --config."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from hermes_multi_agent_team.cli import cli
from hermes_multi_agent_team.team_config import (
    TeamConfigError,
    builtin_team_config,
    load_team_config,
)


def _write_config(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


VALID_CONFIG = {
    "team_name": "CustomTeam",
    "prefix": "custom",
    "roles": [
        # Custom keys must name a template (builtin alias or a file path);
        # the persona text is what makes them custom roles.
        {"key": "writer", "name": "阿写", "nickname": "写写", "role": "内容创作", "template": "pm"},
        {"key": "ops", "name": "老运", "role": "运维", "template": "backend"},
    ],
    "coordinator": {
        "key": "boss",
        "name": "老板",
        "nickname": "板子",
        "role": "总管",
        "template": "coordinator",
    },
}


# --- load_team_config ---


def test_load_valid_config(tmp_path: Path):
    cfg_path = _write_config(tmp_path / "team.json", VALID_CONFIG)
    cfg = load_team_config(cfg_path)
    assert cfg.team_name == "CustomTeam"
    assert cfg.prefix == "custom"
    assert [r.key for r in cfg.roles] == ["writer", "ops"]
    # nickname defaults to name when omitted
    assert cfg.role("ops").nickname == "老运"
    # builtin template short name resolves to the bundled file
    assert cfg.coordinator.template == "coordinator.md.j2"
    assert cfg.coordinator.template_path is None


def test_builtin_roles_resolve_without_template():
    cfg = builtin_team_config()
    assert cfg.role("fe").template == "frontend.md.j2"
    assert cfg.coordinator is None
    # The builtin team ships the legacy render-only M总 hub entry.
    assert cfg.hub is not None
    assert cfg.hub.name == "M总"
    assert cfg.hub.as_team_member()["open_id"] == "ou_xxx_coordinator"


def test_coordinator_template_defaults_when_omitted(tmp_path: Path):
    # The coordinator's key is arbitrary, so the bundled coordinator SOUL is
    # the default rather than a key-based lookup.
    cfg_path = _write_config(
        tmp_path / "team.json",
        {
            "roles": [{"key": "pm", "name": "P酱", "role": "产品经理"}],
            "coordinator": {"key": "boss", "name": "老板", "role": "总管"},
        },
    )
    cfg = load_team_config(cfg_path)
    assert cfg.coordinator.template == "coordinator.md.j2"
    assert cfg.coordinator.template_path is None


def test_custom_key_without_template_is_rejected(tmp_path: Path):
    cfg_path = _write_config(
        tmp_path / "team.json",
        {"roles": [{"key": "writer", "name": "阿写", "role": "内容创作"}]},
    )
    with pytest.raises(TeamConfigError, match="template"):
        load_team_config(cfg_path)


def test_external_template_path_resolves_relative_to_config(tmp_path: Path):
    template = tmp_path / "souls" / "writer.md.j2"
    template.parent.mkdir()
    template.write_text("你是{{ name }}（{{ role }}）\n", encoding="utf-8")
    cfg_path = _write_config(
        tmp_path / "team.json",
        {
            "roles": [
                {
                    "key": "writer",
                    "name": "阿写",
                    "role": "内容创作",
                    "template": "souls/writer.md.j2",
                }
            ]
        },
    )
    cfg = load_team_config(cfg_path)
    assert cfg.role("writer").template_path == template.resolve()


def test_duplicate_role_names_are_rejected(tmp_path: Path):
    # collect-ids matches SOUL.md @tags by name — duplicate names are ambiguous.
    cfg_path = _write_config(
        tmp_path / "team.json",
        {
            "roles": [
                {"key": "a", "name": "同名", "role": "A", "template": "pm"},
                {"key": "b", "name": "同名", "role": "B", "template": "qa"},
            ]
        },
    )
    with pytest.raises(TeamConfigError, match="duplicate role name"):
        load_team_config(cfg_path)


def test_bad_key_chars_are_rejected(tmp_path: Path):
    cfg_path = _write_config(
        tmp_path / "team.json",
        {"roles": [{"key": "bad key!", "name": "X", "role": "Y", "template": "pm"}]},
    )
    with pytest.raises(TeamConfigError, match="invalid"):
        load_team_config(cfg_path)


def test_missing_file_and_bad_json(tmp_path: Path):
    with pytest.raises(TeamConfigError, match="not found"):
        load_team_config(tmp_path / "nope.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(TeamConfigError, match="could not read"):
        load_team_config(bad)


def test_builtin_keys_resolve_without_template(tmp_path: Path):
    # The five builtin keys (pm/fe/be/qa/ui) may omit "template" — their keys
    # differ from the template short names for fe/be/ui (frontend/backend/designer).
    cfg_path = _write_config(
        tmp_path / "team.json",
        {
            "roles": [
                {"key": "pm", "name": "P酱", "role": "产品经理"},
                {"key": "fe", "name": "F仔", "role": "前端开发"},
                {"key": "be", "name": "B叔", "role": "后端开发"},
                {"key": "qa", "name": "Q宝", "role": "测试QA"},
                {"key": "ui", "name": "U酱", "role": "UI设计"},
            ]
        },
    )
    cfg = load_team_config(cfg_path)
    assert [(r.key, r.template) for r in cfg.roles] == [
        ("pm", "pm.md.j2"),
        ("fe", "frontend.md.j2"),
        ("be", "backend.md.j2"),
        ("qa", "qa.md.j2"),
        ("ui", "designer.md.j2"),
    ]
    assert all(r.template_path is None for r in cfg.roles)


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_shipped_example_config_loads():
    # The example shipped with the repo omits "template" for all five builtin
    # keys — it must load as-is (README: "内置 5 角色不写则用默认模板").
    cfg = load_team_config(REPO_ROOT / "examples" / "baogoet-team" / "team.json")
    assert [r.key for r in cfg.roles] == ["pm", "fe", "be", "qa", "ui"]
    assert all(r.template_path is None for r in cfg.roles)
    assert cfg.coordinator.key == "coord"
    assert cfg.coordinator.template == "coordinator.md.j2"


def test_keys_differing_only_in_case_are_rejected(tmp_path: Path):
    # <prefix>-<key> profile dirs collide on case-insensitive filesystems
    # (macOS APFS default, Windows) — the second profile would silently
    # overwrite the first's SOUL.md/.hermes-team.json.
    cfg_path = _write_config(
        tmp_path / "team.json",
        {
            "roles": [
                {"key": "pm", "name": "甲", "role": "A", "template": "pm"},
                {"key": "PM", "name": "乙", "role": "B", "template": "qa"},
            ]
        },
    )
    with pytest.raises(TeamConfigError, match="case"):
        load_team_config(cfg_path)


def test_whitespace_nickname_falls_back_to_name(tmp_path: Path):
    # "nickname 缺省等于 name" — a whitespace-only nickname is no nickname.
    cfg_path = _write_config(
        tmp_path / "team.json",
        {
            "roles": [
                {
                    "key": "ops",
                    "name": "老运",
                    "nickname": "   ",
                    "role": "运维",
                    "template": "backend",
                }
            ]
        },
    )
    cfg = load_team_config(cfg_path)
    assert cfg.role("ops").nickname == "老运"


def test_coordinator_default_template_wins_over_builtin_key(tmp_path: Path):
    # The coordinator's default must win even when its key collides with a
    # builtin key/short name — "whatever its key is" (team_config docstring).
    cfg_path = _write_config(
        tmp_path / "team.json",
        {
            "roles": [{"key": "w", "name": "阿写", "role": "写", "template": "pm"}],
            "coordinator": {"key": "FE", "name": "M总", "role": "总管"},
        },
    )
    cfg = load_team_config(cfg_path)
    assert cfg.coordinator.template == "coordinator.md.j2"


def test_template_path_does_not_fall_back_to_cwd(tmp_path: Path, monkeypatch):
    # Docs promise config-relative resolution: a same-named file in the cwd
    # must not silently provide the persona.
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    (tmp_path / "onlycwd.md.j2").write_text("WRONG PERSONA", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_config(
        cfg_dir / "team.json",
        {"roles": [{"key": "w", "name": "阿写", "role": "写", "template": "onlycwd.md.j2"}]},
    )
    with pytest.raises(TeamConfigError, match="neither an existing file"):
        load_team_config(cfg_path)


def test_coordinator_fallback_name_collision_rejected(tmp_path: Path):
    # collect-ids matches @tags by name — the render-only hub entry must not
    # share a name with a member.
    cfg_path = _write_config(
        tmp_path / "team.json",
        {
            "roles": [{"key": "w", "name": "老板", "role": "写", "template": "pm"}],
            "coordinator_fallback": {"name": "老板"},
        },
    )
    with pytest.raises(TeamConfigError, match="duplicates a role name"):
        load_team_config(cfg_path)


def test_coordinator_and_fallback_are_mutually_exclusive(tmp_path: Path):
    cfg_path = _write_config(
        tmp_path / "team.json",
        {
            "roles": [{"key": "w", "name": "阿写", "role": "写", "template": "pm"}],
            "coordinator": {"key": "boss", "name": "老板", "role": "总管"},
            "coordinator_fallback": {"name": "M总"},
        },
    )
    with pytest.raises(TeamConfigError, match="not both"):
        load_team_config(cfg_path)


# --- init --config end to end ---


def _fake_hermes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A hermes binary path that exists, so init's lookup succeeds; profile
    creation itself is mocked (we test our file generation, not hermes)."""
    binary = tmp_path / "bin" / "hermes"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setattr("shutil.which", lambda name: str(binary) if name == "hermes" else None)

    from subprocess import CompletedProcess

    def _fake_run(cmd, **kwargs):
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", _fake_run)
    return binary


def test_init_with_config_creates_custom_roles_and_coordinator(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _fake_hermes(tmp_path, monkeypatch)
    cfg_path = _write_config(tmp_path / "team.json", VALID_CONFIG)

    result = CliRunner().invoke(cli, ["init", "--config", str(cfg_path)])
    assert result.exit_code == 0, result.output

    profiles = sorted(p.name for p in (tmp_hermes_home / "profiles").iterdir())
    assert profiles == ["custom-boss", "custom-ops", "custom-writer"]

    # Coordinator SOUL from the bundled template, rendered with custom names.
    boss_soul = (tmp_hermes_home / "profiles" / "custom-boss" / "SOUL.md").read_text()
    assert "老板" in boss_soul
    assert "总管" in boss_soul

    # Member SOUL carries the full team roster (coordinator first).
    writer_soul = (tmp_hermes_home / "profiles" / "custom-writer" / "SOUL.md").read_text()
    for member_name in ("老板", "阿写", "老运"):
        assert member_name in writer_soul

    # Metadata drives collect-ids' name mapping.
    meta = json.loads(
        (tmp_hermes_home / "profiles" / "custom-boss" / ".hermes-team.json").read_text()
    )
    assert meta["name"] == "老板"
    assert meta["coordinator"] is True
    assert meta["team"] == "CustomTeam"
    assert meta["prefix"] == "custom"


def test_init_with_config_external_template_renders(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _fake_hermes(tmp_path, monkeypatch)
    template = tmp_path / "souls" / "writer.md.j2"
    template.parent.mkdir()
    template.write_text(
        "你是{{ name }}，{{ role }}。队友：{{ team_members|map(attribute='name')|join('、') }}\n",
        encoding="utf-8",
    )
    cfg_path = _write_config(
        tmp_path / "team.json",
        {
            "team_name": "T",
            "roles": [
                {
                    "key": "writer",
                    "name": "阿写",
                    "role": "内容创作",
                    "template": "souls/writer.md.j2",
                }
            ],
        },
    )

    result = CliRunner().invoke(cli, ["init", "--config", str(cfg_path)])
    assert result.exit_code == 0, result.output
    # A custom config's roster is exactly its declared roles — the hardcoded
    # M总 placeholder is only kept for the builtin default team.
    soul = (tmp_hermes_home / "profiles" / "T-writer" / "SOUL.md").read_text()
    assert "你是阿写，内容创作。队友：阿写" in soul


def test_init_config_roles_subset_and_unknown_key(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _fake_hermes(tmp_path, monkeypatch)
    cfg_path = _write_config(tmp_path / "team.json", VALID_CONFIG)

    result = CliRunner().invoke(cli, ["init", "--config", str(cfg_path), "--roles", "ops"])
    assert result.exit_code == 0, result.output
    profiles = sorted(p.name for p in (tmp_hermes_home / "profiles").iterdir())
    assert profiles == ["custom-boss", "custom-ops"]

    result = CliRunner().invoke(cli, ["init", "--config", str(cfg_path), "--roles", "pm"])
    assert result.exit_code != 0
    assert "Unknown roles: pm" in result.output
    assert "Valid roles: writer, ops" in result.output


def test_init_invalid_config_fails_cleanly(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _fake_hermes(tmp_path, monkeypatch)
    cfg_path = _write_config(tmp_path / "team.json", {"roles": []})
    result = CliRunner().invoke(cli, ["init", "--config", str(cfg_path)])
    assert result.exit_code != 0
    assert "Invalid team config" in result.output
    assert not (tmp_hermes_home / "profiles").exists() or not list(
        (tmp_hermes_home / "profiles").iterdir()
    )


def test_init_without_config_keeps_builtin_behaviour(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _fake_hermes(tmp_path, monkeypatch)
    result = CliRunner().invoke(cli, ["init", "--team-name", "PlainTeam", "--roles", "pm,qa"])
    assert result.exit_code == 0, result.output
    profiles = sorted(p.name for p in (tmp_hermes_home / "profiles").iterdir())
    assert profiles == ["PlainTeam-pm", "PlainTeam-qa"]
    # No coordinator without a config declaring one (legacy behaviour).
    soul = (tmp_hermes_home / "profiles" / "PlainTeam-pm" / "SOUL.md").read_text()
    assert "P酱" in soul
    meta = json.loads(
        (tmp_hermes_home / "profiles" / "PlainTeam-pm" / ".hermes-team.json").read_text()
    )
    assert meta["name"] == "P酱"
    assert meta["coordinator"] is False


def test_init_roles_flag_matches_uppercase_key(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # _KEY_RE allows uppercase keys; --roles must accept them in the declared
    # casing (it used to .lower() everything, making such keys unselectable).
    _fake_hermes(tmp_path, monkeypatch)
    cfg_path = _write_config(
        tmp_path / "team.json",
        {
            "team_name": "T",
            "roles": [{"key": "Boss", "name": "老板", "role": "总管", "template": "pm"}],
        },
    )

    result = CliRunner().invoke(cli, ["init", "--config", str(cfg_path), "--roles", "Boss"])
    assert result.exit_code == 0, result.output
    assert (tmp_hermes_home / "profiles" / "T-Boss" / "SOUL.md").exists()


def test_builtin_key_default_template_is_case_insensitive(tmp_path: Path):
    # role() matches keys case-insensitively; the omitted-template default
    # lookup must too, or key "FE" fails where "fe" succeeds.
    cfg_path = _write_config(
        tmp_path / "team.json",
        {"roles": [{"key": "FE", "name": "F仔", "role": "前端开发"}]},
    )
    cfg = load_team_config(cfg_path)
    assert cfg.role("FE").template == "frontend.md.j2"


def test_init_custom_team_named_mzong_gets_no_placeholder(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # A custom role may legally be named M总. init must not inject the
    # hardcoded coordinator placeholder next to it: collect-ids would fill
    # BOTH @M总 tags with the role's bot id and the main profile's
    # ou_xxx_coordinator placeholder would be lost.
    _fake_hermes(tmp_path, monkeypatch)
    cfg_path = _write_config(
        tmp_path / "team.json",
        {
            "team_name": "T",
            "roles": [
                {"key": "hub", "name": "M总", "role": "总管", "template": "coordinator"},
                {"key": "w", "name": "阿写", "role": "内容创作", "template": "pm"},
            ],
        },
    )

    result = CliRunner().invoke(cli, ["init", "--config", str(cfg_path)])
    assert result.exit_code == 0, result.output
    soul = (tmp_hermes_home / "profiles" / "T-w" / "SOUL.md").read_text()
    assert '<at user_id="ou_xxx_hub">M总</at>' in soul
    assert "ou_xxx_coordinator" not in soul
    # exactly one @M总 entry, not two
    assert soul.count(">M总</at>") == 1


def test_init_custom_team_coordinator_fallback_hub_entry(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A custom config without a coordinator can declare a render-only hub
    (coordinator_fallback): bundled templates tell members to 只 @总管 汇报,
    so the roster needs a hub entry to @ — while no profile is created for
    it (the user's main profile plays the hub)."""
    _fake_hermes(tmp_path, monkeypatch)
    cfg_path = _write_config(
        tmp_path / "team.json",
        {
            "team_name": "T",
            "roles": [{"key": "w", "name": "阿写", "role": "内容创作", "template": "pm"}],
            "coordinator_fallback": {"name": "老板"},
        },
    )

    result = CliRunner().invoke(cli, ["init", "--config", str(cfg_path)])
    assert result.exit_code == 0, result.output
    assert "Hub (render-only, no profile): 老板" in result.output

    soul = (tmp_hermes_home / "profiles" / "T-w" / "SOUL.md").read_text()
    assert "- @老板（总管）" in soul
    assert '<at user_id="ou_xxx_coordinator">老板</at>' in soul
    assert "- @阿写（内容创作）" in soul
    assert '<at user_id="ou_xxx_w">阿写</at>' in soul
    # Render-only: no profile/metadata for the hub.
    assert sorted(p.name for p in (tmp_hermes_home / "profiles").iterdir()) == ["T-w"]


def test_init_custom_team_without_any_hub_warns(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Custom config with neither coordinator nor coordinator_fallback: the
    # roster gets no hub entry while bundled templates tell members to
    # @总管 — init must say so instead of staying silent.
    _fake_hermes(tmp_path, monkeypatch)
    cfg_path = _write_config(
        tmp_path / "team.json",
        {
            "team_name": "T",
            "roles": [{"key": "w", "name": "阿写", "role": "内容创作", "template": "pm"}],
        },
    )

    result = CliRunner().invoke(cli, ["init", "--config", str(cfg_path)])
    assert result.exit_code == 0, result.output
    assert "No hub declared" in result.output
    soul = (tmp_hermes_home / "profiles" / "T-w" / "SOUL.md").read_text()
    assert "ou_xxx_coordinator" not in soul


def test_init_template_runtime_error_fails_gracefully(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # An exception raised BY a custom template's code ({{ 1/0 }}) is a
    # per-role failure like any other — reported, counted, non-zero exit —
    # not an uncaught traceback.
    _fake_hermes(tmp_path, monkeypatch)
    template = tmp_path / "souls" / "broken.md.j2"
    template.parent.mkdir()
    template.write_text("{{ 1/0 }}\n", encoding="utf-8")
    cfg_path = _write_config(
        tmp_path / "team.json",
        {
            "team_name": "T",
            "roles": [
                {"key": "w", "name": "阿写", "role": "内容创作", "template": "souls/broken.md.j2"}
            ],
        },
    )

    result = CliRunner().invoke(cli, ["init", "--config", str(cfg_path)])
    assert result.exit_code != 0, result.output
    assert "Failed to render template" in result.output
    assert "partially initialized" in result.output
    assert "1 failed" in result.output
    assert not (tmp_hermes_home / "profiles" / "T-w" / "SOUL.md").exists()


def test_init_empty_roles_flag_is_an_error(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # --roles "" must not silently mean "all roles" (a script passing an empty
    # variable would create the whole team); None (option omitted) means all.
    _fake_hermes(tmp_path, monkeypatch)
    cfg_path = _write_config(tmp_path / "team.json", VALID_CONFIG)

    result = CliRunner().invoke(cli, ["init", "--config", str(cfg_path), "--roles", ""])
    assert result.exit_code != 0
    assert "--roles is empty" in result.output
    assert not list((tmp_hermes_home / "profiles").iterdir())


def test_init_default_team_keeps_coordinator_roster_entry(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Without --config the roster keeps the legacy M总 placeholder (HEAD
    behaviour): templates still tell members to @总管, but no profile is
    created for it — the user's main profile plays the coordinator."""
    _fake_hermes(tmp_path, monkeypatch)
    result = CliRunner().invoke(cli, ["init", "--team-name", "T", "--roles", "pm", "--prefix", "t"])
    assert result.exit_code == 0, result.output

    soul = (tmp_hermes_home / "profiles" / "t-pm" / "SOUL.md").read_text()
    assert '<at user_id="ou_xxx_coordinator">M总</at>' in soul
    assert '<at user_id="ou_xxx_pm">P酱</at>' in soul
    assert '<at user_id="ou_xxx_owner">主人</at>' in soul
    # Render-only placeholder: no coordinator profile directory appears.
    assert sorted(p.name for p in (tmp_hermes_home / "profiles").iterdir()) == ["t-pm"]


def test_init_non_utf8_external_template_fails_gracefully(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # A non-UTF-8 external template is a template failure like any other:
    # reported as "Failed to render template", not an uncaught
    # UnicodeDecodeError traceback.
    _fake_hermes(tmp_path, monkeypatch)
    template = tmp_path / "souls" / "gbk.md.j2"
    template.parent.mkdir()
    template.write_bytes("你是{{ name }}，GBK 编码\n".encode("gbk"))
    cfg_path = _write_config(
        tmp_path / "team.json",
        {
            "team_name": "T",
            "roles": [
                {"key": "w", "name": "阿写", "role": "内容创作", "template": "souls/gbk.md.j2"}
            ],
        },
    )

    result = CliRunner().invoke(cli, ["init", "--config", str(cfg_path)])
    # Partial failure exits non-zero (same convention as verify/doctor), so
    # scripts/CI can detect it.
    assert result.exit_code != 0, result.output
    assert "Failed to render template" in result.output
    assert "partially initialized" in result.output
    assert "1 failed" in result.output
    assert not (tmp_hermes_home / "profiles" / "T-w" / "SOUL.md").exists()


# --- regressions: unsafe names / prefixes / duplicate --roles ---


def test_config_prefix_with_path_traversal_rejected(tmp_path: Path):
    # prefix is joined into profile paths: "../escaped" would write outside
    # the profiles directory, a separator would nest beyond listing.
    for bad in ("../escaped", "a/b", "..", "a\\b"):
        cfg_path = _write_config(
            tmp_path / "team.json",
            {
                "roles": [{"key": "w", "name": "阿写", "role": "写", "template": "pm"}],
                "prefix": bad,
            },
        )
        with pytest.raises(TeamConfigError, match="prefix"):
            load_team_config(cfg_path)


def test_name_with_at_tag_breaking_chars_rejected(tmp_path: Path):
    # Names/roles are embedded verbatim in <at …>name</at> roster lines:
    # '<'/'>'/newline break collect-ids' [^<]+ matching.
    cfg_path = _write_config(
        tmp_path / "team.json",
        {"roles": [{"key": "w", "name": "A<B", "role": "写", "template": "pm"}]},
    )
    with pytest.raises(TeamConfigError, match="'name'"):
        load_team_config(cfg_path)

    cfg_path = _write_config(
        tmp_path / "team.json",
        {"roles": [{"key": "w", "name": "阿写", "role": "写\n长", "template": "pm"}]},
    )
    with pytest.raises(TeamConfigError, match="'role'"):
        load_team_config(cfg_path)

    # The render-only hub entry's name lands in the same <at> lines.
    cfg_path = _write_config(
        tmp_path / "team.json",
        {
            "roles": [{"key": "w", "name": "阿写", "role": "写", "template": "pm"}],
            "coordinator_fallback": {"name": "老板\n二号"},
        },
    )
    with pytest.raises(TeamConfigError, match="'name'"):
        load_team_config(cfg_path)


def test_owner_name_is_reserved(tmp_path: Path):
    # "主人" is the SOUL.md owner line's name: a member sharing it would get
    # the owner line's open_id rewritten by collect-ids.
    cfg_path = _write_config(
        tmp_path / "team.json",
        {"roles": [{"key": "w", "name": "主人", "role": "写", "template": "pm"}]},
    )
    with pytest.raises(TeamConfigError, match="reserved"):
        load_team_config(cfg_path)

    cfg_path = _write_config(
        tmp_path / "team.json",
        {
            "roles": [{"key": "w", "name": "阿写", "role": "写", "template": "pm"}],
            "coordinator_fallback": {"name": "主人"},
        },
    )
    with pytest.raises(TeamConfigError, match="reserved"):
        load_team_config(cfg_path)


def test_init_rejects_unsafe_prefix(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _fake_hermes(tmp_path, monkeypatch)
    result = CliRunner().invoke(cli, ["init", "--team-name", "T", "--prefix", "a/b"])
    assert result.exit_code != 0
    assert "Invalid profile prefix" in result.output
    assert not list((tmp_hermes_home / "profiles").iterdir())

    # The prefix falls back to team_name — the fallback is validated too.
    result = CliRunner().invoke(cli, ["init", "--team-name", "../escaped", "--roles", "pm"])
    assert result.exit_code != 0
    assert "Invalid profile prefix" in result.output
    assert not list((tmp_hermes_home / "profiles").iterdir())
    # Nothing escaped the profiles directory either.
    assert not (tmp_hermes_home / "escaped-pm").exists()


def test_init_roles_flag_duplicates_are_deduped(
    tmp_hermes_home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # --roles pm,pm (or case variants) used to put one RoleSpec into the
    # roster twice, rendering a duplicate @P酱 line into the SOUL.
    _fake_hermes(tmp_path, monkeypatch)
    result = CliRunner().invoke(cli, ["init", "--team-name", "T", "--roles", "pm,pm,PM"])
    assert result.exit_code == 0, result.output
    profiles = sorted(p.name for p in (tmp_hermes_home / "profiles").iterdir())
    assert profiles == ["T-pm"]
    soul = (tmp_hermes_home / "profiles" / "T-pm" / "SOUL.md").read_text()
    assert soul.count(">P酱</at>") == 1
