"""Tests for new-bot — standalone single-function agents."""

from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest
from click.testing import CliRunner

from hermes_multi_agent_team.cli import cli


def _fake_hermes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fake `hermes` binary + subprocess.run that mimics `profile create`.

    Like the real hermes CLI, `profile create NAME` materializes the profile
    directory with a config.yaml identity marker — the host gateway and our
    own listings only serve directories carrying one.
    """
    from hermes_multi_agent_team.utils.profile import get_profiles_dir

    binary = tmp_path / "bin" / "hermes"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setattr("shutil.which", lambda name: str(binary) if name == "hermes" else None)

    def _fake_run(cmd, **kw):
        if len(cmd) >= 4 and cmd[1:3] == ["profile", "create"]:
            profile_dir = get_profiles_dir() / cmd[3]
            profile_dir.mkdir(parents=True, exist_ok=True)
            (profile_dir / "config.yaml").write_text("# fake hermes profile\n", encoding="utf-8")
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", _fake_run)
    return binary


def test_new_bot_creates_standalone_profile(tmp_hermes_home, tmp_path, monkeypatch):
    _fake_hermes(tmp_path, monkeypatch)

    result = CliRunner().invoke(
        cli,
        ["new-bot", "sign-bot", "--description", "签到打卡机器人"],
    )
    assert result.exit_code == 0, result.output

    profile = tmp_hermes_home / "profiles" / "sign-bot"
    soul = (profile / "SOUL.md").read_text()
    assert "sign-bot" in soul  # display name defaults to the profile name
    assert "签到打卡机器人" in soul
    assert "【飞书@方式】" not in soul  # roster-free by design
    assert "不属于任何团队" in soul  # standalone wording (no team_name context)

    meta = json.loads((profile / ".hermes-team.json").read_text())
    assert meta["standalone"] is True
    assert meta["template"] == "bot.md.j2"


def test_new_bot_custom_template_and_display_name(tmp_hermes_home, tmp_path, monkeypatch):
    _fake_hermes(tmp_path, monkeypatch)
    tpl = tmp_path / "my-bot.md.j2"
    tpl.write_text("你是{{ name }}：{{ description }}\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "new-bot",
            "weather",
            "--display-name",
            "天气酱",
            "--description",
            "查天气",
            "--template",
            str(tpl),
        ],
    )
    assert result.exit_code == 0, result.output
    soul = (tmp_hermes_home / "profiles" / "weather" / "SOUL.md").read_text()
    assert "你是天气酱：查天气" in soul
    meta = json.loads((tmp_hermes_home / "profiles" / "weather" / ".hermes-team.json").read_text())
    assert meta["name"] == "天气酱"
    assert meta["standalone"] is True


def test_new_bot_rejects_bad_name_and_duplicates(tmp_hermes_home, tmp_path, monkeypatch):
    _fake_hermes(tmp_path, monkeypatch)

    bad = CliRunner().invoke(
        cli,
        ["new-bot", "bad name!"],
    )
    assert bad.exit_code != 0 and "Invalid bot name" in bad.output

    CliRunner().invoke(cli, ["new-bot", "sign-bot", "--description", "x"])
    dup = CliRunner().invoke(cli, ["new-bot", "sign-bot", "--description", "x"])
    assert dup.exit_code != 0 and "already exists" in dup.output


def test_new_bot_dry_run_creates_nothing(tmp_hermes_home, tmp_path, monkeypatch):
    _fake_hermes(tmp_path, monkeypatch)
    result = CliRunner().invoke(
        cli,
        ["new-bot", "sign-bot", "--description", "x", "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert not (tmp_hermes_home / "profiles" / "sign-bot").exists()


def test_verify_skips_open_ids_for_standalone(tmp_hermes_home, tmp_path, monkeypatch):
    _fake_hermes(tmp_path, monkeypatch)
    CliRunner().invoke(cli, ["new-bot", "sign-bot", "--description", "x"])
    (tmp_hermes_home / "profiles" / "sign-bot" / ".env").write_text(
        "FEISHU_APP_ID=cli_aaa\nFEISHU_APP_SECRET=sec\nFEISHU_GROUP_POLICY=open\n"
    )

    result = CliRunner().invoke(cli, ["verify", "--prefix", "sign-bot"])
    # Gateway/env checks may legitimately fail in the test environment; the
    # behavior under test is the open_ids check not applying to standalone
    # bots (a team profile would fail it with "no open_ids found").
    assert "standalone bot — no roster expected" in result.output
    assert "no open_ids found" not in result.output


def test_collect_ids_skips_standalone_sharing_team_prefix(tmp_hermes_home, tmp_path, monkeypatch):
    _fake_hermes(tmp_path, monkeypatch)
    # A team member and a standalone bot sharing the prefix "team".
    for profile, meta in (
        (
            "team-pm",
            {
                "key": "pm",
                "name": "P酱",
                "nickname": "小P",
                "role": "产品经理",
                "coordinator": False,
                "team": "T",
                "prefix": "team",
                "template": "pm.md.j2",
            },
        ),
    ):
        d = tmp_hermes_home / "profiles" / profile
        d.mkdir(parents=True)
        (d / ".hermes-team.json").write_text(
            json.dumps(meta, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        (d / "SOUL.md").write_text(
            '【飞书@方式】\n- @P酱：`<at user_id="ou_xxx_pm">P酱</at>`\n', encoding="utf-8"
        )
        (d / "logs").mkdir()
        (d / "logs" / "gateway.log").write_text(
            "msg sender=bot:ou_botpm name=P酱\n", encoding="utf-8"
        )
    CliRunner().invoke(cli, ["new-bot", "team-sign", "--description", "x"])

    result = CliRunner().invoke(cli, ["collect-ids", "--prefix", "team"])
    assert result.exit_code == 0, result.output
    assert "team-sign: standalone bot, skipping" in result.output
    # The team member's own @-line got filled from its own log (per-profile
    # reporting format; the standalone bot contributed nothing).
    assert "sources: sender=1" in result.output
    pm_soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_botpm">P酱' in pm_soul


def test_member_roster_ignores_standalone_sharing_prefix(tmp_hermes_home, tmp_path, monkeypatch):
    _fake_hermes(tmp_path, monkeypatch)
    pm_meta = {
        "key": "pm",
        "name": "P酱",
        "nickname": "小P",
        "role": "产品经理",
        "coordinator": False,
        "team": "T",
        "prefix": "team",
        "template": "pm.md.j2",
    }
    d = tmp_hermes_home / "profiles" / "team-pm"
    d.mkdir(parents=True)
    (d / ".hermes-team.json").write_text(
        json.dumps(pm_meta, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (d / "SOUL.md").write_text(
        '【飞书@方式】\n- @P酱：`<at user_id="ou_realpm">P酱</at>`\n', encoding="utf-8"
    )
    CliRunner().invoke(cli, ["new-bot", "team-sign", "--description", "x"])

    # add-member must not treat team-sign as a legacy team member (which
    # would put a "team-sign" entry into every SOUL roster).
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
    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert "阿写" in soul
    assert "team-sign" not in soul
    assert 'user_id="ou_realpm">P酱' in soul


def test_configure_defaults_require_mention_true_for_standalone(
    tmp_hermes_home, tmp_path, monkeypatch
):
    _fake_hermes(tmp_path, monkeypatch)
    CliRunner().invoke(cli, ["new-bot", "sign-bot", "--description", "x"])

    # share settings (default): confirm + 5 setting defaults, then the app
    # credentials, then the per-profile ALLOWED_USERS default.
    result = CliRunner().invoke(
        cli,
        ["configure", "--prefix", "sign-bot"],
        input="\n" * 6 + "cli_aaa\nsec\n\n",
    )
    assert result.exit_code == 0, result.output
    env = (tmp_hermes_home / "profiles" / "sign-bot" / ".env").read_text()
    assert "FEISHU_REQUIRE_MENTION=true" in env  # flipped for standalone bots


def test_configure_mixed_prefix_gives_bot_own_mention_default(
    tmp_hermes_home, tmp_path, monkeypatch
):
    """Team + standalone bot sharing a prefix: neither inherits the other's
    Require @mention default — the shared answer defaults to the team's false,
    and each standalone bot is re-asked with its own true default."""
    _fake_hermes(tmp_path, monkeypatch)
    # A team profile without standalone metadata, plus a new-bot profile.
    pm = tmp_hermes_home / "profiles" / "mix-pm"
    pm.mkdir(parents=True)
    (pm / ".env").write_text("FEISHU_APP_ID=cli_old\nFEISHU_APP_SECRET=old\n")
    CliRunner().invoke(cli, ["new-bot", "mix-sign", "--description", "x"])

    # Sorted order: mix-pm first, mix-sign second. Shared confirm + 5 shared
    # settings (Require @mention defaults false — the team's); then per
    # profile: app id, secret, [standalone re-ask], ALLOWED_USERS.
    result = CliRunner().invoke(
        cli,
        ["configure", "--prefix", "mix"],
        input="\n" * 6 + "cli_a\nsec\n\n" + "cli_b\nsec\n\n\n",
    )
    assert result.exit_code == 0, result.output

    pm_env = (tmp_hermes_home / "profiles" / "mix-pm" / ".env").read_text()
    bot_env = (tmp_hermes_home / "profiles" / "mix-sign" / ".env").read_text()
    assert "FEISHU_REQUIRE_MENTION=false" in pm_env
    assert "FEISHU_REQUIRE_MENTION=true" in bot_env


def test_new_bot_rejects_team_templates(tmp_hermes_home, tmp_path, monkeypatch):
    """Bundled team templates need roster context a standalone bot lacks —
    they must be rejected up front, not silently rendered with empty parts."""
    _fake_hermes(tmp_path, monkeypatch)
    for template in ("pm", "coordinator", "frontend"):
        result = CliRunner().invoke(
            cli, ["new-bot", "x1", "--description", "x", "--template", template]
        )
        assert result.exit_code != 0, template
        assert "team template" in result.output
    assert not (tmp_hermes_home / "profiles" / "x1").exists()


def test_new_bot_render_failure_leaves_no_profile(tmp_hermes_home, tmp_path, monkeypatch):
    """A broken template must not leave a half-created profile that blocks a
    retry with 'already exists' (same guarantee add-member's cleanup gives)."""
    _fake_hermes(tmp_path, monkeypatch)
    bad = tmp_path / "bad.md.j2"
    bad.write_text("{{ 1/0 }}\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli, ["new-bot", "s1", "--description", "x", "--template", str(bad)]
    )
    assert result.exit_code != 0
    assert "Failed to render SOUL" in result.output
    assert not (tmp_hermes_home / "profiles" / "s1").exists()

    # Fixing the template and retrying must now succeed.
    good = tmp_path / "good.md.j2"
    good.write_text("你是{{ name }}\n", encoding="utf-8")
    retry = CliRunner().invoke(
        cli, ["new-bot", "s1", "--description", "x", "--template", str(good)]
    )
    assert retry.exit_code == 0, retry.output
    soul = (tmp_hermes_home / "profiles" / "s1" / "SOUL.md").read_text(encoding="utf-8")
    assert "你是s1" in soul


def test_new_bot_custom_template_missing_team_vars_fails_loudly(
    tmp_hermes_home, tmp_path, monkeypatch
):
    """A custom template referencing team-only variables must error instead
    of silently rendering empty interpolations into a served SOUL."""
    _fake_hermes(tmp_path, monkeypatch)
    tpl = tmp_path / "teamish.md.j2"
    tpl.write_text("{% for m in team_members %}{{ m.name }}{% endfor %}\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli, ["new-bot", "t1", "--description", "x", "--template", str(tpl)]
    )
    assert result.exit_code != 0
    assert "team_members" in result.output
    assert not (tmp_hermes_home / "profiles" / "t1").exists()


def test_new_bot_clears_stale_tombstone(tmp_hermes_home, tmp_path, monkeypatch):
    """A tombstone from an earlier deletion would keep the new profile hidden
    from listings/collect-ids/verify — new-bot removes it like init does."""
    from hermes_multi_agent_team.utils.profile import list_all_profile_names

    _fake_hermes(tmp_path, monkeypatch)
    tombstone = tmp_hermes_home / "profiles" / ".deleted" / "sign2"
    tombstone.mkdir(parents=True)

    result = CliRunner().invoke(cli, ["new-bot", "sign2", "--description", "x"])
    assert result.exit_code == 0, result.output
    assert not tombstone.exists()
    assert "sign2" in list_all_profile_names()


def test_new_bot_dry_run_does_not_prompt_for_description(tmp_hermes_home, tmp_path, monkeypatch):
    """dry-run is preview-only: a missing --description must not prompt (an
    empty stdin / non-TTY context would Abort instead of previewing)."""
    _fake_hermes(tmp_path, monkeypatch)
    result = CliRunner().invoke(cli, ["new-bot", "sign-bot", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "DRY RUN" in result.output
    assert not (tmp_hermes_home / "profiles" / "sign-bot").exists()


def test_new_bot_field_specific_errors(tmp_hermes_home, tmp_path, monkeypatch):
    """A bad --description / --display-name must be reported as such, not
    wrapped as 'Invalid template'."""
    _fake_hermes(tmp_path, monkeypatch)

    bad_desc = CliRunner().invoke(cli, ["new-bot", "d1", "--description", "<b>"])
    assert bad_desc.exit_code != 0
    assert "Invalid description" in bad_desc.output

    bad_name = CliRunner().invoke(
        cli, ["new-bot", "d2", "--display-name", "   ", "--description", "x"]
    )
    assert bad_name.exit_code != 0
    assert "Invalid display name" in bad_name.output


def test_init_ignores_standalone_sharing_prefix(tmp_hermes_home, tmp_path, monkeypatch):
    """init's on-disk member union must skip standalone bots sharing the
    prefix (they are not team members), like collect-ids/add-member do."""
    _fake_hermes(tmp_path, monkeypatch)
    r1 = CliRunner().invoke(cli, ["init", "--team-name", "T", "--prefix", "team", "--roles", "pm"])
    assert r1.exit_code == 0, r1.output
    r2 = CliRunner().invoke(cli, ["new-bot", "team-sign", "--description", "签到"])
    assert r2.exit_code == 0, r2.output

    r3 = CliRunner().invoke(
        cli, ["init", "--team-name", "T", "--prefix", "team", "--roles", "pm,qa"]
    )
    assert r3.exit_code == 0, r3.output
    assert "team-sign" not in r3.output
    for member in ("team-pm", "team-qa"):
        soul = (tmp_hermes_home / "profiles" / member / "SOUL.md").read_text(encoding="utf-8")
        assert "team-sign" not in soul
        assert "Q宝" in soul  # this run's roles still reach every roster


def test_destroy_skips_standalone_sharing_prefix(tmp_hermes_home, tmp_path, monkeypatch):
    """destroy must never delete a standalone bot sharing the team's prefix —
    not even with --force."""
    _fake_hermes(tmp_path, monkeypatch)
    CliRunner().invoke(cli, ["init", "--team-name", "T", "--prefix", "team", "--roles", "pm"])
    CliRunner().invoke(cli, ["new-bot", "team-sign", "--description", "签到"])
    bot_dir = tmp_hermes_home / "profiles" / "team-sign"
    (bot_dir / ".env").write_text("FEISHU_APP_ID=cli_a\n", encoding="utf-8")

    result = CliRunner().invoke(cli, ["destroy", "--prefix", "team", "--force"])
    assert result.exit_code == 0, result.output
    assert not (tmp_hermes_home / "profiles" / "team-pm").exists()
    assert bot_dir.is_dir()  # the standalone bot survived
    assert (bot_dir / ".env").exists()
    assert "standalone bot sharing this prefix — NOT deleted" in result.output

    # A prefix matching ONLY standalone bots refuses rather than deleting them.
    only = CliRunner().invoke(cli, ["destroy", "--prefix", "team-sign", "--force"])
    assert only.exit_code != 0
    assert "standalone" in only.output
    assert bot_dir.is_dir()


def test_add_member_key_bot_uses_bot_template(tmp_hermes_home, tmp_path, monkeypatch):
    """Team config / add-member roles may use the bundled bot template; the
    team render fills its description slot with the role text."""
    _fake_hermes(tmp_path, monkeypatch)
    r = CliRunner().invoke(cli, ["init", "--team-name", "T", "--prefix", "team", "--roles", "pm"])
    assert r.exit_code == 0, r.output

    r2 = CliRunner().invoke(
        cli,
        [
            "add-member",
            "--prefix",
            "team",
            "--key",
            "bot",
            "--name",
            "阿写",
            "--role",
            "内容创作",
        ],
    )
    assert r2.exit_code == 0, r2.output
    soul = (tmp_hermes_home / "profiles" / "team-bot" / "SOUL.md").read_text(encoding="utf-8")
    assert "你是阿写，一个内容创作。" in soul
    assert "只做一件事：内容创作。" in soul
    assert "【飞书@方式】" not in soul  # roster-free even inside a team
    assert "T团队" in soul  # identity line branches on team_name
    assert "不属于任何团队" not in soul


def test_verify_exempts_team_member_with_bot_template(tmp_hermes_home, tmp_path, monkeypatch):
    """A team member rendered from the roster-free bot template has no
    【飞书@方式】 section, so collect-ids can never fill open_ids — verify's
    open_ids check must exempt it instead of failing forever."""
    _fake_hermes(tmp_path, monkeypatch)
    r = CliRunner().invoke(cli, ["init", "--team-name", "T", "--prefix", "team", "--roles", "pm"])
    assert r.exit_code == 0, r.output
    r2 = CliRunner().invoke(
        cli,
        ["add-member", "--prefix", "team", "--key", "bot", "--name", "阿写", "--role", "内容创作"],
    )
    assert r2.exit_code == 0, r2.output

    # Complete .env everywhere so only the open_ids check could fail.
    for profile in ("team-pm", "team-bot"):
        (tmp_hermes_home / "profiles" / profile / ".env").write_text(
            "FEISHU_APP_ID=cli_x\nFEISHU_APP_SECRET=s\nFEISHU_DOMAIN=feishu\n"
            "FEISHU_CONNECTION_MODE=websocket\nFEISHU_GROUP_POLICY=open\n"
            "FEISHU_ALLOW_BOTS=all\nFEISHU_REQUIRE_MENTION=false\n",
            encoding="utf-8",
        )

    result = CliRunner().invoke(cli, ["verify", "--prefix", "team"])
    assert "no open_ids found" not in result.output
    assert "roster-free bot template — no roster expected" in result.output


def test_configure_mixed_prefix_bot_first_does_not_leak_mention_default(
    tmp_hermes_home, tmp_path, monkeypatch
):
    """A standalone bot sorting FIRST (with REQUIRE_MENTION=true already in its
    .env) must not turn the shared mention default true for team profiles."""
    _fake_hermes(tmp_path, monkeypatch)
    CliRunner().invoke(cli, ["new-bot", "mix-bot", "--description", "x"])
    (tmp_hermes_home / "profiles" / "mix-bot" / ".env").write_text(
        "FEISHU_APP_ID=cli_old\nFEISHU_APP_SECRET=old\nFEISHU_REQUIRE_MENTION=true\n",
        encoding="utf-8",
    )
    pm = tmp_hermes_home / "profiles" / "mix-pm"
    pm.mkdir(parents=True)
    (pm / ".env").write_text("FEISHU_APP_ID=cli_old2\nFEISHU_APP_SECRET=old2\n", encoding="utf-8")

    # Sorted order: mix-bot first, mix-pm second. Shared confirm + 5 shared
    # settings (Require @mention defaults false — the TEAM reference's); then
    # per profile: app id, secret, [bot re-ask], ALLOWED_USERS.
    result = CliRunner().invoke(
        cli,
        ["configure", "--prefix", "mix"],
        input="\n" * 6 + "cli_b\nsec\n\n\n" + "cli_a\nsec\n\n",
    )
    assert result.exit_code == 0, result.output

    pm_env = (tmp_hermes_home / "profiles" / "mix-pm" / ".env").read_text()
    bot_env = (tmp_hermes_home / "profiles" / "mix-bot" / ".env").read_text()
    assert "FEISHU_REQUIRE_MENTION=false" in pm_env
    assert "FEISHU_REQUIRE_MENTION=true" in bot_env


def test_new_bot_default_template_not_shadowed_by_cwd_file(tmp_hermes_home, tmp_path, monkeypatch):
    """The default template is the PACKAGED bot.md.j2 — a stray file named
    'bot' in the working directory must not shadow it. An explicit --template
    still resolves against the cwd (the user typed it)."""
    _fake_hermes(tmp_path, monkeypatch)
    workdir = tmp_path / "cwd"
    workdir.mkdir()
    (workdir / "bot").write_text("CWD-SHADOW shadow\n", encoding="utf-8")
    monkeypatch.chdir(workdir)

    result = CliRunner().invoke(cli, ["new-bot", "b1", "--description", "x"])
    assert result.exit_code == 0, result.output
    soul = (tmp_hermes_home / "profiles" / "b1" / "SOUL.md").read_text(encoding="utf-8")
    assert "CWD-SHADOW" not in soul
    assert "只做一件事" in soul  # the packaged roster-free bot template

    # Explicit --template bot DOES pick up the cwd file (documented CLI path).
    explicit = CliRunner().invoke(cli, ["new-bot", "b2", "--description", "x", "--template", "bot"])
    assert explicit.exit_code == 0, explicit.output
    soul2 = (tmp_hermes_home / "profiles" / "b2" / "SOUL.md").read_text(encoding="utf-8")
    assert "CWD-SHADOW shadow" in soul2


def test_new_bot_dry_run_surfaces_template_errors(tmp_hermes_home, tmp_path, monkeypatch):
    """dry-run must not promise a SOUL the real run cannot produce: a broken
    template fails the preview too (rendering is side-effect free)."""
    _fake_hermes(tmp_path, monkeypatch)
    bad = tmp_path / "bad.md.j2"
    bad.write_text("{{ 1/0 }}\n", encoding="utf-8")

    result = CliRunner().invoke(cli, ["new-bot", "d1", "--dry-run", "--template", str(bad)])
    assert result.exit_code != 0
    assert "Failed to render SOUL" in result.output
    assert not (tmp_hermes_home / "profiles" / "d1").exists()


def test_destroy_fails_closed_on_corrupt_bot_metadata(tmp_hermes_home, tmp_path, monkeypatch):
    """A corrupt .hermes-team.json hides the standalone marker — destroy must
    still not delete the profile (fail closed), and a corrupt-only prefix
    refuses outright."""
    _fake_hermes(tmp_path, monkeypatch)
    CliRunner().invoke(cli, ["init", "--team-name", "T", "--prefix", "team", "--roles", "pm"])
    CliRunner().invoke(cli, ["new-bot", "team-sign", "--description", "签到"])
    (tmp_hermes_home / "profiles" / "team-sign" / ".hermes-team.json").write_text(
        "{broken", encoding="utf-8"
    )
    bot_dir = tmp_hermes_home / "profiles" / "team-sign"

    result = CliRunner().invoke(cli, ["destroy", "--prefix", "team", "--force"])
    assert result.exit_code == 0, result.output
    assert not (tmp_hermes_home / "profiles" / "team-pm").exists()
    assert bot_dir.is_dir()  # fail closed: might be a standalone bot
    assert "unreadable .hermes-team.json — NOT deleted" in result.output

    # A prefix matching only the corrupt profile refuses rather than deleting.
    only = CliRunner().invoke(cli, ["destroy", "--prefix", "team-sign", "--force"])
    assert only.exit_code != 0
    assert bot_dir.is_dir()


def test_init_fails_closed_on_corrupt_metadata(tmp_hermes_home, tmp_path, monkeypatch):
    """init's on-disk union must not classify a corrupt-metadata profile as a
    legacy member (that would write a possibly-standalone bot into every
    roster) — it is skipped with a warning."""
    _fake_hermes(tmp_path, monkeypatch)
    CliRunner().invoke(cli, ["init", "--team-name", "T", "--prefix", "team", "--roles", "pm"])
    CliRunner().invoke(cli, ["new-bot", "team-sign", "--description", "签到"])
    (tmp_hermes_home / "profiles" / "team-sign" / ".hermes-team.json").write_text(
        "{broken", encoding="utf-8"
    )

    result = CliRunner().invoke(
        cli, ["init", "--team-name", "T", "--prefix", "team", "--roles", "pm,qa"]
    )
    assert result.exit_code == 0, result.output
    assert "unreadable" in result.output
    for member in ("team-pm", "team-qa"):
        soul = (tmp_hermes_home / "profiles" / member / "SOUL.md").read_text(encoding="utf-8")
        assert "- @sign" not in soul  # not classified as a legacy "sign" member
        assert "team-sign" not in soul


def test_member_roster_skips_corrupt_metadata(tmp_hermes_home, tmp_path, monkeypatch):
    """add-member's roster rebuild skips corrupt-metadata profiles instead of
    treating them as legacy members."""
    _fake_hermes(tmp_path, monkeypatch)
    r = CliRunner().invoke(cli, ["init", "--team-name", "T", "--prefix", "team", "--roles", "pm"])
    assert r.exit_code == 0, r.output
    CliRunner().invoke(cli, ["new-bot", "team-sign", "--description", "签到"])
    (tmp_hermes_home / "profiles" / "team-sign" / ".hermes-team.json").write_text(
        "{broken", encoding="utf-8"
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
    assert "unreadable" in result.output
    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text(encoding="utf-8")
    assert "阿写" in soul
    assert "- @sign" not in soul


def test_collect_ids_skips_corrupt_metadata(tmp_hermes_home, tmp_path, monkeypatch):
    """A corrupt-metadata profile must not be classified as a legacy member:
    its logs feed ITS app's open_ids into the global mapping and overwrite
    teammates' real ids (open_ids are per-app isolated)."""
    _fake_hermes(tmp_path, monkeypatch)
    # A real team member whose SOUL already carries F仔's real id.
    pm = tmp_hermes_home / "profiles" / "team-pm"
    pm.mkdir(parents=True)
    (pm / ".hermes-team.json").write_text(
        json.dumps(
            {
                "key": "pm",
                "name": "P酱",
                "nickname": "小P",
                "role": "产品经理",
                "coordinator": False,
                "team": "T",
                "prefix": "team",
                "template": "pm.md.j2",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (pm / "SOUL.md").write_text(
        '【飞书@方式】\n- @P酱：`<at user_id="ou_xxx_pm">P酱</at>`\n'
        '- @F仔：`<at user_id="ou_realfe">F仔</at>`\n',
        encoding="utf-8",
    )
    (pm / "logs").mkdir()
    (pm / "logs" / "gateway.log").write_text("msg sender=bot:ou_botpm name=P酱\n", encoding="utf-8")
    # A corrupt-metadata profile whose log would feed a WRONG F仔 id
    # (pre-fix it was classified as legacy member "F仔" by its suffix).
    fe = tmp_hermes_home / "profiles" / "team-fe"
    fe.mkdir(parents=True)
    (fe / "SOUL.md").write_text("legacy soul\n", encoding="utf-8")
    (fe / ".hermes-team.json").write_text("{broken", encoding="utf-8")
    (fe / "logs").mkdir()
    (fe / "logs" / "gateway.log").write_text(
        "msg sender=bot:ou_botfe_wrong name=F仔\n", encoding="utf-8"
    )

    result = CliRunner().invoke(cli, ["collect-ids", "--prefix", "team"])
    assert result.exit_code == 0, result.output
    assert "team-fe: unreadable .hermes-team.json — skipping" in result.output
    assert "F仔 → ou_botfe_wrong" not in result.output

    soul = (pm / "SOUL.md").read_text(encoding="utf-8")
    assert 'user_id="ou_botpm">P酱' in soul  # P酱 filled from her own log
    assert 'user_id="ou_realfe">F仔' in soul  # F仔's real id NOT overwritten


def test_configure_corrupt_profile_fails_closed(tmp_hermes_home, tmp_path, monkeypatch):
    """A corrupt-metadata profile gets the bot treatment in configure: a
    warning, standalone mention default, and never the shared-settings
    reference — even when it sorts first."""
    _fake_hermes(tmp_path, monkeypatch)
    # Corrupt profile sorting FIRST ("mix-c1" < "mix-pm"), plus a team profile.
    c1 = tmp_hermes_home / "profiles" / "mix-c1"
    c1.mkdir(parents=True)
    (c1 / ".env").write_text("FEISHU_APP_ID=cli_old\nFEISHU_APP_SECRET=old\n", encoding="utf-8")
    (c1 / ".hermes-team.json").write_text("{broken", encoding="utf-8")
    pm = tmp_hermes_home / "profiles" / "mix-pm"
    pm.mkdir(parents=True)
    (pm / ".env").write_text("FEISHU_APP_ID=cli_old2\nFEISHU_APP_SECRET=old2\n", encoding="utf-8")

    # Shared confirm + 5 shared settings (defaults from the TEAM reference →
    # mention false); then mix-c1: creds, [re-ask, default true], allowed;
    # then mix-pm: creds, allowed.
    result = CliRunner().invoke(
        cli,
        ["configure", "--prefix", "mix"],
        input="\n" * 6 + "cli_c\nsec\n\n\n" + "cli_p\nsec\n\n",
    )
    assert result.exit_code == 0, result.output
    assert "unreadable .hermes-team.json" in result.output

    pm_env = (pm / ".env").read_text()
    c1_env = (c1 / ".env").read_text()
    assert "FEISHU_REQUIRE_MENTION=false" in pm_env  # team default, no leak
    assert "FEISHU_REQUIRE_MENTION=true" in c1_env  # bot-like fail-closed default

    # An all-corrupt run flips the shared mention default, like all-bots do.
    solo = tmp_hermes_home / "profiles" / "cbot"
    solo.mkdir(parents=True)
    (solo / ".env").write_text("FEISHU_APP_ID=cli_x\nFEISHU_APP_SECRET=old\n", encoding="utf-8")
    (solo / ".hermes-team.json").write_text("{broken", encoding="utf-8")
    r2 = CliRunner().invoke(
        cli,
        ["configure", "--prefix", "cbot"],
        input="\n" * 6 + "cli_s\nsec\n\n",
    )
    assert r2.exit_code == 0, r2.output
    assert "FEISHU_REQUIRE_MENTION=true" in (solo / ".env").read_text()


def test_init_selected_role_colliding_with_standalone_bot(tmp_hermes_home, tmp_path, monkeypatch):
    """A selected role whose profile exists as a standalone bot must be
    skipped: overwriting it would erase the bot's persona + standalone marker
    (and expose it to destroy), and it must not enter teammates' rosters."""
    _fake_hermes(tmp_path, monkeypatch)
    r = CliRunner().invoke(cli, ["new-bot", "te-pm", "--description", "签到打卡"])
    assert r.exit_code == 0, r.output

    r2 = CliRunner().invoke(
        cli, ["init", "--team-name", "Te", "--prefix", "te", "--roles", "pm,fe"]
    )
    assert r2.exit_code == 0, r2.output
    assert "te-pm' exists but is a standalone bot (new-bot) — skipping" in r2.output
    assert "1 role(s) skipped" in r2.output

    # The bot's SOUL and metadata survive untouched.
    soul = (tmp_hermes_home / "profiles" / "te-pm" / "SOUL.md").read_text(encoding="utf-8")
    assert "签到打卡" in soul
    assert "P酱" not in soul
    meta = json.loads((tmp_hermes_home / "profiles" / "te-pm" / ".hermes-team.json").read_text())
    assert meta["standalone"] is True

    # The blocked role is not rendered into the created member's roster.
    fe_soul = (tmp_hermes_home / "profiles" / "te-fe" / "SOUL.md").read_text(encoding="utf-8")
    assert "P酱" not in fe_soul

    # And destroy still refuses to delete the bot with the team prefix.
    r3 = CliRunner().invoke(cli, ["destroy", "--prefix", "te", "--force"])
    assert r3.exit_code == 0, r3.output
    assert (tmp_hermes_home / "profiles" / "te-pm").is_dir()
    assert not (tmp_hermes_home / "profiles" / "te-fe").exists()


def test_init_corrupt_metadata_hiding_removed_marker(tmp_hermes_home, tmp_path, monkeypatch):
    """A removed (--keep-profile) member whose metadata later became corrupt
    must not be resurrected by a re-run: the unreadable file hides the
    'removed' marker, so the role fails closed instead of being re-rendered."""
    _fake_hermes(tmp_path, monkeypatch)
    r = CliRunner().invoke(
        cli, ["init", "--team-name", "T", "--prefix", "team", "--roles", "pm,qa"]
    )
    assert r.exit_code == 0, r.output
    rm = CliRunner().invoke(
        cli, ["remove-member", "--prefix", "team", "--key", "qa", "--force", "--keep-profile"]
    )
    assert rm.exit_code == 0, rm.output
    pm_soul_after_removal = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text(
        encoding="utf-8"
    )
    assert "Q宝" not in pm_soul_after_removal

    # Corrupt the kept profile's metadata — the 'removed' marker is hidden.
    (tmp_hermes_home / "profiles" / "team-qa" / ".hermes-team.json").write_text(
        "{broken", encoding="utf-8"
    )

    rerun = CliRunner().invoke(
        cli, ["init", "--team-name", "T", "--prefix", "team", "--roles", "pm,qa"]
    )
    assert rerun.exit_code == 0, rerun.output
    assert "unreadable" in rerun.output
    assert "1 role(s) skipped" in rerun.output

    # The member is NOT resurrected: its metadata stays corrupt (not
    # overwritten with fresh team metadata) and the roster stays without it.
    assert (tmp_hermes_home / "profiles" / "team-qa" / ".hermes-team.json").read_text(
        encoding="utf-8"
    ) == "{broken"
    pm_soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text(encoding="utf-8")
    assert "Q宝" not in pm_soul


def test_new_bot_rejects_reserved_name_default(tmp_hermes_home, tmp_path, monkeypatch):
    """'default' passes the key validation but is Hermes' reserved default
    profile (it lives in ~/.hermes itself, never under profiles/): a bot with
    that name would be invisible to every hermes-team command. Reject it,
    case-insensitively, with an explanation."""
    _fake_hermes(tmp_path, monkeypatch)

    for name in ("default", "Default", "DEFAULT"):
        result = CliRunner().invoke(cli, ["new-bot", name, "--description", "x", "--dry-run"])
        assert result.exit_code != 0, (name, result.output)
        assert "reserved" in result.output
        assert "default" in result.output

    # Nothing was created.
    assert not (tmp_hermes_home / "profiles" / "default").exists()
