"""Tests for the verify command."""

from click.testing import CliRunner

from hermes_multi_agent_team.cli import cli


def test_verify_no_profiles(tmp_hermes_home):
    """verify with no matching profiles should show error."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["verify", "--prefix", "nonexistent"],
    )
    assert result.exit_code != 0
    assert "No profiles" in result.output or "not found" in result.output.lower()


def test_verify_with_empty_profile(tmp_hermes_home):
    """verify with a profile that only has an empty .env should report issues.

    (A directory with no identity marker at all is a ghost, not a profile —
    `list_team_profiles` skips it and verify would report 'No profiles'.)
    """
    profiles_dir = tmp_hermes_home / "profiles" / "test-pm"
    profiles_dir.mkdir(parents=True)
    (profiles_dir / ".env").write_text("")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["verify", "--prefix", "test"],
    )
    # Should report missing .env or SOUL.md, and exit non-zero (CI must see it).
    assert result.exit_code != 0
    assert "Some checks failed" in result.output


def test_verify_flags_duplicate_app_ids(tmp_hermes_home):
    """Two profiles sharing one Feishu App ID must be reported and fail the run."""
    for name in ("test-pm", "test-fe"):
        profile = tmp_hermes_home / "profiles" / name
        profile.mkdir(parents=True)
        (profile / ".env").write_text("FEISHU_APP_ID=cli_same\nFEISHU_APP_SECRET=sec\n")

    result = CliRunner().invoke(cli, ["verify", "--prefix", "test"])

    assert result.exit_code != 0
    assert "Duplicate Feishu App IDs" in result.output
    assert "test-fe, test-pm" in result.output
    # The affected profiles are listed in the failure summary…
    assert "Some checks failed for: test-fe, test-pm" in result.output
    # …with a fix hint pointing at configure.
    assert "Duplicate App IDs" in result.output


def test_verify_flags_allowlist_with_empty_users(tmp_hermes_home):
    """Group policy 'allowlist' with an empty allowlist must fail verification."""
    profile = tmp_hermes_home / "profiles" / "test-pm"
    profile.mkdir(parents=True)
    (profile / ".env").write_text(
        "FEISHU_APP_ID=cli_aaa\nFEISHU_APP_SECRET=sec\nFEISHU_GROUP_POLICY=allowlist\n"
    )

    result = CliRunner().invoke(cli, ["verify", "--prefix", "test"])

    assert result.exit_code != 0
    assert "rejects every group message" in result.output


def test_verify_flags_allowlist_case_insensitive(tmp_hermes_home):
    """Hermes lowercases FEISHU_GROUP_POLICY — 'Allowlist' with no users is the same trap."""
    profile = tmp_hermes_home / "profiles" / "test-pm"
    profile.mkdir(parents=True)
    (profile / ".env").write_text(
        "FEISHU_APP_ID=cli_aaa\nFEISHU_APP_SECRET=sec\nFEISHU_GROUP_POLICY=Allowlist\n"
    )

    result = CliRunner().invoke(cli, ["verify", "--prefix", "test"])

    assert result.exit_code != 0
    assert "rejects every group message" in result.output


def test_verify_flags_whitespace_only_allowed_users(tmp_hermes_home):
    """Hermes' _id_set drops blank comma entries — ' , ' is an empty allowlist."""
    profile = tmp_hermes_home / "profiles" / "test-pm"
    profile.mkdir(parents=True)
    (profile / ".env").write_text(
        "FEISHU_APP_ID=cli_aaa\nFEISHU_APP_SECRET=sec\n"
        "FEISHU_GROUP_POLICY=allowlist\nFEISHU_ALLOWED_USERS=  ,  \n"
    )

    result = CliRunner().invoke(cli, ["verify", "--prefix", "test"])

    assert result.exit_code != 0
    assert "rejects every group message" in result.output


def test_verify_accepts_populated_allowlist_case_insensitive(tmp_hermes_home):
    """A real open_id in the allowlist passes the group-policy check."""
    from hermes_multi_agent_team.commands.verify import _check_profile

    profile = tmp_hermes_home / "profiles" / "test-pm"
    profile.mkdir(parents=True)
    (profile / ".env").write_text(
        "FEISHU_APP_ID=cli_aaa\nFEISHU_APP_SECRET=sec\n"
        "FEISHU_GROUP_POLICY=Allowlist\nFEISHU_ALLOWED_USERS= ou_abc , ou_def \n"
    )

    checks = _check_profile("test-pm")

    assert checks["group_policy"] == (True, "OK")


