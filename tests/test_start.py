"""Tests for the start command (multiplexed + legacy gateway modes)."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from subprocess import CompletedProcess

import pytest
from click.testing import CliRunner

from hermes_multi_agent_team.cli import cli


def _make_profile(home: Path, name: str, app_id: str | None, secret: str = "sec") -> None:
    profile = home / "profiles" / name
    profile.mkdir(parents=True)
    env = ""
    if app_id is not None:
        env += f"FEISHU_APP_ID={app_id}\nFEISHU_APP_SECRET={secret}\n"
    (profile / ".env").write_text(env)


@pytest.fixture()
def fake_hermes_bin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A hermes binary path that actually exists, so start's existence check passes."""
    binary = tmp_path / "bin" / "hermes"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setattr("shutil.which", lambda name: str(binary) if name == "hermes" else None)
    return binary


class FakeRun:
    """subprocess.run replacement: reports a version for --version, succeeds otherwise."""

    def __init__(self, version_output: str = "", returncode: int = 0):
        self.version_output = version_output
        self.returncode = returncode
        self.calls: list[list[str]] = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        if "--version" in cmd:
            return CompletedProcess(cmd, 0, stdout=self.version_output, stderr="")
        return CompletedProcess(cmd, self.returncode, stdout="", stderr="error")


def _fake_run_for(version_output: str, status_result: CompletedProcess | Exception):
    """subprocess.run replacement with a configurable `gateway status` outcome."""

    def _run(cmd, **kwargs):
        if "--version" in cmd:
            return CompletedProcess(cmd, 0, stdout=version_output, stderr="")
        if "status" in cmd:
            if isinstance(status_result, Exception):
                raise status_result
            return status_result
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    return _run


# --- start (multiplexed, the default since Hermes 0.19) ---


