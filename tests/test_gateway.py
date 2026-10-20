"""Tests for gateway helpers (multiplex-aware status + version parsing)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from hermes_multi_agent_team.utils.gateway import (
    _find_host_gateway_pid,
    gateway_status,
    get_hermes_version,
)

# --- multiplex-aware gateway status (Hermes >= 0.19: served profiles own no pid file) ---


def _make_profile(home: Path, name: str) -> None:
    (home / "profiles" / name).mkdir(parents=True)


def _host_record(home: Path, **overrides) -> None:
    """Write a host gateway_state.json into the temp Hermes home."""
    record: dict = {
        "pid": os.getpid(),
        "kind": "hermes-gateway",
        "gateway_state": "running",
        "served_profiles": [],
    }
    record.update(overrides)
    (home / "gateway_state.json").write_text(json.dumps(record))


def test_host_gateway_pid_serves_listed_profile(tmp_hermes_home: Path):
    _make_profile(tmp_hermes_home, "team-pm")
    _host_record(tmp_hermes_home, served_profiles=["team-pm", "team-fe"])

    assert _find_host_gateway_pid("team-pm") == os.getpid()
    assert gateway_status("team-pm")["pid"] == os.getpid()


def test_host_gateway_pid_ignores_unlisted_profile(tmp_hermes_home: Path):
    _make_profile(tmp_hermes_home, "team-pm")
    _host_record(tmp_hermes_home, served_profiles=["other-team"])

    assert _find_host_gateway_pid("team-pm") is None
    assert gateway_status("team-pm")["pid"] is None


def test_host_record_stopped_state_is_not_running(tmp_hermes_home: Path):
    """Hermes keeps gateway_state.json after stopping — a stopped record is no gateway."""
    _make_profile(tmp_hermes_home, "team-pm")
    _host_record(tmp_hermes_home, gateway_state="stopped", served_profiles=["team-pm"])

    assert _find_host_gateway_pid("team-pm") is None
    assert gateway_status("team-pm")["pid"] is None


def test_host_record_startup_failed_state_is_not_running(tmp_hermes_home: Path):
    _make_profile(tmp_hermes_home, "team-pm")
    _host_record(tmp_hermes_home, gateway_state="startup_failed", served_profiles=["team-pm"])

    assert _find_host_gateway_pid("team-pm") is None


def test_host_record_with_recycled_pid_is_rejected(tmp_hermes_home: Path):
    """A stale record whose PID was recycled by another process must not count."""
    _make_profile(tmp_hermes_home, "team-pm")
    stat_path = Path(f"/proc/{os.getpid()}/stat")
    if not stat_path.exists():
        pytest.skip("requires /proc (Linux)")
    actual_start_time = int(stat_path.read_text().split()[21])

    _host_record(tmp_hermes_home, start_time=actual_start_time + 1, served_profiles=["team-pm"])

    assert _find_host_gateway_pid("team-pm") is None
    assert gateway_status("team-pm")["pid"] is None


def test_host_record_with_matching_start_time_is_accepted(tmp_hermes_home: Path):
    _make_profile(tmp_hermes_home, "team-pm")
    stat_path = Path(f"/proc/{os.getpid()}/stat")
    if not stat_path.exists():
        pytest.skip("requires /proc (Linux)")
    actual_start_time = int(stat_path.read_text().split()[21])

    _host_record(tmp_hermes_home, start_time=actual_start_time, served_profiles=["team-pm"])

    assert _find_host_gateway_pid("team-pm") == os.getpid()


def test_host_record_with_wrong_kind_is_rejected(tmp_hermes_home: Path):
    _make_profile(tmp_hermes_home, "team-pm")
    _host_record(tmp_hermes_home, kind="something-else", served_profiles=["team-pm"])

    assert _find_host_gateway_pid("team-pm") is None


def test_host_record_without_gateway_state_is_rejected(tmp_hermes_home: Path):
    """A record that never confirmed a running state must not count (Hermes: None → down)."""
    _make_profile(tmp_hermes_home, "team-pm")
    record = {
        "pid": os.getpid(),
        "kind": "hermes-gateway",
        "served_profiles": ["team-pm"],
    }
    (tmp_hermes_home / "gateway_state.json").write_text(json.dumps(record))

    assert _find_host_gateway_pid("team-pm") is None
    assert gateway_status("team-pm")["pid"] is None


def test_host_record_without_kind_is_rejected(tmp_hermes_home: Path):
    _make_profile(tmp_hermes_home, "team-pm")
    record = {
        "pid": os.getpid(),
        "gateway_state": "running",
        "served_profiles": ["team-pm"],
    }
    (tmp_hermes_home / "gateway_state.json").write_text(json.dumps(record))

    assert _find_host_gateway_pid("team-pm") is None


def test_host_gateway_pid_ignores_dead_process(
    tmp_hermes_home: Path, monkeypatch: pytest.MonkeyPatch
):
    _make_profile(tmp_hermes_home, "team-pm")
    _host_record(tmp_hermes_home, served_profiles=["team-pm"])

    def _dead(pid: int, sig: int | None = None) -> None:
        raise ProcessLookupError(pid)

    monkeypatch.setattr("hermes_multi_agent_team.utils.gateway.os.kill", _dead)
    assert _find_host_gateway_pid("team-pm") is None


def test_host_gateway_pid_tolerates_missing_or_corrupt_state(tmp_hermes_home: Path):
    _make_profile(tmp_hermes_home, "team-pm")
    # No gateway_state.json at all…
    assert _find_host_gateway_pid("team-pm") is None
    # …and a corrupt one.
    (tmp_hermes_home / "gateway_state.json").write_text("{not json")
    assert _find_host_gateway_pid("team-pm") is None


# --- connected status (multiplex rung via the host record's platform states) ---


def test_connected_via_host_record_for_served_profile(tmp_hermes_home: Path):
    """Real multiplex path: a served profile's own log never says 'feishu connected'."""
    _make_profile(tmp_hermes_home, "team-pm")
    _host_record(
        tmp_hermes_home,
        served_profiles=["team-pm"],
        platforms={"team-pm:feishu": {"state": "connected"}},
    )

    assert gateway_status("team-pm")["connected"] is True