def test_verify_exits_zero_when_all_checks_pass(tmp_hermes_home):
    """A fully healthy team passes with exit code 0.

    The connection comes from the host gateway's runtime record — the real
    multiplex path. A served profile's own log NEVER contains "feishu
    connected" (the host prints that line into its own log), so no log is
    written here on purpose.
    """
    import json
    import os

    profile = tmp_hermes_home / "profiles" / "test-pm"
    profile.mkdir(parents=True)
    (profile / ".env").write_text(
        "FEISHU_APP_ID=cli_aaa\nFEISHU_APP_SECRET=sec\n"
        "FEISHU_DOMAIN=feishu\nFEISHU_CONNECTION_MODE=websocket\n"
        "FEISHU_GROUP_POLICY=open\nFEISHU_ALLOW_BOTS=all\nFEISHU_REQUIRE_MENTION=false\n"
    )
    (profile / "SOUL.md").write_text('<at user_id="ou_real1234">P酱</at>')
    # Host multiplex gateway serves this profile (pid = this live pytest process);
    # secondary platform state is keyed "<profile>:<platform>".
    (tmp_hermes_home / "gateway_state.json").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "kind": "hermes-gateway",
                "gateway_state": "running",
                "served_profiles": ["test-pm"],
                "platforms": {"test-pm:feishu": {"state": "connected"}},
            }
        )
    )

    result = CliRunner().invoke(cli, ["verify", "--prefix", "test"])

    assert result.exit_code == 0, result.output
    assert "ALL CHECKS PASSED" in result.output
    assert "feishu connected" in result.output


def test_verify_flags_app_id_duplicating_default_profile(tmp_hermes_home):
    """A team profile sharing the default profile's App ID must fail verification.

    start's credential check rejects this (the host gateway serves ~/.hermes/.env
    too) — verify must reach the same verdict instead of ALL CHECKS PASSED.
    """
    profile = tmp_hermes_home / "profiles" / "test-pm"
    profile.mkdir(parents=True)
    (profile / ".env").write_text("FEISHU_APP_ID=cli_host\nFEISHU_APP_SECRET=sec\n")
    (tmp_hermes_home / ".env").write_text("FEISHU_APP_ID=cli_host\nFEISHU_APP_SECRET=host\n")

    result = CliRunner().invoke(cli, ["verify", "--prefix", "test"])

    assert result.exit_code != 0
    assert "Duplicate Feishu App IDs" in result.output
    assert "default profile" in result.output


def test_verify_flags_app_id_shared_across_teams(tmp_hermes_home):
    """The host gateway serves every profile under profiles/ — other teams included."""
    for name in ("test-pm", "other-pm"):
        profile = tmp_hermes_home / "profiles" / name
        profile.mkdir(parents=True)
        (profile / ".env").write_text("FEISHU_APP_ID=cli_same\nFEISHU_APP_SECRET=sec\n")

    result = CliRunner().invoke(cli, ["verify", "--prefix", "test"])

    assert result.exit_code != 0
    assert "Duplicate Feishu App IDs" in result.output
    assert "other-pm" in result.output


def test_verify_surfaces_outside_prefix_duplicate_when_team_itself_is_clean(tmp_hermes_home):
    """A duplicate only involving OTHER profiles must not print an empty failure list.

    `other-pm` shares the default profile's App ID; the `test` team itself is
    perfectly healthy. `start` would still refuse to run — verify must name the
    outside owners and point at the files that need fixing.
    """
    import json
    import os

    # A fully green team profile (same shape as the all-pass test).
    profile = tmp_hermes_home / "profiles" / "test-pm"
    profile.mkdir(parents=True)
    (profile / ".env").write_text(
        "FEISHU_APP_ID=cli_aaa\nFEISHU_APP_SECRET=sec\n"
        "FEISHU_DOMAIN=feishu\nFEISHU_CONNECTION_MODE=websocket\n"
        "FEISHU_GROUP_POLICY=open\nFEISHU_ALLOW_BOTS=all\nFEISHU_REQUIRE_MENTION=false\n"
    )
    (profile / "SOUL.md").write_text('<at user_id="ou_real1234">P酱</at>')
    (tmp_hermes_home / "gateway_state.json").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "kind": "hermes-gateway",
                "gateway_state": "running",
                "served_profiles": ["test-pm"],
                "platforms": {"test-pm:feishu": {"state": "connected"}},
            }
        )
    )
    # The clash lives entirely outside the prefix: other-pm vs the default .env.
    other = tmp_hermes_home / "profiles" / "other-pm"
    other.mkdir()
    (other / ".env").write_text("FEISHU_APP_ID=cli_host\nFEISHU_APP_SECRET=x\n")
    (tmp_hermes_home / ".env").write_text("FEISHU_APP_ID=cli_host\nFEISHU_APP_SECRET=y\n")

    result = CliRunner().invoke(cli, ["verify", "--prefix", "test"])

    assert result.exit_code != 0
    assert "Duplicate Feishu App IDs" in result.output
    # The failure summary names the outside owners instead of being empty…
    summary_line = next(
        line for line in result.output.splitlines() if "Some checks failed for:" in line
    )
    assert "other-pm (outside prefix 'test')" in summary_line
    assert "~/.hermes/.env (default profile)" in summary_line
    assert "test-pm" not in summary_line  # the team itself is clean
    # …and the fix hints point at the files configure cannot touch.
    assert "edit ~/.hermes/.env directly" in result.output
    assert "edit ~/.hermes/profiles/other-pm/.env directly" in result.output


