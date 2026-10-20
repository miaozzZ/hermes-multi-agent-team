"""Tests for the new-config interactive wizard."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from hermes_multi_agent_team.cli import cli
from hermes_multi_agent_team.team_config import load_team_config


def test_wizard_builtin_team_with_coordinator(tmp_path: Path):
    out = tmp_path / "t.json"
    # prompts: team name, prefix(default), hub choice(default 1=coordinator),
    # then the coordinator role (key/name/title/nickname/template-default),
    # builtin base yes, all five included, no extra roles.
    inputs = "T\n\n\nboss\n老板\n总管\n\n\ny\n\n\n\n\n\n" + "\n"
    result = CliRunner().invoke(cli, ["new-config", str(out)], input=inputs)
    assert result.exit_code == 0, result.output

    cfg = load_team_config(out)  # the written file loads on the first try
    assert cfg.coordinator is not None and cfg.coordinator.name == "老板"
    assert cfg.coordinator.template == "coordinator.md.j2"
    assert [r.key for r in cfg.roles] == ["pm", "fe", "be", "qa", "ui"]
    # Builtin roles carry no template in the JSON (defaults apply); the
    # coordinator's template is recorded resolved (loads identically).
    raw = json.loads(out.read_text())
    assert all("template" not in r for r in raw["roles"])
    assert raw["coordinator"]["template"] in ("coordinator", "coordinator.md.j2")


def test_wizard_custom_roles_with_fallback_hub(tmp_path: Path):
    out = tmp_path / "t.json"
    inputs = "ContentTeam\ncontent\n2\n\nn\n\nwriter\n阿写\n内容创作\n\npm\n" + "\n"
    result = CliRunner().invoke(cli, ["new-config", str(out)], input=inputs)
    assert result.exit_code == 0, result.output

    cfg = load_team_config(out)
    assert cfg.coordinator is None
    assert cfg.hub is not None and cfg.hub.name == "M总"
    assert [r.key for r in cfg.roles] == ["writer"]
    assert cfg.role("writer").template == "pm.md.j2"
    raw = json.loads(out.read_text())
    assert raw["coordinator_fallback"] == {"name": "M总"}


def test_wizard_external_template_path_recorded_absolute(tmp_path: Path):
    tpl = tmp_path / "soul.md.j2"
    tpl.write_text("你是{{ name }}\n", encoding="utf-8")
    out = tmp_path / "t.json"
    inputs = (
        "\n".join(
            [
                "T",
                "",  # name, prefix
                "3",  # hub → none
                "n",  # 不从内置开始
                "",  # 添加（名单为空）
                "writer",
                "阿写",
                "内容创作",
                "",
                str(tpl),  # 模板 → 外部文件
                "",  # 不再添加
            ]
        )
        + "\n"
    )
    result = CliRunner().invoke(cli, ["new-config", str(out)], input=inputs)
    assert result.exit_code == 0, result.output

    cfg = load_team_config(out)
    assert cfg.role("writer").template_path == tpl.resolve()
    assert cfg.hub is None and cfg.coordinator is None


def test_wizard_invalid_inputs_reask(tmp_path: Path):
    out = tmp_path / "t.json"
    inputs = "T\n../bad\nT\n3\nn\n\nbad key!\nwriter\n阿写\n内容创作\n\npm\n" + "\n"
    result = CliRunner().invoke(cli, ["new-config", str(out)], input=inputs)
    assert result.exit_code == 0, result.output
    assert "role key 'bad key!' is invalid" in result.output
    cfg = load_team_config(out)
    assert [r.key for r in cfg.roles] == ["writer"]


def test_wizard_duplicate_name_reask(tmp_path: Path):
    out = tmp_path / "t.json"
    # A duplicate name re-asks the NAME only (immediate per-field validation),
    # so the answer stream continues directly with a new name.
    inputs = "T\n\n3\ny\n\n\n\n\n\ny\nwriter\nP酱\n阿写\n内容创作\n\npm\n" + "\n"
    result = CliRunner().invoke(cli, ["new-config", str(out)], input=inputs)
    assert result.exit_code == 0, result.output
    assert "名称 'P酱' 已存在" in result.output
    cfg = load_team_config(out)
    assert sorted(r.name for r in cfg.roles) == sorted(["P酱", "F仔", "B叔", "Q宝", "U酱", "阿写"])


def test_wizard_refuses_overwrite(tmp_path: Path):
    out = tmp_path / "t.json"
    out.write_text("{}", encoding="utf-8")
    # name, prefix, hub=none, builtin base yes, all five included, no extra
    # roles — then the overwrite confirm hits EOF and aborts.
    inputs = "T\n\n3\ny\n\n\n\n\n\nn\n"
    result = CliRunner().invoke(cli, ["new-config", str(out)], input=inputs)
    assert result.exit_code != 0
    assert out.read_text() == "{}"  # untouched


def test_wizard_overwrite_declined_keeps_original(tmp_path: Path):
    out = tmp_path / "t.json"
    out.write_text("{}", encoding="utf-8")
    inputs = "T\n\n3\ny\n\n\n\n\n\nn\nn\n"  # last n = 覆盖？否
    result = CliRunner().invoke(cli, ["new-config", str(out)], input=inputs)
    assert result.exit_code != 0
    assert "已取消" in result.output
    assert out.read_text() == "{}"  # untouched


def test_wizard_builtin_conflicting_with_coordinator_key_skipped(tmp_path: Path):
    """Coordinator key=pm + adopting the builtin pm must not reach the writer.

    The loader rejects duplicate keys, so the wizard skips the conflicting
    builtin instead of writing a file its own round-trip check would refuse.
    """
    out = tmp_path / "t.json"
    inputs = "T\n\n1\npm\n老板\n总管\n\n\ny\n\n\n\n\n\nn\n"
    result = CliRunner().invoke(cli, ["new-config", str(out)], input=inputs)
    assert result.exit_code == 0, result.output
    assert "跳过" in result.output
    cfg = load_team_config(out)
    assert cfg.coordinator is not None and cfg.coordinator.key == "pm"
    assert cfg.coordinator.template == "coordinator.md.j2"
    assert [r.key for r in cfg.roles] == ["fe", "be", "qa", "ui"]
    # The coordinator's resolved template is recorded explicitly (an omitted
    # one would reload as the coordinator default — here identical, but the
    # key=pm case must not silently fall back to pm.md.j2).
    raw = json.loads(out.read_text())
    assert raw["coordinator"]["template"] == "coordinator.md.j2"


def test_wizard_builtin_conflicting_with_coordinator_name_skipped(tmp_path: Path):
    """A builtin sharing the coordinator's NAME is skipped for the same reason."""
    out = tmp_path / "t.json"
    inputs = "T\n\n1\nboss\nP酱\n总管\n\n\ny\n\n\n\n\n\nn\n"
    result = CliRunner().invoke(cli, ["new-config", str(out)], input=inputs)
    assert result.exit_code == 0, result.output
    assert "跳过" in result.output
    cfg = load_team_config(out)
    assert cfg.coordinator is not None and cfg.coordinator.name == "P酱"
    assert [r.key for r in cfg.roles] == ["fe", "be", "qa", "ui"]
    assert "P酱" not in [r.name for r in cfg.roles]