def test_last_message_time_read_even_when_host_state_authoritative(tmp_hermes_home: Path):
    """Log timestamps must surface for multiplex profiles too (status' Last Active)."""
    _make_profile(tmp_hermes_home, "team-pm")
    logs = tmp_hermes_home / "profiles" / "team-pm" / "logs"
    logs.mkdir(parents=True)
    (logs / "gateway.log").write_text(
        "2026-10-20 10:00:00 INFO [Feishu] Connected in websocket mode (feishu)\n"
        "2026-10-20 10:05:00 INFO user:ou_x message\n"
    )
    _host_record(
        tmp_hermes_home,
        served_profiles=["team-pm"],
        platforms={"team-pm:feishu": {"state": "connected"}},
    )

    gw = gateway_status("team-pm")

    assert gw["connected"] is True
    assert gw["last_message_time"] == "2026-10-20 10:05:00"


def test_connected_via_host_record_default_profile_uses_bare_key(tmp_hermes_home: Path):
    """The launch profile's platform state lives under the bare platform name."""
    _host_record(
        tmp_hermes_home,
        served_profiles=["default"],
        platforms={"feishu": {"state": "connected"}},
    )

    assert gateway_status("default")["connected"] is True


def test_not_connected_when_host_platform_state_is_error(tmp_hermes_home: Path):
    """The host state is authoritative: a stale Connected log line must not win."""
    _make_profile(tmp_hermes_home, "team-pm")
    logs = tmp_hermes_home / "profiles" / "team-pm" / "logs"
    logs.mkdir(parents=True)
    (logs / "gateway.log").write_text(
        "2026-10-20 10:00:00 INFO [Feishu] Connected in websocket mode (feishu)\n"
    )
    _host_record(
        tmp_hermes_home,
        served_profiles=["team-pm"],
        platforms={"team-pm:feishu": {"state": "error", "error_message": "bad secret"}},
    )

    assert gateway_status("team-pm")["connected"] is False


