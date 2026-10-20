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