def test_verify_reports_unreadable_env_as_check_failure(tmp_hermes_home):
    """A broken-encoding .env fails its own profile's check instead of crashing."""
    profile = tmp_hermes_home / "profiles" / "test-pm"
    profile.mkdir(parents=True)
    (profile / ".env").write_bytes(b"FEISHU_APP_ID=\xff\xfe\x00bad")

    result = CliRunner().invoke(cli, ["verify", "--prefix", "test"])

    assert result.exit_code != 0
    assert "unreadable or empty" in result.output


def test_verify_survives_unreadable_other_env(tmp_hermes_home):
    """A broken-encoding .env in an unrelated profile must not crash the scan."""
    profile = tmp_hermes_home / "profiles" / "test-pm"
    profile.mkdir(parents=True)
    (profile / ".env").write_text("FEISHU_APP_ID=cli_aaa\nFEISHU_APP_SECRET=sec\n")
    other = tmp_hermes_home / "profiles" / "other-pm"
    other.mkdir()
    (other / ".env").write_bytes(b"FEISHU_APP_ID=\xff\xfe\x00bad")

    result = CliRunner().invoke(cli, ["verify", "--prefix", "test"])

    # Unreadable file yields no app_id — it simply cannot be an owner; the run
    # completes and fails only on the team profile's own (missing) checks.
    assert "Traceback" not in result.output
    assert "Duplicate Feishu App IDs" not in result.output


def test_verify_reports_unreadable_default_env(tmp_hermes_home):
    """An unreadable ~/.hermes/.env blinds start's uniqueness scan — verify must
    fail loudly instead of ALL CHECKS PASSED."""
    import json
    import os

    profile = tmp_hermes_home / "profiles" / "test-pm"
    profile.mkdir(parents=True)
    (profile / ".env").write_text(
        "FEISHU_APP_ID=cli_aaa\nFEISHU_APP_SECRET=sec\n"
        "FEISHU_DOMAIN=feishu\nFEISHU_CONNECTION_MODE=websocket\n"
        "FEISHU_GROUP_POLICY=open\nFEISHU_ALLOW_BOTS=all\nFEISHU_REQUIRE_MENTION=false\n"
    )
    (profile / "SOUL.md").write_text('<at user_id="ou_real1234">P酱</at>')
    (tmp_hermes_home / "gateway_state.json").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "kind": "hermes-gateway",
                "gateway_state": "running",
                "served_profiles": ["test-pm"],
                "platforms": {"test-pm:feishu": {"state": "connected"}},
            }
        )
    )
    # The default .env exists but is unreadable (broken encoding).
    (tmp_hermes_home / ".env").write_bytes(b"FEISHU_APP_ID=\xff\xfe\x00bad")

    result = CliRunner().invoke(cli, ["verify", "--prefix", "test"])

    assert result.exit_code != 0
    assert "exists but is unreadable" in result.output
    assert "~/.hermes/.env (default profile)" in result.output
    assert "Traceback" not in result.output