def test_stale_connected_log_does_not_override_retrying_host_state(tmp_hermes_home: Path):
    """host=retrying wins over the last [Feishu] Connected line in the profile log."""
    _make_profile(tmp_hermes_home, "team-pm")
    logs = tmp_hermes_home / "profiles" / "team-pm" / "logs"
    logs.mkdir(parents=True)
    (logs / "gateway.log").write_text(
        "2026-10-20 10:00:00 INFO [Feishu] Connected in websocket mode (feishu)\n"
        "2026-10-20 10:00:05 INFO [Feishu] Disconnected: websocket closed\n"
    )
    _host_record(
        tmp_hermes_home,
        served_profiles=["team-pm"],
        platforms={"team-pm:feishu": {"state": "retrying"}},
    )

    gw = gateway_status("team-pm")

    assert gw["connected"] is False
    assert gw["pid"] == os.getpid()  # host is alive and serving — only the state is bad


def test_connected_false_when_host_stopped_but_log_looks_connected(tmp_hermes_home: Path):
    """A stopped host + stale log must not report connected (running check would disagree)."""
    _make_profile(tmp_hermes_home, "team-pm")
    logs = tmp_hermes_home / "profiles" / "team-pm" / "logs"
    logs.mkdir(parents=True)
    (logs / "gateway.log").write_text(
        "2026-10-20 10:00:00 INFO [Feishu] Connected in websocket mode (feishu)\n"
    )
    _host_record(tmp_hermes_home, gateway_state="stopped", served_profiles=["team-pm"])

    gw = gateway_status("team-pm")

    assert gw["pid"] is None
    assert gw["connected"] is False


def test_connected_via_real_adapter_log_line(tmp_hermes_home: Path):
    """Standalone rung: the adapter's '[Feishu] Connected' log line counts as connected.

    This is the only connection line a profile-local log ever carries — the old
    pattern ("feishu connected") never matched it.
    """
    profile = tmp_hermes_home / "profiles" / "team-x"
    profile.mkdir(parents=True)
    (profile / "gateway.pid").write_text(str(os.getpid()))
    logs = profile / "logs"
    logs.mkdir()
    (logs / "gateway.log").write_text(
        "2026-10-20 10:00:00 INFO [Feishu] Connected in websocket mode (feishu)\n"
    )

    gw = gateway_status("team-x")

    assert gw["connected"] is True
    assert gw["pid"] == os.getpid()


# --- get_hermes_version: returncode gate + marker-first matching ---


def test_get_hermes_version_parses_semver(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kw: CompletedProcess(cmd, 0, stdout="hermes, version 0.22.2", stderr=""),
    )
    assert get_hermes_version("/fake/hermes") == (0, 22, 2)


def test_get_hermes_version_prefers_semver_over_date(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kw: CompletedProcess(cmd, 0, stdout="v0.19.0 (v2026.7.20)", stderr=""),
    )
    assert get_hermes_version("/fake/hermes") == (0, 19, 0)


def test_get_hermes_version_requires_zero_returncode(monkeypatch: pytest.MonkeyPatch):
    """A failing `hermes --version` must not yield a version parsed from its noise."""
    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kw: CompletedProcess(cmd, 1, stdout="", stderr="Python 3.14.3 (main)"),
    )
    assert get_hermes_version("/fake/hermes") is None


def test_get_hermes_version_prefers_marker_over_python_banner(monkeypatch: pytest.MonkeyPatch):
    """Real output mixes the CLI version with a Python version — pick the right one."""
    stdout = "Hermes Agent v0.22.2 (2026.9.24) · stable\nInstall directory: /x\nPython: 3.14.7\n"
    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kw: CompletedProcess(cmd, 0, stdout=stdout, stderr=""),
    )
    assert get_hermes_version("/fake/hermes") == (0, 22, 2)


def test_get_hermes_version_ignores_stderr(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kw: CompletedProcess(cmd, 0, stdout="ok", stderr="warning 9.9.9"),
    )
    assert get_hermes_version("/fake/hermes") is None


def test_get_hermes_version_returns_none_when_binary_missing(monkeypatch: pytest.MonkeyPatch):
    def _raise(cmd, **kw):
        raise FileNotFoundError(cmd)

    monkeypatch.setattr("subprocess.run", _raise)
    assert get_hermes_version("/fake/hermes") is None


def test_get_hermes_version_returns_none_on_timeout(monkeypatch: pytest.MonkeyPatch):
    def _hang(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 15)

    monkeypatch.setattr("subprocess.run", _hang)
    assert get_hermes_version("/fake/hermes") is None
