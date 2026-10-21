"""Tests for profile helpers (listing + host-serving determination)."""

from __future__ import annotations

from pathlib import Path

from hermes_multi_agent_team.utils.profile import (
    list_all_profile_names,
    list_team_profiles,
    profile_served_by_host,
    read_env,
)


def _make_real_profile(home: Path, name: str) -> Path:
    """A directory carrying an identity marker (an .env), i.e. a real profile."""
    profile = home / "profiles" / name
    profile.mkdir(parents=True, exist_ok=True)
    (profile / ".env").write_text("")
    return profile


def test_list_team_profiles_skips_ghost_and_tombstoned(tmp_hermes_home: Path):
    """Ghost dirs (runtime side-effects) and tombstones are not team profiles —
    treating them as members would fail start/verify on 'missing credentials'."""
    _make_real_profile(tmp_hermes_home, "team-pm")
    ghost = tmp_hermes_home / "profiles" / "team-ghost"
    (ghost / "logs").mkdir(parents=True)  # side-effect dirs only, no marker
    gone = _make_real_profile(tmp_hermes_home, "team-gone")
    (tmp_hermes_home / "profiles" / ".deleted" / "team-gone").mkdir(parents=True)
    gone.joinpath("x").touch()  # still has identity, but tombstoned

    assert list_team_profiles("team") == ["team-pm"]


def test_list_team_profiles_isolates_prefix_that_prefixes_another_team(tmp_hermes_home: Path):
    """A bare startswith(prefix) has no boundary: with teams 'team'/'teamq',
    every command run against 'team' used to swallow teamq's profiles —
    destroy would list (and delete) them, collect-ids would merge both teams'
    name→open_id mappings, start would demand teamq's credentials."""
    for name in ("team-pm", "team-qa", "teamq-qa", "teamquote-pm"):
        _make_real_profile(tmp_hermes_home, name)

    assert list_team_profiles("team") == ["team-pm", "team-qa"]
    assert list_team_profiles("teamq") == ["teamq-qa"]
    assert list_team_profiles("teamquote") == ["teamquote-pm"]


def test_list_team_profiles_matches_standalone_bot_by_exact_name(tmp_hermes_home: Path):
    """new-bot profiles carry no '<prefix>-<key>' shape: the bot named exactly
    like a queried prefix must still be found (configure --prefix NAME)."""
    _make_real_profile(tmp_hermes_home, "mybot")
    _make_real_profile(tmp_hermes_home, "mybot-helper")

    assert list_team_profiles("mybot") == ["mybot", "mybot-helper"]
    assert list_team_profiles("mybo") == []


def test_write_env_creates_file_owner_only(tmp_hermes_home: Path):
    """The .env carries the Feishu App Secret — a fresh file must be 0600 no
    matter the umask (a plain write_text leaves 0644/0664, readable by other
    local users)."""
    import os

    from hermes_multi_agent_team.utils.profile import write_env

    old_umask = os.umask(0o022)  # typical default: would yield 0644
    try:
        # Directory only — the .env itself must not pre-exist (fresh create).
        (tmp_hermes_home / "profiles" / "team-pm").mkdir(parents=True)
        write_env("team-pm", {"FEISHU_APP_SECRET": "s3cret"})
    finally:
        os.umask(old_umask)

    env_path = tmp_hermes_home / "profiles" / "team-pm" / ".env"
    assert env_path.read_text() == "FEISHU_APP_SECRET=s3cret\n"
    assert env_path.stat().st_mode & 0o777 == 0o600


def test_write_env_tightens_loose_existing_file_permissions(tmp_hermes_home: Path):
    """An existing .env left group/other-readable (0644 — created before the
    0600 rule or loosened by hand) carries the App Secret after a
    reconfigure: write_env must tighten it to 0600, not preserve the loose
    mode silently. Stricter-than-0600 modes are kept as-is."""
    from hermes_multi_agent_team.utils.profile import write_env

    loose = _make_real_profile(tmp_hermes_home, "team-pm") / ".env"
    loose.write_text("FEISHU_APP_ID=old\n")
    loose.chmod(0o644)

    assert write_env("team-pm", {"FEISHU_APP_ID": "cli_x"}) is True
    assert loose.read_text() == "FEISHU_APP_ID=cli_x\n"
    assert loose.stat().st_mode & 0o777 == 0o600

    already_ok = _make_real_profile(tmp_hermes_home, "team-qa") / ".env"
    already_ok.write_text("FEISHU_APP_ID=old\n")
    already_ok.chmod(0o600)

    assert write_env("team-qa", {"FEISHU_APP_ID": "cli_y"}) is False
    assert already_ok.stat().st_mode & 0o777 == 0o600  # already owner-only: kept


