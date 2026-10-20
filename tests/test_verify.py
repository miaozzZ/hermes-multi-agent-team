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
    (profile / "SOUL.md").write_text('user_id="ou_real1234"')
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
    (profile / "SOUL.md").write_text('user_id="ou_real1234"')
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
    (profile / "SOUL.md").write_text('user_id="ou_real1234"')
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
    assert "unreadable or empty" in result.output
    assert "~/.hermes/.env (default profile)" in result.output
    assert "Traceback" not in result.output