def test_wizard_fallback_reserved_name_with_space_reasked(tmp_path: Path):
    """'主人 ' (trailing space) is the reserved owner name after stripping.

    The wizard must reject it immediately (same semantics as the loader)
    and re-ask, not write a file the round-trip check would refuse.
    """
    out = tmp_path / "t.json"
    inputs = "T\n\n2\n主人 \nM总\nn\n\nwriter\n阿写\n内容创作\n\npm\nn\n"
    result = CliRunner().invoke(cli, ["new-config", str(out)], input=inputs)
    assert result.exit_code == 0, result.output
    assert "is reserved" in result.output
    cfg = load_team_config(out)
    assert cfg.hub is not None and cfg.hub.name == "M总"
    raw = json.loads(out.read_text())
    assert raw["coordinator_fallback"] == {"name": "M总"}


def test_wizard_explicit_template_on_builtin_key_kept(tmp_path: Path):
    """key=fe + template qa must survive into the JSON and the reload.

    The template may only be omitted when it equals the key's builtin
    default — an explicit choice on a builtin key is written out.
    """
    out = tmp_path / "t.json"
    inputs = "T\n\n3\nn\n\nfe\n阿写\n内容创作\n\nqa\nn\n"
    result = CliRunner().invoke(cli, ["new-config", str(out)], input=inputs)
    assert result.exit_code == 0, result.output
    raw = json.loads(out.read_text())
    assert raw["roles"][0]["template"] == "qa.md.j2"
    cfg = load_team_config(out)
    assert cfg.role("fe").template == "qa.md.j2"


