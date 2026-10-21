"""Tests for collect-ids: metadata-driven agent names + legacy fallback."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from hermes_multi_agent_team.cli import cli


def _make_profile(
    home: Path,
    name: str,
    *,
    metadata: dict | None,
    log_lines: list[str],
    soul_names: list[str],
) -> None:
    profile = home / "profiles" / name
    (profile / "logs").mkdir(parents=True)
    (profile / "logs" / "gateway.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    if metadata is not None:
        (profile / ".hermes-team.json").write_text(
            json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
        )
    at_lines = "\n".join(f'- @{n}：`<at user_id="ou_xxx_placeholder">{n}</at>`' for n in soul_names)
    (profile / "SOUL.md").write_text(f"【飞书@方式】\n{at_lines}\n", encoding="utf-8")


def test_collect_ids_uses_metadata_names_including_coordinator(tmp_hermes_home: Path):
    _make_profile(
        tmp_hermes_home,
        "team-writer",
        metadata={"key": "writer", "name": "阿写", "coordinator": False},
        log_lines=["2026-10-20 10:00:00 msg sender=bot:ou_botwriter name=阿写"],
        soul_names=["阿写", "老板"],
    )
    _make_profile(
        tmp_hermes_home,
        "team-boss",
        metadata={"key": "boss", "name": "老板", "coordinator": True},
        log_lines=["2026-10-20 10:00:01 msg sender=bot:ou_botboss name=老板"],
        soul_names=["阿写", "老板"],
    )

    result = CliRunner().invoke(cli, ["collect-ids", "--prefix", "team"])
    assert result.exit_code == 0, result.output
    assert "阿写 → ou_botwriter" in result.output
    assert "老板 → ou_botboss" in result.output

    # Both SOULs get BOTH ids filled (coordinator included — the old
    # hardcoded table could not do that).
    for name in ("team-writer", "team-boss"):
        soul = (tmp_hermes_home / "profiles" / name / "SOUL.md").read_text()
        assert 'user_id="ou_botwriter">阿写' in soul
        assert 'user_id="ou_botboss">老板' in soul


def test_collect_ids_legacy_fallback_without_metadata(tmp_hermes_home: Path):
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata=None,  # team created before metadata existed
        log_lines=["2026-10-20 10:00:00 msg sender=bot:ou_botpm name=P酱"],
        soul_names=["P酱"],
    )
    # Unknown suffix and no metadata → warned and skipped, not a crash.
    _make_profile(
        tmp_hermes_home,
        "team-misc",
        metadata=None,
        log_lines=["2026-10-20 10:00:02 msg sender=bot:ou_botmisc name=X"],
        soul_names=["P酱"],
    )

    result = CliRunner().invoke(cli, ["collect-ids", "--prefix", "team"])
    assert result.exit_code == 0, result.output
    assert "P酱 → ou_botpm" in result.output
    assert "could not determine agent name" in result.output
    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_botpm">P酱' in soul


def test_collect_ids_skips_profiles_removed_from_team(tmp_hermes_home: Path):
    """A profile kept via `remove-member --keep-profile` carries a "removed"
    marker: it is no longer a team member, so its logs must not feed the
    name→open_id mapping nor its SOUL be rewritten."""
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=["2026-10-20 10:00:00 msg sender=bot:ou_botpm name=P酱"],
        soul_names=["P酱", "F仔"],
    )
    _make_profile(
        tmp_hermes_home,
        "team-fe",
        metadata={"key": "fe", "name": "F仔", "coordinator": False, "removed": True},
        log_lines=["2026-10-20 10:00:01 msg sender=bot:ou_botfe name=F仔"],
        soul_names=["P酱", "F仔"],
    )

    result = CliRunner().invoke(cli, ["collect-ids", "--prefix", "team"])
    assert result.exit_code == 0, result.output
    assert "P酱 → ou_botpm" in result.output
    assert "F仔 → ou_botfe" not in result.output  # not part of the team mapping
    assert "team-fe" not in result.output  # skipped entirely (no log scan)

    pm_soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_botpm">P酱' in pm_soul
    # The removed profile's SOUL was not rewritten.
    fe_soul = (tmp_hermes_home / "profiles" / "team-fe" / "SOUL.md").read_text()
    assert 'user_id="ou_xxx_placeholder">F仔' in fe_soul


def test_collect_ids_skips_roster_free_bot_template_members(tmp_hermes_home: Path):
    """A team member rendered from the roster-free 'bot' template has no
    【飞书@方式】 section by design: it must be exempted like verify does (not
    warned at, not counted as 'could not be updated', no manual-fill tip that
    has no roster to apply to) — while its bot id still feeds teammates'
    @-lines."""
    # Normal member: roster SOUL listing both itself and the bot member.
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=["2026-10-20 10:00:00 msg sender=bot:ou_botpm name=P酱"],
        soul_names=["P酱", "阿写"],
    )
    # Roster-free bot-template member: SOUL without the 【飞书@方式】 section.
    bot = tmp_hermes_home / "profiles" / "team-writer"
    (bot / "logs").mkdir(parents=True)
    (bot / "logs" / "gateway.log").write_text(
        "2026-10-20 10:00:01 msg sender=bot:ou_botwriter name=阿写\n", encoding="utf-8"
    )
    (bot / ".hermes-team.json").write_text(
        json.dumps(
            {"key": "writer", "name": "阿写", "coordinator": False, "template": "bot.md.j2"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (bot / "SOUL.md").write_text("你是阿写，一个内容创作。\n", encoding="utf-8")

    result = CliRunner().invoke(cli, ["collect-ids", "--prefix", "team"])
    assert result.exit_code == 0, result.output

    # The bot member's id was collected and filled into the teammate's SOUL…
    assert "阿写 → ou_botwriter" in result.output
    pm_soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_botwriter">阿写' in pm_soul

    # …but its own profile was exempted, not failed.
    assert "roster-free bot template" in result.output
    assert "could not be updated" not in result.output
    assert "manually set open_ids" not in result.output
    assert "Updated 1/1 SOUL.md files" in result.output
