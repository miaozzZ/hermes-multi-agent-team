"""Tests for the configure command."""

import sys
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from hermes_multi_agent_team.cli import cli
from hermes_multi_agent_team.commands import configure
from hermes_multi_agent_team.commands.configure import _masked_key_loop


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


def test_configure_tightens_loose_env_permissions(tmp_hermes_home):
    """A pre-existing 0644 .env carrying the App Secret must not stay
    group/world-readable after a reconfigure — write_env tightens it to 0600
    and configure says so."""
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        "FEISHU_APP_ID=cli_old\nFEISHU_APP_SECRET=old\nMODEL_API_KEY=sk-keepme\n",
    )
    env_path = tmp_hermes_home / "profiles" / "team-pm" / ".env"
    env_path.chmod(0o644)

    result = CliRunner().invoke(
        cli,
        ["configure", "--prefix", "team"],
        input=_SHARED_SETTINGS_INPUT + _PROFILE_INPUT_DEFAULTS,
    )
    assert result.exit_code == 0, result.output

    assert env_path.stat().st_mode & 0o777 == 0o600
    assert "Tightened" in result.output
    assert "0600" in result.output
    # The tool-managed rewrite itself is unchanged.
    assert "MODEL_API_KEY=sk-keepme" in env_path.read_text()


def test_configure_reports_env_write_failure_cleanly(tmp_hermes_home, monkeypatch):
    """An OSError from the final .env write (unwritable file, full disk…)
    used to escape as a bare traceback after every prompt was answered —
    surface it as a clean error naming the profile."""
    _make_profile(tmp_hermes_home, "team-pm", "FEISHU_APP_ID=cli_old\nFEISHU_APP_SECRET=old\n")

    def _boom(profile_name, env_vars):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr("hermes_multi_agent_team.commands.configure.write_env", _boom)

    result = CliRunner().invoke(
        cli,
        ["configure", "--prefix", "team"],
        input=_SHARED_SETTINGS_INPUT + _PROFILE_INPUT_DEFAULTS,
    )
    assert result.exit_code != 0
    assert "Could not write team-pm/.env" in result.output
    assert "Traceback" not in result.output


def test_configure_strips_surrounding_whitespace_from_credentials(tmp_hermes_home):
    """Copy-pasted App ID/Secret with surrounding whitespace is stripped.

    Unstripped values would bypass the duplicate check and never match at
    connect time.
    """
    _make_profile(tmp_hermes_home, "team-pm", "")

    # Inputs carry leading/trailing spaces (and a full-width space U+3000 on
    # the secret — .strip() handles unicode whitespace).
    result = CliRunner().invoke(
        cli,
        ["configure", "--prefix", "team"],
        input=_SHARED_SETTINGS_INPUT + "  cli_aaa  \n\u3000secret1\u3000\n" + "\n",
    )
    assert result.exit_code == 0, result.output
    env = (tmp_hermes_home / "profiles" / "team-pm" / ".env").read_text()
    # Line-exact match: a substring match would pass even if the secret were
    # stored with its trailing whitespace unstripped.
    assert "FEISHU_APP_ID=cli_aaa" in env.splitlines()
    assert "FEISHU_APP_SECRET=secret1" in env.splitlines()


def test_configure_whitespace_duplicate_app_id_detected(tmp_hermes_home):
    """The duplicate check runs on the stripped value: '  cli_dup ' collides
    with a previously entered 'cli_dup' instead of slipping through."""
    _make_profile(tmp_hermes_home, "team-pm", "")
    _make_profile(tmp_hermes_home, "team-qa", "")

    # team-pm gets cli_dup; team-qa tries "  cli_dup " (rejected), then
    # cli_other. Each profile also answers its ALLOWED_USERS prompt.
    user_input = _SHARED_SETTINGS_INPUT + "cli_dup\nsec1\n\n" + "  cli_dup \ncli_other\nsec2\n\n"
    result = CliRunner().invoke(cli, ["configure", "--prefix", "team"], input=user_input)
    assert result.exit_code == 0, result.output
    assert "already used by" in result.output
    qa_env = (tmp_hermes_home / "profiles" / "team-qa" / ".env").read_text()
    assert "FEISHU_APP_ID=cli_other" in qa_env


