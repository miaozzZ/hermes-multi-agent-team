"""Tests for the doctor command (deterministic — checks are mocked per scenario)."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from hermes_multi_agent_team.cli import cli


def _fake_hermes_binary(tmp_hermes_home, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point find_hermes_bin at a binary that actually exists in the temp home."""
    binary = tmp_hermes_home / "bin" / "hermes"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setattr(
        "hermes_multi_agent_team.utils.gateway.find_hermes_bin", lambda: str(binary)
    )


def _all_checks_pass(tmp_hermes_home, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every doctor check succeed regardless of the host machine."""
    _fake_hermes_binary(tmp_hermes_home, monkeypatch)
    monkeypatch.setattr(
        "hermes_multi_agent_team.utils.gateway.get_hermes_version", lambda _bin=None: (0, 22, 2)
    )
    # tmp_hermes_home fixture provides HERMES_HOME with a profiles/ dir.


def test_doctor_exits_zero_when_all_checks_pass(tmp_hermes_home, monkeypatch):
    _all_checks_pass(tmp_hermes_home, monkeypatch)
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "All" in result.output


def test_doctor_exits_nonzero_when_a_check_fails(tmp_hermes_home, monkeypatch):
    """Scripts and CI must be able to detect a failing environment via exit code."""
    _all_checks_pass(tmp_hermes_home, monkeypatch)
    monkeypatch.setattr(
        "hermes_multi_agent_team.utils.gateway.get_hermes_version", lambda _bin=None: None
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    assert result.exit_code != 0
    assert "Hermes version" in result.output


def test_doctor_hermes_cli_uses_same_lookup_as_version_check(tmp_hermes_home, monkeypatch):
    """Hermes only in the venv fallback (not on PATH): both Hermes checks must agree.

    Previously the CLI check used shutil.which alone and reported ❌ while the
    version check (find_hermes_bin) reported ✅ — a working install was shown
    as broken.
    """
    binary = tmp_hermes_home / "venv" / "bin" / "hermes"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setattr("shutil.which", lambda name: None)  # nothing on PATH
    monkeypatch.setattr(
        "hermes_multi_agent_team.utils.gateway.find_hermes_bin", lambda: str(binary)
    )
    monkeypatch.setattr(
        "hermes_multi_agent_team.utils.gateway.get_hermes_version", lambda _bin=None: (0, 22, 2)
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "Hermes CLI" in result.output
    assert "Hermes version" in result.output


def test_doctor_shows_python_check(tmp_hermes_home, monkeypatch):
    """doctor should check Python version."""
    _all_checks_pass(tmp_hermes_home, monkeypatch)
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    assert "Python" in result.output or "python" in result.output


def test_doctor_shows_hermes_version_check(tmp_hermes_home, monkeypatch):
    """doctor should check the Hermes version (multiplexed gateway needs >= 0.19)."""
    _all_checks_pass(tmp_hermes_home, monkeypatch)
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    assert "Hermes version" in result.output


def test_doctor_flags_old_hermes_version(tmp_hermes_home, monkeypatch):
    """Hermes < 0.19 fails the version check with an update hint."""
    _all_checks_pass(tmp_hermes_home, monkeypatch)
    monkeypatch.setattr(
        "hermes_multi_agent_team.utils.gateway.get_hermes_version", lambda _bin=None: (0, 18, 2)
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    assert result.exit_code != 0
    assert "hermes update" in result.output
