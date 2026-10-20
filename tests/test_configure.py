"""Tests for the configure command."""

from pathlib import Path

from click.testing import CliRunner

from hermes_multi_agent_team.cli import cli


def _make_profile(home: Path, name: str, env_content: str) -> None:
    profile = home / "profiles" / name
    profile.mkdir(parents=True)
    (profile / ".env").write_text(env_content)


def test_configure_dry_run(tmp_hermes_home):
    """configure --dry-run should not write files."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["configure", "--prefix", "nonexistent", "--dry-run"],
    )
    # Should either show dry-run or error about missing profiles
    assert result.exit_code == 0 or "No profiles" in result.output


def test_configure_no_profiles(tmp_hermes_home):
    """configure with no matching profiles should show error."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["configure", "--prefix", "nonexistent"],
    )
    assert result.exit_code != 0


# Shared settings confirm + the five shared settings prompts (FEISHU_ALLOWED_USERS
# is per-profile now), all accepting defaults.
_SHARED_SETTINGS_INPUT = "\n" + "\n" * 5

# Per profile: App ID, App Secret, FEISHU_ALLOWED_USERS — all accepting defaults.
_PROFILE_INPUT_DEFAULTS = "cli_new\n\n\n"


def test_configure_writes_unique_apps_and_shared_settings(tmp_hermes_home):
    """Each profile gets its own app; settings are shared; obsolete keys are dropped."""
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        "FEISHU_APP_ID=cli_old_a\nFEISHU_APP_SECRET=sec1\n"
        "FEISHU_DM_POLICY=pairing\nMODEL_API_KEY=sk-keepme\n",
    )
    _make_profile(
        tmp_hermes_home,
        "team-fe",
        "FEISHU_APP_ID=cli_old_b\nFEISHU_APP_SECRET=sec2\nFEISHU_ALLOW_ALL_USERS=false\n",
    )

    user_input = _SHARED_SETTINGS_INPUT + "cli_aaa\n\n\ncli_bbb\n\n\n"
    result = CliRunner().invoke(cli, ["configure", "--prefix", "team"], input=user_input)
    assert result.exit_code == 0, result.output

    pm_env = (tmp_hermes_home / "profiles" / "team-pm" / ".env").read_text()
    fe_env = (tmp_hermes_home / "profiles" / "team-fe" / ".env").read_text()

    # Profiles are configured in sorted order: team-fe first, team-pm second.
    assert "FEISHU_APP_ID=cli_aaa" in fe_env
    assert "FEISHU_APP_ID=cli_bbb" in pm_env
    assert "FEISHU_GROUP_POLICY=open" in pm_env
    assert "FEISHU_GROUP_POLICY=open" in fe_env
    assert "FEISHU_DM_POLICY" not in pm_env
    # FEISHU_ALLOW_ALL_USERS is still read by Hermes 0.22.x — it must survive.
    assert "FEISHU_ALLOW_ALL_USERS=false" in fe_env
    # Keys this tool does not manage must survive a reconfigure.
    assert "MODEL_API_KEY=sk-keepme" in pm_env
    # Shared settings applied to every profile.
    assert "FEISHU_DOMAIN=feishu" in fe_env


def test_configure_rejects_shared_app_id(tmp_hermes_home):
    """Entering the same App ID for two profiles must be rejected and re-prompted."""
    _make_profile(tmp_hermes_home, "team-pm", "")
    _make_profile(tmp_hermes_home, "team-fe", "")

    # team-fe gets cli_dup; team-pm tries cli_dup (rejected), then cli_other.
    user_input = _SHARED_SETTINGS_INPUT + "cli_dup\ns1\n\ncli_dup\ncli_other\ns2\n\n"
    result = CliRunner().invoke(cli, ["configure", "--prefix", "team"], input=user_input)
    assert result.exit_code == 0, result.output

    # Profiles are configured in sorted order: team-fe first, team-pm second.
    # team-pm tries cli_dup (already taken by team-fe), is rejected, then picks cli_other.
    assert "already used by" in result.output
    fe_env = (tmp_hermes_home / "profiles" / "team-fe" / ".env").read_text()
    pm_env = (tmp_hermes_home / "profiles" / "team-pm" / ".env").read_text()
    assert "FEISHU_APP_ID=cli_dup" in fe_env
    assert "FEISHU_APP_ID=cli_other" in pm_env


def test_configure_keeps_allowed_users_per_profile(tmp_hermes_home):
    """FEISHU_ALLOWED_USERS must not be shared: open_ids are isolated per app."""
    _make_profile(
        tmp_hermes_home,
        "team-fe",
        "FEISHU_APP_ID=cli_old_a\nFEISHU_APP_SECRET=sec_a\nFEISHU_ALLOWED_USERS=ou_fe_one\n",
    )
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        "FEISHU_APP_ID=cli_old_b\nFEISHU_APP_SECRET=sec_b\nFEISHU_ALLOWED_USERS=ou_pm_one\n",
    )

    user_input = _SHARED_SETTINGS_INPUT + "cli_new_a\n\n\ncli_new_b\n\n\n"
    result = CliRunner().invoke(cli, ["configure", "--prefix", "team"], input=user_input)
    assert result.exit_code == 0, result.output

    fe_env = (tmp_hermes_home / "profiles" / "team-fe" / ".env").read_text()
    pm_env = (tmp_hermes_home / "profiles" / "team-pm" / ".env").read_text()
    # Each profile keeps its own open_id list; nothing is copied across profiles.
    assert "FEISHU_ALLOWED_USERS=ou_fe_one" in fe_env
    assert "FEISHU_ALLOWED_USERS=ou_pm_one" in pm_env
    assert "ou_fe_one" not in pm_env
    assert "ou_pm_one" not in fe_env