def test_read_env_unreadable_file_returns_empty(tmp_hermes_home: Path):
    """A broken-encoding .env must not raise out of read_env — one bad file must
    not crash a whole-team command."""
    profile = _make_real_profile(tmp_hermes_home, "team-pm")
    (profile / ".env").write_bytes(b"FEISHU_APP_ID=\xff\xfe\x00bad")

    assert read_env("team-pm") == {}


def test_lists_all_profiles_across_prefixes(tmp_hermes_home: Path):
    for name in ("team-pm", "team-fe", "other-pm"):
        _make_real_profile(tmp_hermes_home, name)

    assert list_all_profile_names() == ["other-pm", "team-fe", "team-pm"]


def test_skips_ghost_directories_without_identity_marker(tmp_hermes_home: Path):
    """Runtime side-effects (cron heartbeats, logs) leave marker-less dirs that
    Hermes never lists or serves — a leftover FEISHU_APP_ID in one must not
    block `start`."""
    _make_real_profile(tmp_hermes_home, "team-pm")
    ghost = tmp_hermes_home / "profiles" / "ghost-pm"
    (ghost / "logs").mkdir(parents=True)  # side-effect dirs only, no marker file

    assert list_all_profile_names() == ["team-pm"]


def test_skips_tombstoned_profiles(tmp_hermes_home: Path):
    _make_real_profile(tmp_hermes_home, "team-pm")
    _make_real_profile(tmp_hermes_home, "gone-pm")
    deleted = tmp_hermes_home / "profiles" / ".deleted" / "gone-pm"
    deleted.mkdir(parents=True)

    assert list_all_profile_names() == ["team-pm"]


def test_skips_stray_default_directory(tmp_hermes_home: Path):
    """The default profile lives in the Hermes home itself, never under profiles/."""
    _make_real_profile(tmp_hermes_home, "team-pm")
    _make_real_profile(tmp_hermes_home, "default")

    assert list_all_profile_names() == ["team-pm"]


def test_parked_marker_opts_profile_out(tmp_hermes_home: Path):
    """`hermes -p X gateway stop` leaves a gateway.parked marker the host skips."""
    profile = _make_real_profile(tmp_hermes_home, "team-pm")
    (profile / "gateway.parked").write_text("")

    assert profile_served_by_host("team-pm") is False


def test_config_standalone_two_space_indent_opts_out(tmp_hermes_home: Path):
    profile = _make_real_profile(tmp_hermes_home, "team-pm")
    (profile / "config.yaml").write_text("model:\n  default: gpt\n\ngateway:\n  standalone: true\n")

    assert profile_served_by_host("team-pm") is False


def test_config_standalone_four_space_indent_opts_out(tmp_hermes_home: Path):
    """4-space YAML is equally valid — the child indent is learned, not assumed."""
    profile = _make_real_profile(tmp_hermes_home, "team-pm")
    (profile / "config.yaml").write_text(
        "model:\n    default: gpt\n\ngateway:\n    standalone: true\n"
    )

    assert profile_served_by_host("team-pm") is False


def test_standalone_with_inline_comment_opts_out(tmp_hermes_home: Path):
    """`standalone: true # opted out` — the comment must be stripped before tokenizing."""
    profile = _make_real_profile(tmp_hermes_home, "team-pm")
    (profile / "config.yaml").write_text(
        "gateway:\n  standalone: true # opted out of the host gateway\n"
    )

    assert profile_served_by_host("team-pm") is False


def test_standalone_inline_comment_four_space_indent(tmp_hermes_home: Path):
    profile = _make_real_profile(tmp_hermes_home, "team-pm")
    (profile / "config.yaml").write_text(
        "gateway:\n    standalone: true  # keep this bot off the host gateway\n"
    )

    assert profile_served_by_host("team-pm") is False


def test_quoted_hash_is_data_not_comment(tmp_hermes_home: Path):
    """A '#' inside a quoted scalar is part of the value — token is not truthy."""
    profile = _make_real_profile(tmp_hermes_home, "team-pm")
    (profile / "config.yaml").write_text('gateway:\n  standalone: "true # x"\n')

    assert profile_served_by_host("team-pm") is True


def test_gateway_inline_flow_with_comment_opts_out(tmp_hermes_home: Path):
    profile = _make_real_profile(tmp_hermes_home, "team-pm")
    (profile / "config.yaml").write_text("gateway: {standalone: true} # manual setup\n")

    assert profile_served_by_host("team-pm") is False


