"""Tests for the list command — the host inventory view."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from hermes_multi_agent_team.cli import cli
from hermes_multi_agent_team.commands import listing


def _profile(home: Path, name: str, metadata: dict | None, soul: str = "x") -> None:
    d = home / "profiles" / name
    d.mkdir(parents=True)
    (d / "SOUL.md").write_text(soul, encoding="utf-8")
    if metadata is not None:
        (d / ".hermes-team.json").write_text(
            json.dumps(metadata, ensure_ascii=False) + "\n", encoding="utf-8"
        )


def test_list_groups_teams_standalone_removed(tmp_hermes_home: Path, monkeypatch):
    _profile(tmp_hermes_home, "alpha-pm", {"key": "pm", "name": "P酱", "prefix": "alpha"})
    _profile(tmp_hermes_home, "alpha-fe", {"key": "fe", "name": "F仔", "prefix": "alpha"})
    _profile(
        tmp_hermes_home,
        "beta-coord",
        {"key": "coord", "name": "M总", "prefix": "beta", "coordinator": True},
    )
    _profile(
        tmp_hermes_home,
        "sign-bot",
        {"standalone": True, "key": "sign-bot", "name": "sign-bot", "role": "签到打卡"},
    )
    _profile(
        tmp_hermes_home,
        "alpha-old",
        {"key": "old", "name": "老人", "prefix": "alpha", "removed": True},
    )

    # Two of the five profiles are gateway-visible; the header must count them.
    gateway_visible = {"alpha-pm", "sign-bot"}
    monkeypatch.setattr(
        listing,
        "gateway_status",
        lambda p: {"pid": 4321 if p in gateway_visible else None},
    )

    result = CliRunner().invoke(cli, ["list"])
    assert result.exit_code == 0, result.output
    assert "alpha" in result.output and "beta" in result.output
    assert "alpha-pm" in result.output and "beta-coord" in result.output
    assert "5 profile(s) on this host (2 gateway-visible)" in result.output
    assert "Standalone bots" in result.output and "sign-bot" in result.output
    assert "签到打卡" in result.output  # role moved to a └ subline under the row
    assert "(removed, kept)" in result.output  # kept profile stays visible
    # Removed members get their own section, grouped under their team prefix,
    # and don't count as team members.
    assert "Removed from team, kept on disk" in result.output
    assert "alpha-old (removed, kept)" in result.output
    assert "(2 profile(s))" in result.output  # alpha-pm + alpha-fe only
    # Every section renders the detail table (model column present; these
    # profiles have no config.yaml, so the model cell shows <unset>).
    assert "Model" in result.output and "<unset>" in result.output


def test_list_shows_model_and_provider(tmp_hermes_home: Path):
    _profile(tmp_hermes_home, "alpha-pm", {"key": "pm", "name": "P酱", "prefix": "alpha"})
    cfg = tmp_hermes_home / "profiles" / "alpha-pm" / "config.yaml"
    cfg.write_text(
        'model:\n  # comment line between section header and value\n'
        '  default: "glm-5.3-flash"\n\n'
        'provider: "zai"\n',
        encoding="utf-8",
    )
    _profile(tmp_hermes_home, "alpha-fe", {"key": "fe", "name": "F仔", "prefix": "alpha"})
    cfg2 = tmp_hermes_home / "profiles" / "alpha-fe" / "config.yaml"
    cfg2.write_text('model:\n  default: glm-5.3  # pinned, provider auto\n', encoding="utf-8")

    result = CliRunner().invoke(cli, ["list"])
    assert result.exit_code == 0, result.output
    assert "glm-5.3-flash (zai)" in result.output  # provider shown when pinned
    assert "glm-5.3 " in result.output  # bare model, no provider suffix for auto


def test_list_legacy_and_corrupt_metadata(tmp_hermes_home: Path):
    _profile(tmp_hermes_home, "old-pm", None)  # no metadata at all
    corrupt = tmp_hermes_home / "profiles" / "weird"
    corrupt.mkdir(parents=True)
    (corrupt / "SOUL.md").write_text("x", encoding="utf-8")
    (corrupt / ".hermes-team.json").write_text("{broken", encoding="utf-8")

    result = CliRunner().invoke(cli, ["list"])
    assert result.exit_code == 0, result.output
    assert "Legacy" in result.output and "old-pm" in result.output
    assert "Unreadable metadata" in result.output and "weird" in result.output


def test_list_empty(tmp_hermes_home: Path):
    result = CliRunner().invoke(cli, ["list"])
    assert result.exit_code == 0, result.output
    assert "No profiles" in result.output
