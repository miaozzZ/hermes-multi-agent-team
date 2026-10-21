"""Tests for the destroy command."""

from click.testing import CliRunner

from hermes_multi_agent_team.cli import cli


def test_destroy_no_profiles(tmp_hermes_home):
    """destroy with no matching profiles should show error."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["destroy", "--prefix", "nonexistent"],
    )
    assert result.exit_code != 0
    assert "No profiles" in result.output or "not found" in result.output.lower()


def test_destroy_requires_confirmation(tmp_hermes_home):
    """destroy without --force should ask for confirmation."""
    # Create a fake profile
    pdir = tmp_hermes_home / "profiles" / "test-pm"
    pdir.mkdir(parents=True)
    (pdir / "SOUL.md").write_text("test")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["destroy", "--prefix", "test"],
        input="n\n",  # Decline confirmation
    )
    # Should abort
    assert result.exit_code != 0 or "Aborted" in result.output


def test_destroy_with_force(tmp_hermes_home):
    """destroy --force should delete without asking."""
    # Create fake profiles
    for role in ["pm", "fe"]:
        pdir = tmp_hermes_home / "profiles" / f"test-{role}"
        pdir.mkdir(parents=True)
        (pdir / "SOUL.md").write_text("test")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["destroy", "--prefix", "test", "--force"],
    )
    assert result.exit_code == 0
    assert "Destroyed" in result.output or "Deleted" in result.output

    # Verify they're gone
    assert not (tmp_hermes_home / "profiles" / "test-pm").exists()
    assert not (tmp_hermes_home / "profiles" / "test-fe").exists()


def test_destroy_only_deletes_matching_prefix(tmp_hermes_home):
    """destroy should only delete profiles matching the prefix."""
    # Create matching and non-matching profiles
    for name in ["test-pm", "test-fe", "other-pm"]:
        pdir = tmp_hermes_home / "profiles" / name
        pdir.mkdir(parents=True)
        (pdir / "SOUL.md").write_text("test")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["destroy", "--prefix", "test", "--force"],
    )
    assert result.exit_code == 0

    # other-pm should still exist
    assert (tmp_hermes_home / "profiles" / "other-pm").exists()
    # test-pm and test-fe should be gone
    assert not (tmp_hermes_home / "profiles" / "test-pm").exists()
    assert not (tmp_hermes_home / "profiles" / "test-fe").exists()


def test_destroy_tombstones_deleted_profiles(tmp_hermes_home):
    """destroy must write the same profiles/.deleted/<name> tombstones
    remove-member's delete mode writes: a leftover (e.g. partially deleted)
    shell must never be listed or served again. Re-init clears them."""
    pdir = tmp_hermes_home / "profiles" / "test-pm"
    pdir.mkdir(parents=True)
    (pdir / "SOUL.md").write_text("test")

    result = CliRunner().invoke(cli, ["destroy", "--prefix", "test", "--force"])
    assert result.exit_code == 0, result.output
    assert (tmp_hermes_home / "profiles" / ".deleted" / "test-pm").is_dir()


def test_destroy_rmtree_failure_aborts_cleanly(tmp_hermes_home, monkeypatch):
    """A failed rmtree used to escape as a bare traceback. It must abort with
    a clean error instead (mirroring remove-member), keeping already-deleted
    profiles deleted and tombstoned."""
    real_rmtree = __import__("shutil").rmtree

    def _fake_rmtree(path, *args, **kwargs):
        if "test-qa" in str(path):  # fails mid-run (sorted after test-pm)
            raise OSError("permission denied")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr("hermes_multi_agent_team.commands.destroy.shutil.rmtree", _fake_rmtree)

    for role in ("pm", "qa"):
        pdir = tmp_hermes_home / "profiles" / f"test-{role}"
        pdir.mkdir(parents=True)
        (pdir / "SOUL.md").write_text("test")

    result = CliRunner().invoke(cli, ["destroy", "--prefix", "test", "--force"])

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "Failed to delete profile directory 'test-qa'" in result.output
    assert "partially destroyed" in result.output
    # The first profile stayed deleted and tombstoned.
    assert not (tmp_hermes_home / "profiles" / "test-pm").exists()
    assert (tmp_hermes_home / "profiles" / ".deleted" / "test-pm").is_dir()