def test_configure_bare_enter_keeps_existing_secret(tmp_hermes_home):
    """Re-running configure and pressing Enter keeps the existing secret."""
    _make_profile(tmp_hermes_home, "team-pm", "FEISHU_APP_ID=cli_old\nFEISHU_APP_SECRET=old_sec\n")

    # App ID keeps its shown default; the secret prompt gets a bare Enter.
    result = CliRunner().invoke(
        cli,
        ["configure", "--prefix", "team"],
        input=_SHARED_SETTINGS_INPUT + "\n" + "\n" + "\n",
    )
    assert result.exit_code == 0, result.output
    env = (tmp_hermes_home / "profiles" / "team-pm" / ".env").read_text()
    assert "FEISHU_APP_SECRET=old_sec" in env


class _ScriptedReader:
    """Feeds a fixed keystroke script to _masked_key_loop, one char per call.

    The script must end with Enter (\\r or \\n); once exhausted, reads raise so
    a loop bug that over-consumes or misses the terminator fails the test fast
    instead of hanging it.
    """

    def __init__(self, keys: str):
        self._keys = list(keys)
        self.echoed: list[str] = []

    def read(self) -> str:
        if not self._keys:
            raise AssertionError("reader script exhausted — over-consumed or missing Enter")
        return self._keys.pop(0)

    def echo(self, text: str) -> None:
        self.echoed.append(text)


def test_masked_key_loop_types_characters_and_echoes_stars():
    reader = _ScriptedReader("abc\r")
    assert _masked_key_loop(reader.read, reader.echo) == "abc"
    assert reader.echoed == ["*", "*", "*"]


def test_masked_key_loop_backspace_erases_del_and_ctrl_h():
    """Both DEL (\\x7f) and Ctrl-H (\\x08, terminals with erase=^H) erase."""
    reader = _ScriptedReader("ab\x7fc\x08\r")
    assert _masked_key_loop(reader.read, reader.echo) == "a"
    assert reader.echoed.count("\b \b") == 2


def test_masked_key_loop_swallows_csi_sequences():
    """Up-arrow/Left/Home/Ctrl+Right (CSI) must vanish, not append '[A'/'[H'."""
    reader = _ScriptedReader("x\x1b[Ay\x1b[D\x1b[H\x1b[1;5Cz\r")
    assert _masked_key_loop(reader.read, reader.echo) == "xyz"
    assert reader.echoed == ["*", "*", "*"]


def test_masked_key_loop_swallows_ss3_sequences():
    reader = _ScriptedReader("\x1bOAq\r")
    assert _masked_key_loop(reader.read, reader.echo) == "q"


def test_masked_key_loop_lone_esc_keeps_next_character():
    """A lone ESC (or Alt+key) drops only the ESC; Enter still terminates."""
    reader = _ScriptedReader("a\x1bb\x1b\r")
    assert _masked_key_loop(reader.read, reader.echo) == "ab"


def test_masked_key_loop_drops_other_control_characters():
    reader = _ScriptedReader("a\x01\x02b\r")
    assert _masked_key_loop(reader.read, reader.echo) == "ab"


def test_masked_key_loop_reader_eof_raises():
    """A reader returning '' (stdin closed mid-line) must fail loudly, not hang."""
    with pytest.raises(EOFError):
        _masked_key_loop(lambda: "", lambda _text: None)


def test_masked_key_loop_incomplete_sequence_terminated_by_enter():
    """ESC+'['/'O' directly followed by Enter: the Enter must end the line
    instead of being consumed by the never-terminating sequence."""
    reader = _ScriptedReader("ab\x1b[\r")
    assert _masked_key_loop(reader.read, reader.echo) == "ab"
    reader = _ScriptedReader("a\x1bO\r")
    assert _masked_key_loop(reader.read, reader.echo) == "a"