def test_start_multiplex_dry_run_runs_host_gateway_once(
    tmp_hermes_home, fake_hermes_bin, monkeypatch
):
    _make_profile(tmp_hermes_home, "team-pm", "cli_aaa")
    _make_profile(tmp_hermes_home, "team-fe", "cli_bbb")
    fake = FakeRun(version_output="hermes 0.22.2")
    monkeypatch.setattr("subprocess.run", fake)

    result = CliRunner().invoke(cli, ["start", "--prefix", "team", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "Multiplexed mode" in result.output
    assert f"{fake_hermes_bin} gateway install" in result.output
    assert f"{fake_hermes_bin} gateway start" in result.output
    # Host gateway is started once — never per profile.
    assert "--profile" not in result.output


def test_start_multiplex_success_prints_gateway_status(
    tmp_hermes_home, fake_hermes_bin, monkeypatch
):
    """Non-dry-run happy path: install/start succeed, status output is shown."""
    _make_profile(tmp_hermes_home, "team-pm", "cli_aaa")
    monkeypatch.setattr(
        "subprocess.run",
        _fake_run_for(
            "hermes 0.22.2",
            CompletedProcess([], 0, stdout="gateway: running (pid 123)", stderr=""),
        ),
    )

    result = CliRunner().invoke(cli, ["start", "--prefix", "team"])

    assert result.exit_code == 0, result.output
    assert f"{fake_hermes_bin} gateway install" in result.output
    assert f"{fake_hermes_bin} gateway start" in result.output
    assert "Gateway status" in result.output
    assert "gateway: running (pid 123)" in result.output


def test_start_multiplex_survives_gateway_status_timeout(
    tmp_hermes_home, fake_hermes_bin, monkeypatch
):
    """A hanging `gateway status` must not fail the command — install/start already won."""
    _make_profile(tmp_hermes_home, "team-pm", "cli_aaa")
    monkeypatch.setattr(
        "subprocess.run",
        _fake_run_for("hermes 0.22.2", subprocess.TimeoutExpired([], 30)),
    )

    result = CliRunner().invoke(cli, ["start", "--prefix", "team"])

    assert result.exit_code == 0, result.output
    assert "Could not read `hermes gateway status`" in result.output


def test_start_multiplex_survives_missing_hermes_binary_at_status(
    tmp_hermes_home, fake_hermes_bin, monkeypatch
):
    """FileNotFoundError from the status call degrades to a hint, not a traceback."""
    _make_profile(tmp_hermes_home, "team-pm", "cli_aaa")
    monkeypatch.setattr(
        "subprocess.run",
        _fake_run_for("hermes 0.22.2", FileNotFoundError("hermes vanished")),
    )

    result = CliRunner().invoke(cli, ["start", "--prefix", "team"])

    assert result.exit_code == 0, result.output
    assert "Could not read `hermes gateway status`" in result.output


def test_start_rejects_duplicate_app_ids(tmp_hermes_home, fake_hermes_bin, monkeypatch):
    _make_profile(tmp_hermes_home, "team-pm", "cli_same")
    _make_profile(tmp_hermes_home, "team-fe", "cli_same")
    monkeypatch.setattr("subprocess.run", FakeRun(version_output="hermes 0.22.2"))

    result = CliRunner().invoke(cli, ["start", "--prefix", "team"])

    assert result.exit_code != 0
    assert "already used by" in result.output


def test_start_rejects_app_id_duplicating_default_profile(
    tmp_hermes_home, fake_hermes_bin, monkeypatch
):
    """The host gateway also serves the default profile (~/.hermes/.env)."""
    _make_profile(tmp_hermes_home, "team-pm", "cli_host")
    (tmp_hermes_home / ".env").write_text("FEISHU_APP_ID=cli_host\nFEISHU_APP_SECRET=host\n")
    monkeypatch.setattr("subprocess.run", FakeRun(version_output="hermes 0.22.2"))

    result = CliRunner().invoke(cli, ["start", "--prefix", "team"])

    assert result.exit_code != 0
    assert "default profile" in result.output


def test_start_rejects_app_id_shared_across_teams(tmp_hermes_home, fake_hermes_bin, monkeypatch):
    """The host gateway serves every profile under profiles/ — other teams included."""
    _make_profile(tmp_hermes_home, "team-pm", "cli_same")
    _make_profile(tmp_hermes_home, "other-pm", "cli_same")
    monkeypatch.setattr("subprocess.run", FakeRun(version_output="hermes 0.22.2"))

    result = CliRunner().invoke(cli, ["start", "--prefix", "team"])

    assert result.exit_code != 0
    assert "already used by" in result.output
    assert "other-pm" in result.output


def test_start_ignores_parked_profile_sharing_app_id(tmp_hermes_home, fake_hermes_bin, monkeypatch):
    """A parked profile is skipped by the host (`hermes -p X gateway stop`) — no clash."""
    _make_profile(tmp_hermes_home, "team-pm", "cli_x")
    _make_profile(tmp_hermes_home, "other-pm", "cli_x")
    (tmp_hermes_home / "profiles" / "other-pm" / "gateway.parked").write_text("")
    monkeypatch.setattr("subprocess.run", FakeRun(version_output="hermes 0.22.2"))

    result = CliRunner().invoke(cli, ["start", "--prefix", "team"])

    assert result.exit_code == 0, result.output


def test_start_rejects_missing_credentials(tmp_hermes_home, fake_hermes_bin, monkeypatch):
    _make_profile(tmp_hermes_home, "team-pm", None)
    monkeypatch.setattr("subprocess.run", FakeRun(version_output="hermes 0.22.2"))

    result = CliRunner().invoke(cli, ["start", "--prefix", "team"])

    assert result.exit_code != 0
    assert "missing FEISHU_APP_ID" in result.output


def test_start_handles_non_executable_hermes_binary(tmp_hermes_home, fake_hermes_bin, monkeypatch):
    """A hermes path that exists but is not executable fails cleanly, no traceback."""
    _make_profile(tmp_hermes_home, "team-pm", "cli_aaa")

    def _denied(cmd, **kwargs):
        raise PermissionError(13, "Permission denied", cmd[0] if cmd else "")

    monkeypatch.setattr("subprocess.run", _denied)

    result = CliRunner().invoke(cli, ["start", "--prefix", "team"])

    assert result.exit_code != 0
    assert "Could not run Hermes binary" in result.output
    assert "Traceback" not in result.output


def test_start_standalone_also_validates_credentials(tmp_hermes_home, fake_hermes_bin, monkeypatch):
    """Legacy mode validates credentials too — failures are more obscure there."""
    _make_profile(tmp_hermes_home, "team-pm", "cli_dup")
    _make_profile(tmp_hermes_home, "team-fe", "cli_dup")
    monkeypatch.setattr("subprocess.run", FakeRun(version_output="hermes 0.18.2"))

    result = CliRunner().invoke(cli, ["start", "--prefix", "team", "--standalone"])

    assert result.exit_code != 0
    assert "already used by" in result.output


def test_start_on_old_hermes_falls_back_to_per_profile(
    tmp_hermes_home, fake_hermes_bin, monkeypatch
):
    _make_profile(tmp_hermes_home, "team-pm", "cli_aaa")
    fake = FakeRun(version_output="hermes 0.18.2")
    monkeypatch.setattr("subprocess.run", fake)
    monkeypatch.setattr(time, "sleep", lambda _s: None)

    result = CliRunner().invoke(cli, ["start", "--prefix", "team"])

    assert result.exit_code == 0, result.output
    assert "predates the multiplexed gateway" in result.output
    assert f"{fake_hermes_bin} --profile team-pm gateway install" in result.output
    assert f"{fake_hermes_bin} --profile team-pm gateway start" in result.output


def test_start_standalone_warns_on_multiplex_hermes(tmp_hermes_home, fake_hermes_bin, monkeypatch):
    _make_profile(tmp_hermes_home, "team-pm", "cli_aaa")
    monkeypatch.setattr("subprocess.run", FakeRun(version_output="hermes 0.22.2"))

    result = CliRunner().invoke(cli, ["start", "--prefix", "team", "--standalone", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "refuses per-profile gateways" in result.output
    assert "--profile team-pm" in result.output


def test_start_skips_ghost_directory_without_credentials(
    tmp_hermes_home, fake_hermes_bin, monkeypatch
):
    """A marker-less `profiles/team-ghost/logs` dir is not a profile — `start`
    must not fail it for missing credentials (the host never serves it)."""
    _make_profile(tmp_hermes_home, "team-pm", "cli_aaa")
    ghost_logs = tmp_hermes_home / "profiles" / "team-ghost" / "logs"
    ghost_logs.mkdir(parents=True)
    (ghost_logs / "gateway.log").write_text("2026-10-20 10:00:00 rotation\n")
    monkeypatch.setattr("subprocess.run", FakeRun(version_output="hermes 0.22.2"))

    result = CliRunner().invoke(cli, ["start", "--prefix", "team", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "team-ghost" not in result.output


def test_start_survives_unreadable_other_env(tmp_hermes_home, fake_hermes_bin, monkeypatch):
    """A broken-encoding .env in an unrelated profile must not crash the scan."""
    _make_profile(tmp_hermes_home, "team-pm", "cli_aaa")
    other = tmp_hermes_home / "profiles" / "other-pm"
    _make_profile(tmp_hermes_home, "other-pm", "cli_bbb")
    (other / ".env").write_bytes(b"FEISHU_APP_ID=\xff\xfe\x00bad")
    monkeypatch.setattr("subprocess.run", FakeRun(version_output="hermes 0.22.2"))

    result = CliRunner().invoke(cli, ["start", "--prefix", "team"])

    assert result.exit_code == 0, result.output


def test_start_warns_when_default_env_unreadable(tmp_hermes_home, fake_hermes_bin, monkeypatch):
    """A broken-encoding ~/.hermes/.env degrades to a warning, not a crash."""
    _make_profile(tmp_hermes_home, "team-pm", "cli_aaa")
    (tmp_hermes_home / ".env").write_bytes(b"FEISHU_APP_ID=\xff\xfe\x00bad")
    monkeypatch.setattr("subprocess.run", FakeRun(version_output="hermes 0.22.2"))

    result = CliRunner().invoke(cli, ["start", "--prefix", "team"])

    assert result.exit_code == 0, result.output
    assert "exists but is unreadable" in result.output
    assert "NOT included in the uniqueness scan" in result.output


def test_start_no_warning_for_readable_default_env_without_app_id(
    tmp_hermes_home, fake_hermes_bin, monkeypatch
):
    """A readable ~/.hermes/.env with no FEISHU_APP_ID (empty/comments/model
    keys) hides no duplicate — start must not tell the user to fix
    permissions on a file that is not broken (same verdict as verify)."""
    _make_profile(tmp_hermes_home, "team-pm", "cli_aaa")
    (tmp_hermes_home / ".env").write_text("# model only\nMODEL_API_KEY=sk\n")
    monkeypatch.setattr("subprocess.run", FakeRun(version_output="hermes 0.22.2"))

    result = CliRunner().invoke(cli, ["start", "--prefix", "team"])

    assert result.exit_code == 0, result.output
    assert "unreadable" not in result.output
    assert "Fix its permissions" not in result.output