def test_verify_accepts_readable_empty_default_env(tmp_hermes_home):
    """A readable-but-empty ~/.hermes/.env has no App ID — it hides no
    duplicate, so it must not fail verify (start only warns about it).

    Only an UNREADABLE file (permissions/encoding) blinds start's App-ID
    uniqueness scan and fails; conflating the two used to fail verify on a
    harmless 0-byte file.
    """
    import json
    import os

    profile = tmp_hermes_home / "profiles" / "test-pm"
    profile.mkdir(parents=True)
    (profile / ".env").write_text(
        "FEISHU_APP_ID=cli_aaa\nFEISHU_APP_SECRET=sec\n"
        "FEISHU_DOMAIN=feishu\nFEISHU_CONNECTION_MODE=websocket\n"
        "FEISHU_GROUP_POLICY=open\nFEISHU_ALLOW_BOTS=all\nFEISHU_REQUIRE_MENTION=false\n"
    )
    (profile / "SOUL.md").write_text('<at user_id="ou_real1234">P酱</at>')
    (tmp_hermes_home / "gateway_state.json").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "kind": "hermes-gateway",
                "gateway_state": "running",
                "served_profiles": ["test-pm"],
                "platforms": {"test-pm:feishu": {"state": "connected"}},
            }
        )
    )
    # Empty (and comments-only) default .env: readable, just no values.
    (tmp_hermes_home / ".env").write_text("# nothing configured\n")

    result = CliRunner().invoke(cli, ["verify", "--prefix", "test"])

    assert result.exit_code == 0, result.output
    assert "ALL CHECKS PASSED" in result.output


def test_verify_fails_on_remaining_placeholder_despite_real_ids(tmp_hermes_home):
    """One unfilled @-line makes that member un-@-able from this SOUL: the
    check must fail (and name the member) even when other ids are real —
    e.g. right after add-member, before collect-ids re-runs."""
    from hermes_multi_agent_team.commands.verify import _check_profile

    profile = tmp_hermes_home / "profiles" / "test-pm"
    profile.mkdir(parents=True)
    (profile / "SOUL.md").write_text(
        "【飞书@方式】\n"
        '- @P酱：`<at user_id="ou_realpm">P酱</at>`\n'
        '- @阿写：`<at user_id="ou_xxx_writer">阿写</at>`\n',
        encoding="utf-8",
    )

    checks = _check_profile("test-pm")
    assert checks["open_ids"][0] is False
    assert "placeholder open_id(s) remain" in checks["open_ids"][1]
    assert "阿写" in checks["open_ids"][1]


def test_verify_exempts_hub_and_owner_placeholders(tmp_hermes_home):
    """The render-only hub ('ou_xxx_coordinator') and the owner line
    ('ou_xxx_owner') are documented permanent placeholders — collect-ids
    never fills them (it only maps bot ids). They must not fail the check."""
    from hermes_multi_agent_team.commands.verify import _check_profile

    profile = tmp_hermes_home / "profiles" / "test-pm"
    profile.mkdir(parents=True)
    (profile / "SOUL.md").write_text(
        "【飞书@方式】\n"
        '- @M总：`<at user_id="ou_xxx_coordinator">M总</at>`\n'
        '- @P酱：`<at user_id="ou_realpm">P酱</at>`\n'
        '- @主人：`<at user_id="ou_xxx_owner">主人</at>`\n',
        encoding="utf-8",
    )

    checks = _check_profile("test-pm")
    assert checks["open_ids"] == (True, "found 1 open_id(s)")


def test_verify_fails_loudly_on_corrupt_team_metadata(tmp_hermes_home):
    """A corrupt .hermes-team.json may hide standalone/removed markers —
    every other team command fails closed on it; verify must name the cause
    instead of leaving generic downstream failures to be misread."""
    profile = tmp_hermes_home / "profiles" / "test-pm"
    profile.mkdir(parents=True)
    (profile / ".env").write_text("FEISHU_APP_ID=cli_aaa\nFEISHU_APP_SECRET=sec\n")
    (profile / "SOUL.md").write_text('<at user_id="ou_real1234">P酱</at>')
    (profile / ".hermes-team.json").write_text("{not json")

    result = CliRunner().invoke(cli, ["verify", "--prefix", "test"])

    assert result.exit_code != 0
    assert "team_metadata" in result.output
    assert "unreadable .hermes-team.json" in result.output


def test_verify_passes_metadata_check_when_absent(tmp_hermes_home):
    """Legacy teams have no .hermes-team.json at all — that is fine (only a
    file that exists but cannot be parsed is a failure)."""
    from hermes_multi_agent_team.commands.verify import _check_profile

    profile = tmp_hermes_home / "profiles" / "test-pm"
    profile.mkdir(parents=True)
    (profile / "SOUL.md").write_text('<at user_id="ou_real1234">P酱</at>')

    checks = _check_profile("test-pm")
    assert checks["team_metadata"] == (True, "OK")