def test_gateway_inline_flow_mapping_opts_out(tmp_hermes_home: Path):
    profile = _make_real_profile(tmp_hermes_home, "team-pm")
    (profile / "config.yaml").write_text("gateway: {standalone: true, rescan: 30}\n")

    assert profile_served_by_host("team-pm") is False


def test_gateway_inline_flow_mapping_false_serves(tmp_hermes_home: Path):
    profile = _make_real_profile(tmp_hermes_home, "team-pm")
    (profile / "config.yaml").write_text("gateway: {standalone: false}\n")

    assert profile_served_by_host("team-pm") is True


def test_standalone_false_or_missing_serves(tmp_hermes_home: Path):
    profile = _make_real_profile(tmp_hermes_home, "team-pm")
    # Project template shape: no gateway section at all.
    (profile / "config.yaml").write_text("model:\n  default: gpt\nlanguage: zh\n")

    assert profile_served_by_host("team-pm") is True

    (profile / "config.yaml").write_text("gateway:\n  standalone: false\n")

    assert profile_served_by_host("team-pm") is True


def test_deeper_nested_standalone_key_is_not_matched(tmp_hermes_home: Path):
    """Only gateway.standalone counts, not gateway.<sub>.standalone."""
    profile = _make_real_profile(tmp_hermes_home, "team-pm")
    (profile / "config.yaml").write_text("gateway:\n  rescan:\n    standalone: true\n")

    assert profile_served_by_host("team-pm") is True


def test_unreadable_config_counts_as_served(tmp_hermes_home: Path):
    """Over-reporting a credential clash is safer than silently skipping a profile."""
    profile = _make_real_profile(tmp_hermes_home, "team-pm")
    (profile / "config.yaml").write_bytes(b"\xff\xfe\x00broken")

    assert profile_served_by_host("team-pm") is True


def test_unterminated_quote_counts_as_served(tmp_hermes_home: Path):
    """`standalone: "true` is broken YAML: Hermes raises YAMLError → not standalone
    → the host SERVES the profile. An empty (non-truthy) token mirrors that."""
    profile = _make_real_profile(tmp_hermes_home, "team-pm")
    (profile / "config.yaml").write_text('gateway:\n  standalone: "true\n')

    assert profile_served_by_host("team-pm") is True


def test_read_default_env_unreadable_returns_empty(tmp_hermes_home: Path):
    """A broken-encoding ~/.hermes/.env must not raise out of read_default_env."""
    (tmp_hermes_home / ".env").write_bytes(b"FEISHU_APP_ID=\xff\xfe\x00bad")

    from hermes_multi_agent_team.utils.profile import read_default_env

    assert read_default_env() == {}


def test_read_soul_unreadable_returns_empty(tmp_hermes_home: Path):
    """A broken-encoding SOUL.md must not raise out of read_soul."""
    profile = _make_real_profile(tmp_hermes_home, "team-pm")
    (profile / "SOUL.md").write_bytes(b"\xff\xfe user_id=ou_xxx")

    from hermes_multi_agent_team.utils.profile import read_soul

    assert read_soul("team-pm") == ""


def test_team_metadata_corrupt_detection(tmp_hermes_home: Path):
    """Corrupt .hermes-team.json is distinguishable from absent metadata:
    read_team_metadata stays tolerant ({}) while team_metadata_corrupt flags
    the broken file so safety-relevant paths (destroy/init/member) can fail
    closed — a corrupt file hides any standalone marker it carried."""
    from hermes_multi_agent_team.utils.profile import (
        is_standalone_profile,
        read_team_metadata,
        team_metadata_corrupt,
    )

    _make_real_profile(tmp_hermes_home, "p-absent")
    assert team_metadata_corrupt("p-absent") is False
    assert read_team_metadata("p-absent") == {}

    valid = _make_real_profile(tmp_hermes_home, "p-valid")
    (valid / ".hermes-team.json").write_text('{"standalone": true}', encoding="utf-8")
    assert team_metadata_corrupt("p-valid") is False
    assert is_standalone_profile("p-valid") is True

    broken = _make_real_profile(tmp_hermes_home, "p-broken")
    (broken / ".hermes-team.json").write_text("{broken", encoding="utf-8")
    assert team_metadata_corrupt("p-broken") is True
    assert read_team_metadata("p-broken") == {}  # tolerant read unchanged
    assert is_standalone_profile("p-broken") is False  # marker hidden by corruption

    nondict = _make_real_profile(tmp_hermes_home, "p-nondict")
    (nondict / ".hermes-team.json").write_text("[1, 2]", encoding="utf-8")
    assert team_metadata_corrupt("p-nondict") is True