def test_masked_key_loop_nested_escape_restarts_sequence():
    """An ESC inside an unterminated sequence ends it; the next ESC starts a
    fresh one, so a following arrow key still vanishes entirely."""
    reader = _ScriptedReader("a\x1b[\x1b[Az\r")
    assert _masked_key_loop(reader.read, reader.echo) == "az"


def test_masked_key_loop_sequence_length_capped():
    """16 parameter-range bytes with no final byte: the sequence is dropped
    instead of eating what follows; only bytes beyond the cap survive."""
    reader = _ScriptedReader("a\x1b[" + "1;" * 8 + "\r")  # exactly 16 bytes
    assert _masked_key_loop(reader.read, reader.echo) == "a"
    reader = _ScriptedReader("a\x1b[" + "1;" * 8 + "z\r")  # 17th byte survives
    assert _masked_key_loop(reader.read, reader.echo) == "az"


def test_masked_key_loop_win32_semantics():
    """msvcrt-style: \\x00/\\xe0 prefixes consume the second code; Ctrl-C aborts."""
    reader = _ScriptedReader("a\xe0Kb\r")
    assert (
        _masked_key_loop(
            reader.read,
            reader.echo,
            extended_prefixes=("\x00", "\xe0"),
            backspace=("\x08",),
            ctrl_c_abort=True,
        )
        == "ab"
    )
    aborting = _ScriptedReader("\x03")
    with pytest.raises(click.Abort):
        _masked_key_loop(
            aborting.read,
            aborting.echo,
            extended_prefixes=("\x00", "\xe0"),
            backspace=("\x08",),
            ctrl_c_abort=True,
        )


class _FakeTtyStdin:
    """Stands in for sys.stdin on a real terminal (isatty → True)."""

    def isatty(self) -> bool:
        return True


def test_prompt_app_secret_bare_enter_on_tty_keeps_existing(monkeypatch):
    """The TTY path's own `if not value and default: return default` branch.

    CliRunner takes the non-TTY fallback, where click.prompt already resolves
    the default — so this branch needs the masked-line path to be exercised.
    """
    monkeypatch.setattr(sys, "stdin", _FakeTtyStdin())
    monkeypatch.setattr(configure, "_read_masked_line", lambda: "")
    assert configure._prompt_app_secret("team-pm", {"FEISHU_APP_SECRET": "old_sec"}) == "old_sec"


def test_prompt_app_secret_on_tty_strips_surrounding_whitespace(monkeypatch):
    monkeypatch.setattr(sys, "stdin", _FakeTtyStdin())
    monkeypatch.setattr(configure, "_read_masked_line", lambda: "  new_sec\u3000")
    assert configure._prompt_app_secret("team-pm", {"FEISHU_APP_SECRET": "old_sec"}) == "new_sec"