def _soul_check_with(tmp_hermes_home, metadata: dict | None, soul: str):
    from hermes_multi_agent_team.commands.verify import _check_profile

    profile = tmp_hermes_home / "profiles" / "test-pm"
    profile.mkdir(parents=True, exist_ok=True)
    meta_path = profile / ".hermes-team.json"
    if metadata is None:
        meta_path.unlink(missing_ok=True)
    else:
        import json

        meta_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    (profile / "SOUL.md").write_text(soul, encoding="utf-8")
    return _check_profile("test-pm")["open_ids"]


def test_verify_placeholder_exemptions_are_by_name_not_id(tmp_hermes_home):
    """A member whose KEY is 'coordinator'/'owner' renders the placeholder id
    ou_xxx_coordinator / ou_xxx_owner (as_team_member uses ou_xxx_<key>) —
    exempting by ID would excuse a real, un-@-able member forever. The
    exemptions are by NAME: 主人 (reserved for the owner line) and the
    render-only hub recorded in this profile's metadata."""
    meta_hub_null = {"key": "pm", "name": "P酱", "hub": None, "prefix": "test"}

    # Coordinator-keyed member still placeholder (hub:null → NO exemption):
    # its placeholder line must FAIL the check, named.
    ok, detail = _soul_check_with(
        tmp_hermes_home,
        meta_hub_null,
        '- @P酱：`<at user_id="ou_realpm">P酱</at>`\n'
        '- @老板：`<at user_id="ou_xxx_coordinator">老板</at>`\n',
    )
    assert ok is False and "老板" in detail

    # An owner-looking ID on a NON-owner name is not exempt either.
    ok, detail = _soul_check_with(
        tmp_hermes_home,
        meta_hub_null,
        '- @P酱：`<at user_id="ou_realpm">P酱</at>`\n'
        '- @老王：`<at user_id="ou_xxx_owner">老王</at>`\n',
    )
    assert ok is False and "老王" in detail

    # The owner line (name 主人) is exempt whatever its id.
    ok, _ = _soul_check_with(
        tmp_hermes_home,
        meta_hub_null,
        '- @P酱：`<at user_id="ou_realpm">P酱</at>`\n'
        '- @主人：`<at user_id="ou_xxx_owner">主人</at>`\n',
    )
    assert ok is True

    # The render-only hub is exempt BY ITS RECORDED NAME.
    ok, _ = _soul_check_with(
        tmp_hermes_home,
        {"key": "pm", "name": "P酱", "hub": {"name": "大总管"}, "prefix": "test"},
        '- @P酱：`<at user_id="ou_realpm">P酱</at>`\n'
        '- @大总管：`<at user_id="ou_xxx_coordinator">大总管</at>`\n',
    )
    assert ok is True

    # Legacy team (no metadata): the builtin M总 hub is exempt.
    ok, _ = _soul_check_with(
        tmp_hermes_home,
        None,
        '- @P酱：`<at user_id="ou_realpm">P酱</at>`\n'
        '- @M总：`<at user_id="ou_xxx_coordinator">M总</at>`\n',
    )
    assert ok is True


def test_verify_fails_on_dash_key_placeholder(tmp_hermes_home):
    """Role keys may contain dashes (_KEY_RE): the placeholder id
    ou_xxx_front-end must be SEEN by the check — a narrower id character
    class used to make it invisible and pass a team that cannot @ 前端."""
    ok, detail = _soul_check_with(
        tmp_hermes_home,
        {"key": "pm", "name": "P酱", "hub": None, "prefix": "test"},
        '- @P酱：`<at user_id="ou_realpm">P酱</at>`\n'
        '- @前端：`<at user_id="ou_xxx_front-end">前端</at>`\n',
    )
    assert ok is False
    assert "前端" in detail


def test_verify_placeholder_listing_truncates_names(tmp_hermes_home):
    """The detail lists the first 3 distinct names and counts the rest with
    (+N more) — listing everyone AND appending (+N more) reads as names the
    user cannot see."""
    soul = '- @P酱：`<at user_id="ou_realpm">P酱</at>`\n' + "".join(
        f'- @成员{i}：`<at user_id="ou_xxx_m{i}">成员{i}</at>`\n' for i in range(1, 8)
    )
    ok, detail = _soul_check_with(
        tmp_hermes_home, {"key": "pm", "name": "P酱", "hub": None, "prefix": "test"}, soul
    )
    assert ok is False
    assert "7 placeholder open_id(s) remain" in detail
    assert "(+4 more)" in detail  # 7 distinct names, 3 shown
    assert "成员7" not in detail  # the hidden ones are truly hidden