def _make_metadata(home: Path, profile: str, metadata: dict) -> None:
    import json

    d = home / "profiles" / profile
    d.mkdir(parents=True, exist_ok=True)
    (d / ".env").write_text("")
    (d / ".hermes-team.json").write_text(
        json.dumps(metadata, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def test_list_team_profiles_uses_recorded_prefix_for_dash_nested_teams(tmp_hermes_home: Path):
    """Name matching cannot split dash-nested prefixes ('team-pm' and
    'team-extra-pm' both start with 'team-'): profiles that record their
    team's prefix in metadata are matched on it exactly, so remove-member /
    destroy / collect-ids stay team-scoped."""
    _make_metadata(tmp_hermes_home, "team-pm", {"key": "pm", "name": "P酱", "prefix": "team"})
    _make_metadata(
        tmp_hermes_home,
        "team-extra-pm",
        {"key": "pm", "name": "P酱", "prefix": "team-extra"},
    )

    assert list_team_profiles("team") == ["team-pm"]
    assert list_team_profiles("team-extra") == ["team-extra-pm"]


def test_list_team_profiles_name_fallback_for_legacy_and_standalone(tmp_hermes_home: Path):
    """No recorded prefix (legacy pre-metadata profiles, standalone bots) →
    name-based fallback: exact name or '<prefix>-<rest>'."""
    # Legacy team profile: no metadata at all.
    _make_real_profile(tmp_hermes_home, "team-qa")
    # Standalone bot: metadata without a prefix field.
    _make_metadata(tmp_hermes_home, "mybot", {"standalone": True, "key": "mybot", "name": "mybot"})

    assert list_team_profiles("team") == ["team-qa"]
    assert list_team_profiles("mybot") == ["mybot"]


def test_write_env_grants_owner_write_on_readonly_env(tmp_hermes_home: Path):
    """A 0400 .env used to crash write_env with a bare PermissionError at
    os.open(O_WRONLY) — mid-configure, after every prompt was answered. The
    rewrite is explicit, so the owner-write bit is granted first; the file
    ends owner-only (0600)."""
    from hermes_multi_agent_team.utils.profile import write_env

    env_path = _make_real_profile(tmp_hermes_home, "team-pm") / ".env"
    env_path.write_text("FEISHU_APP_ID=old\n")
    env_path.chmod(0o400)

    write_env("team-pm", {"FEISHU_APP_ID": "cli_x"})

    assert env_path.read_text() == "FEISHU_APP_ID=cli_x\n"
    assert env_path.stat().st_mode & 0o777 == 0o600


def test_legacy_dash_nested_profiles_fail_closed_by_name(tmp_hermes_home: Path):
    """Without metadata, 'team-extra-pm' under prefix 'team' is ambiguous
    (dash-keyed member of 'team' vs plain member of 'team-extra') — the
    listing fails closed: excluded from 'team', still served to its LONGEST
    plausible prefix 'team-extra'. A metadata-recorded member of the same
    name stays with its own team via the recorded prefix."""
    _make_real_profile(tmp_hermes_home, "team-pm")
    _make_real_profile(tmp_hermes_home, "team-extra-pm")
    _make_metadata(
        tmp_hermes_home,
        "team-extra-qa",
        {"key": "qa", "name": "Q宝", "prefix": "team-extra"},
    )

    assert list_team_profiles("team") == ["team-pm"]
    assert list_team_profiles("team-extra") == ["team-extra-pm", "team-extra-qa"]
    # The exclusion is discoverable for command-level warnings.
    from hermes_multi_agent_team.utils.profile import list_name_ambiguous_profiles

    assert list_name_ambiguous_profiles("team") == ["team-extra-pm"]
    assert list_name_ambiguous_profiles("team-extra") == []


def test_name_ambiguous_list_skips_standalone_and_removed(tmp_hermes_home: Path):
    """Standalone bots and kept-but-removed profiles are never team
    candidates — the ambiguity hint must not tell the user to 're-init'
    their bot or departed member under another team."""
    from hermes_multi_agent_team.utils.profile import list_name_ambiguous_profiles

    _make_real_profile(tmp_hermes_home, "sign-pm")
    _make_metadata(
        tmp_hermes_home,
        "sign-extra-bot",
        {"standalone": True, "key": "sign-extra-bot", "name": "sign-extra-bot"},
    )
    _make_metadata(
        tmp_hermes_home,
        "sign-extra-old",
        {"key": "old", "name": "旧人", "removed": True},
    )

    assert list_name_ambiguous_profiles("sign") == []