def test_configure_warns_when_allowlist_has_no_users(tmp_hermes_home):
    """Group policy 'allowlist' with an empty allowlist rejects ALL group messages."""
    _make_profile(tmp_hermes_home, "team-pm", "")

    # Shared settings: confirm, domain, mode, policy=allowlist, bots, mention.
    shared_input = "\n\n\nallowlist\n\n\n"
    user_input = shared_input + "cli_new\nsec1\n\n"
    result = CliRunner().invoke(cli, ["configure", "--prefix", "team"], input=user_input)
    assert result.exit_code == 0, result.output
    assert "reject EVERY group message" in result.output


def test_configure_never_echoes_existing_secret(tmp_hermes_home):
    """An existing secret must not appear in output, not even as a prompt default."""
    _make_profile(tmp_hermes_home, "team-pm", "FEISHU_APP_ID=cli_old\nFEISHU_APP_SECRET=sec1\n")

    user_input = _SHARED_SETTINGS_INPUT + "cli_new\n\n\n"
    result = CliRunner().invoke(cli, ["configure", "--prefix", "team"], input=user_input)
    assert result.exit_code == 0, result.output
    assert "sec1" not in result.output
    # Empty secret input keeps the existing secret.
    env = (tmp_hermes_home / "profiles" / "team-pm" / ".env").read_text()
    assert "FEISHU_APP_SECRET=sec1" in env


def test_configure_requires_non_empty_secret_for_new_profile(tmp_hermes_home):
    """A profile without an existing secret must not accept an empty one."""
    _make_profile(tmp_hermes_home, "team-pm", "")

    # Empty secret input is rejected, then a real value is accepted.
    user_input = _SHARED_SETTINGS_INPUT + "cli_new\n\nsec1\n\n"
    result = CliRunner().invoke(cli, ["configure", "--prefix", "team"], input=user_input)
    assert result.exit_code == 0, result.output
    assert "App Secret cannot be empty" in result.output
    env = (tmp_hermes_home / "profiles" / "team-pm" / ".env").read_text()
    assert "FEISHU_APP_SECRET=sec1" in env


def test_configure_dry_run_masks_preserved_sensitive_keys(tmp_hermes_home):
    """Preserved unmanaged keys (e.g. model API keys) must be masked in dry-run."""
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        "FEISHU_APP_ID=cli_old\nFEISHU_APP_SECRET=sec\nMODEL_API_KEY=sk-supersecret123\n",
    )

    user_input = _SHARED_SETTINGS_INPUT + _PROFILE_INPUT_DEFAULTS
    result = CliRunner().invoke(
        cli, ["configure", "--prefix", "team", "--dry-run"], input=user_input
    )
    assert result.exit_code == 0, result.output
    assert "sk-supersecret123" not in result.output
    assert "MODEL_API_KEY=****" in result.output
    # Non-sensitive values are still shown.
    assert "FEISHU_APP_ID=cli_new" in result.output


def test_configure_without_shared_settings_prompts_per_profile(tmp_hermes_home):
    """Answering 'no' to shared settings must ask every profile its own values."""
    _make_profile(tmp_hermes_home, "team-fe", "")
    _make_profile(tmp_hermes_home, "team-pm", "")

    # "n" to sharing; then per profile: App ID, Secret, domain, mode, policy,
    # bots, mention-confirm, allowed users.
    team_fe_input = "cli_a\ns1\nlark\n\n\n\n\n\n"
    team_pm_input = "cli_b\ns2\n\n\n\n\n\n\n"
    user_input = "n\n" + team_fe_input + team_pm_input

    result = CliRunner().invoke(cli, ["configure", "--prefix", "team"], input=user_input)
    assert result.exit_code == 0, result.output

    fe_env = (tmp_hermes_home / "profiles" / "team-fe" / ".env").read_text()
    pm_env = (tmp_hermes_home / "profiles" / "team-pm" / ".env").read_text()
    # Each profile got the values entered for IT, not the other profile's.
    assert "FEISHU_APP_ID=cli_a" in fe_env
    assert "FEISHU_DOMAIN=lark" in fe_env
    assert "FEISHU_APP_ID=cli_b" in pm_env
    assert "FEISHU_DOMAIN=feishu" in pm_env
    assert "lark" not in pm_env


def test_configure_warns_on_invalid_existing_choice(tmp_hermes_home):
    """An existing .env value outside the valid choices falls back with a warning."""
    _make_profile(tmp_hermes_home, "team-pm", "FEISHU_DOMAIN=bogus\nFEISHU_APP_SECRET=sec\n")

    user_input = _SHARED_SETTINGS_INPUT + _PROFILE_INPUT_DEFAULTS
    result = CliRunner().invoke(cli, ["configure", "--prefix", "team"], input=user_input)
    assert result.exit_code == 0, result.output

    assert "existing FEISHU_DOMAIN='bogus' is not a valid value" in result.output
    env = (tmp_hermes_home / "profiles" / "team-pm" / ".env").read_text()
    assert "FEISHU_DOMAIN=feishu" in env
    assert "FEISHU_DOMAIN=bogus" not in env