def _run_masked_read_on_pty(tmp_path: Path, keys: bytes, *, pre_cbreak: bool = True) -> str:
    """Drive _read_masked_line in a child process whose stdio is a real pty.

    With ``pre_cbreak=True`` (default) the child switches its tty to cbreak and
    prints READY before the parent sends ``keys``, so the line discipline
    cannot interpret them first (canonical-mode ERASE would eat the \x7f/\x08
    we are testing). With ``pre_cbreak=False`` the child leaves the tty in its
    default canonical mode — configure's own setcbreak/restore inside
    _read_masked_line are then the code under test: the parent waits, via the
    pty pair's shared termios (no timing guess), until ECHO is off (setcbreak
    has taken effect) before sending ``keys``. Returns everything the child
    printed, including 'RESTORED:<bool>' and 'RESULT:<line>' markers.
    """
    import os
    import pty
    import select
    import subprocess
    import termios
    import time

    driver = tmp_path / "_pty_driver.py"
    driver.write_text(
        "import sys, termios\n"
        "fd = sys.stdin.fileno()\n"
        + ("import tty\ntty.setcbreak(fd)\n" if pre_cbreak else "")
        + "before = termios.tcgetattr(fd)\n"
        "sys.stdout.write('READY\\r\\n'); sys.stdout.flush()\n"
        "from hermes_multi_agent_team.commands.configure import _read_masked_line\n"
        "line = _read_masked_line()\n"
        "print()\n"
        "print('RESTORED:%s' % (termios.tcgetattr(fd) == before))\n"
        "print('RESULT:' + line)\n",
    )
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [sys.executable, str(driver)],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        cwd=Path(__file__).resolve().parents[1],
    )
    os.close(slave)
    output = b""

    def _read_more(timeout: float) -> bytes:
        ready, _, _ = select.select([master], [], [], timeout)
        if not ready:
            return b""
        try:
            return os.read(master, 4096)
        except OSError:  # EIO once the child exits and the pty closes
            return b""

    try:
        deadline = time.monotonic() + 15
        while b"READY" not in output and proc.poll() is None and time.monotonic() < deadline:
            output += _read_more(1)
        assert b"READY" in output, output.decode("utf-8", errors="replace")
        if not pre_cbreak:
            # ECHO visible from the master fd == the child's setcbreak (inside
            # _read_masked_line) has taken effect; sending keys earlier could
            # let the canonical line discipline echo/interpret them.
            while (
                termios.tcgetattr(master)[3] & termios.ECHO
                and proc.poll() is None
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            assert not termios.tcgetattr(master)[3] & termios.ECHO, (
                "ECHO stayed on — configure's setcbreak was not applied"
            )
        os.write(master, keys)
        while proc.poll() is None and time.monotonic() < deadline:
            output += _read_more(1)
        while True:  # drain whatever is still buffered
            chunk = _read_more(0.5)
            if not chunk:
                break
            output += chunk
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
        os.close(master)
    return output.decode("utf-8", errors="replace")


@pytest.mark.skipif(sys.platform == "win32", reason="pty test is POSIX-only")
def test_read_masked_line_on_pty_ignores_arrow_keys(tmp_path):
    """Regression: 'abc' + LEFT + 'd' + Enter must yield 'abcd', not 'abc[Dd'.

    Found by driving the real TTY path through a pty — the bug is invisible
    to CliRunner, whose non-TTY fallback never reaches _read_masked_line.
    """
    out = _run_masked_read_on_pty(tmp_path, b"abc\x1b[Dd\r")
    assert "RESULT:abcd" in out
    assert "[D" not in out
    assert out.count("*") == 4


@pytest.mark.skipif(sys.platform == "win32", reason="pty test is POSIX-only")
def test_read_masked_line_on_pty_backspace_and_home(tmp_path):
    """DEL and Ctrl-H both erase on a real TTY; Home (\x1b[H) is swallowed."""
    out = _run_masked_read_on_pty(tmp_path, b"ab\x08c\x1b[H\x7fd\r")
    assert "RESULT:ad" in out
    assert "\b \b" in out
    assert "[H" not in out


@pytest.mark.skipif(sys.platform == "win32", reason="pty test is POSIX-only")
def test_read_masked_line_on_pty_manages_terminal_state(tmp_path):
    """configure's own setcbreak/restore are load-bearing.

    Unlike the other pty cases this driver does NOT pre-set cbreak: ECHO must
    be off while reading (the secret appears only as '*' echoes, never as
    plaintext), and the tty must be restored to its pre-call state afterwards.
    Plain characters only — no \x7f/\x08/ESC — since the canonical line
    discipline is in charge until setcbreak runs.
    """
    out = _run_masked_read_on_pty(tmp_path, b"s3cret\r", pre_cbreak=False)
    assert "RESULT:s3cret" in out
    # Exactly one occurrence (the RESULT marker): had ECHO stayed on, the
    # line discipline would have echoed the typed plaintext as well.
    assert out.count("s3cret") == 1
    assert "RESTORED:True" in out
    assert out.count("*") == 6