def test_wizard_directory_output_path_rejected(tmp_path: Path):
    out = tmp_path / "adir"
    out.mkdir()
    # A directory OUTPUT_PATH fails before any question is asked — input= is
    # omitted on purpose: reaching a prompt would raise Abort on EOF instead.
    result = CliRunner().invoke(cli, ["new-config", str(out)])
    assert result.exit_code == 1
    assert "是一个目录" in result.output
    # A clean ClickException (SystemExit), not an IsADirectoryError traceback.
    assert isinstance(result.exception, SystemExit)


def test_wizard_team_name_whitespace_reasked(tmp_path: Path):
    """A whitespace-only team name re-asks immediately (stripped → empty)."""
    out = tmp_path / "t.json"
    inputs = " \nT\n\n3\nn\n\nwriter\n阿写\n内容创作\n\npm\nn\n"
    result = CliRunner().invoke(cli, ["new-config", str(out)], input=inputs)
    assert result.exit_code == 0, result.output
    assert "团队名称不能为空" in result.output
    cfg = load_team_config(out)
    assert cfg.team_name == "T"


def test_wizard_mkstemp_failure_is_clean_error(tmp_path: Path, monkeypatch):
    """An unwritable target directory surfaces as a ClickException."""
    from hermes_multi_agent_team.commands import wizard

    def boom(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(wizard.tempfile, "mkstemp", boom)
    out = tmp_path / "t.json"
    inputs = "T\n\n3\nn\n\nwriter\n阿写\n内容创作\n\npm\nn\n"
    result = CliRunner().invoke(cli, ["new-config", str(out)], input=inputs)
    assert result.exit_code == 1
    assert "无法写入" in result.output
    # A clean ClickException (SystemExit), not a PermissionError traceback.
    assert isinstance(result.exception, SystemExit)
    assert not out.exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_wizard_keyboard_interrupt_cleans_temp_file(tmp_path: Path, monkeypatch):
    """Ctrl+C between temp creation and replace must not leave temp litter."""
    from hermes_multi_agent_team.commands import wizard

    def boom(path):
        raise KeyboardInterrupt

    monkeypatch.setattr(wizard, "load_team_config", boom)
    out = tmp_path / "t.json"
    out.write_text("{}", encoding="utf-8")
    inputs = "T\n\n3\nn\n\nwriter\n阿写\n内容创作\n\npm\nn\ny\n"
    try:
        CliRunner().invoke(cli, ["new-config", str(out)], input=inputs)
    except KeyboardInterrupt:
        pass  # click's CliRunner does not catch KeyboardInterrupt
    assert out.read_text() == "{}"  # target untouched
    assert not list(tmp_path.glob("*.tmp"))  # no temp litter


def test_wizard_prints_quoted_commands_for_spacey_prefix(tmp_path: Path):
    """prefix with spaces (validate_prefix allows them) is shell-quoted."""
    out = tmp_path / "t.json"
    inputs = "Content Team\n\n3\nn\n\nwriter\n阿写\n内容创作\n\npm\nn\n"
    result = CliRunner().invoke(cli, ["new-config", str(out)], input=inputs)
    assert result.exit_code == 0, result.output
    assert "configure --prefix 'Content Team'" in result.output
    assert "start --prefix 'Content Team'" in result.output
    cfg = load_team_config(out)
    assert cfg.prefix == "Content Team"


def test_wizard_symlink_output_updates_real_file(tmp_path: Path):
    """A symlinked output path updates the real file, keeping link and mode.

    os.replace would swap the link itself for a regular file (stale real
    target) and impose the temp file's mode — the wizard resolves the link
    first and preserves the existing target's mode.
    """
    real = tmp_path / "real.json"
    real.write_text("{}", encoding="utf-8")
    real.chmod(0o600)
    link = tmp_path / "link.json"
    link.symlink_to(real)
    inputs = "T\n\n3\nn\n\nwriter\n阿写\n内容创作\n\npm\nn\ny\n"
    result = CliRunner().invoke(cli, ["new-config", str(link)], input=inputs)
    assert result.exit_code == 0, result.output
    assert link.is_symlink()  # the link itself survives
    raw = json.loads(real.read_text())  # the REAL file was updated
    assert raw["team_name"] == "T"
    assert (real.stat().st_mode & 0o777) == 0o600  # mode preserved on overwrite


def test_wizard_symlink_loop_rejected(tmp_path: Path):
    """A self-referencing output symlink is a clean error, not a traceback.

    Path.resolve raises RuntimeError on a symlink loop even with
    strict=False; it must surface as a ClickException after the questions.
    """
    loop = tmp_path / "loop.json"
    loop.symlink_to(loop)
    inputs = "T\n\n3\nn\n\nwriter\n阿写\n内容创作\n\npm\nn\n"
    result = CliRunner().invoke(cli, ["new-config", str(loop)], input=inputs)
    assert result.exit_code == 1
    assert "无法解析" in result.output
    assert isinstance(result.exception, SystemExit)  # no RuntimeError traceback
    assert loop.is_symlink()  # untouched
    assert not list(tmp_path.glob("*.tmp"))  # no temp litter


def test_wizard_prompted_directory_path_rejected(tmp_path: Path):
    """A directory typed at the 保存到 prompt hits the later is_dir check."""
    adir = tmp_path / "adir"
    adir.mkdir()
    # No OUTPUT_PATH argument: the save path comes from the last prompt.
    inputs = "T\n\n3\nn\n\nwriter\n阿写\n内容创作\n\npm\nn\n" + str(adir) + "\n"
    result = CliRunner().invoke(cli, ["new-config"], input=inputs)
    assert result.exit_code == 1
    assert "是一个目录" in result.output
    assert isinstance(result.exception, SystemExit)


def test_wizard_prints_quoted_config_path(tmp_path: Path):
    """An output path containing spaces is shell-quoted in the init line."""
    out = tmp_path / "my config.json"
    inputs = "T\n\n3\nn\n\nwriter\n阿写\n内容创作\n\npm\nn\n"
    result = CliRunner().invoke(cli, ["new-config", str(out)], input=inputs)
    assert result.exit_code == 0, result.output
    assert f"hermes-team init --config '{out}'" in result.output
    assert out.is_file()


def test_wizard_overwrite_write_only_target(tmp_path: Path):
    """A write-only (0200) target is still replaceable, like write_text.

    The round-trip check must run while the temp file still has mkstemp's
    0600 — chmod'ing it to the target's 0200 first would make it unreadable
    and fail validation with a misleading "不应发生" error.
    """
    out = tmp_path / "t.json"
    out.write_text("{}", encoding="utf-8")
    out.chmod(0o200)
    inputs = "T\n\n3\nn\n\nwriter\n阿写\n内容创作\n\npm\nn\ny\n"
    result = CliRunner().invoke(cli, ["new-config", str(out)], input=inputs)
    assert result.exit_code == 0, result.output
    assert (out.stat().st_mode & 0o777) == 0o200  # mode preserved
    out.chmod(0o600)  # owner may chmod without read permission
    raw = json.loads(out.read_text(encoding="utf-8"))
    assert raw["team_name"] == "T"  # content actually replaced


def test_wizard_roundtrip_failure_leaves_target_untouched(tmp_path: Path, monkeypatch):
    """If the (should-not-happen) round-trip check fails, nothing is written.

    Validation runs on a temp file and the target is replaced only after it
    passes, so a failure must leave the original file and no temp litter.
    """
    from hermes_multi_agent_team.commands import wizard
    from hermes_multi_agent_team.team_config import TeamConfigError

    def boom(path):
        raise TeamConfigError("boom")

    monkeypatch.setattr(wizard, "load_team_config", boom)

    out = tmp_path / "t.json"
    out.write_text("{}", encoding="utf-8")
    inputs = "T\n\n3\nn\n\nwriter\n阿写\n内容创作\n\npm\nn\ny\n"
    result = CliRunner().invoke(cli, ["new-config", str(out)], input=inputs)
    assert result.exit_code == 1
    assert "不应发生" in result.output
    assert out.read_text() == "{}"  # original survives
    assert not list(tmp_path.glob("*.tmp"))  # no temp litter
