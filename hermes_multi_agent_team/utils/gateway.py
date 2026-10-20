"""Gateway helper functions for managing Feishu gateway processes."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path


def get_real_home() -> Path:
    """Return the real user home directory, even if HOME is overridden by Hermes.

    In a Hermes session, HOME may point to ~/.hermes/profiles/<name>/home.
    We need the actual user home (/Users/mac or /root etc).
    """
    # Try to detect the real home by looking at /etc/passwd or known paths
    real_home = os.environ.get("REAL_HOME")
    if real_home:
        return Path(real_home)

    # If HOME looks like a hermes profile home, go up to find real home
    home = Path.home()
    parts = home.parts
    if ".hermes" in parts:
        idx = list(parts).index(".hermes")
        return Path(*parts[:idx])

    return home


def find_hermes_bin() -> str:
    """Find the hermes CLI binary.

    Priority:
    1. 'hermes' in PATH (via shutil.which)
    2. ~/.hermes/hermes-agent/venv/bin/hermes
    3. $HERMES_HOME/hermes-agent/venv/bin/hermes (if set and different)
    """
    # Try PATH first
    which_result = shutil.which("hermes")
    if which_result:
        return which_result

    # Try real home
    real_home = get_real_home()
    candidate = real_home / ".hermes" / "hermes-agent" / "venv" / "bin" / "hermes"
    if candidate.exists():
        return str(candidate)

    # Try HERMES_HOME env
    hermes_home = os.environ.get("HERMES_HOME")
    if hermes_home:
        candidate = Path(hermes_home) / "hermes-agent" / "venv" / "bin" / "hermes"
        if candidate.exists():
            return str(candidate)

    # Return the most likely path as fallback
    return str(real_home / ".hermes" / "hermes-agent" / "venv" / "bin" / "hermes")


# A version number right after a "hermes"/"v" marker, e.g. "hermes, version 0.22.2"
# or "Hermes Agent v0.22.2 (2026.9.24)".
_VERSION_WITH_MARKER_RE = re.compile(
    r"(?:hermes[^0-9]{0,20}|(?<![a-z])v)[^\d]{0,16}(\d+)\.(\d+)\.(\d+)",
    re.IGNORECASE,
)
_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def get_hermes_version(hermes_bin: str | None = None) -> tuple[int, int, int] | None:
    """Return the Hermes CLI version as (major, minor, patch), or None if undeterminable."""
    binary = hermes_bin or find_hermes_bin()
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    # Prefer a version with a hermes/v marker in stdout so stray version-like
    # numbers elsewhere in the output (e.g. a Python banner) are not mistaken
    # for the CLI version; stderr is never searched.
    match = _VERSION_WITH_MARKER_RE.search(result.stdout) or _VERSION_RE.search(result.stdout)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _hermes_bin() -> str:
    """Return the path to the hermes CLI binary."""
    return find_hermes_bin()


def gateway_status(name: str) -> dict[str, str | int | None]:
    """Check gateway status for a profile.

    Returns a dict with keys:
      - pid: process ID or None if not running
      - connected: bool — whether 'feishu connected' appears in recent logs
      - last_message_time: str or None
    """
    from hermes_multi_agent_team.utils.profile import get_profile_dir

    log_path = get_profile_dir(name) / "logs" / "gateway.log"
    result: dict[str, str | int | None] = {
        "pid": None,
        "connected": False,
        "last_message_time": None,
    }

    # Find PID via pidfile or process list
    pid = _find_gateway_pid(name)
    result["pid"] = pid

    # Always read the profile log tail: it feeds last_message_time in every
    # mode (status' Last Active column), multiplex or not. Its connected lines
    # only matter when the host record has no state for this profile.
    tail = ""
    if log_path.exists():
        try:
            tail = _tail_file(log_path, lines=200)
        except OSError:
            tail = ""

    # Connection state: the live host record is authoritative when it has a
    # state for this profile — it reflects the CURRENT connection, while the
    # profile log keeps stale "[Feishu] Connected" lines after a disconnect or
    # retry. Only fall back to the log when there is no host state (a
    # standalone gateway, or no host record at all). Under the multiplexed
    # gateway the host prints "feishu connected (profile: X)" into ITS OWN log,
    # never the profile's — a profile log only ever carries the adapter's
    # "[Feishu] Connected" line.
    host_state = _host_platform_state(name)
    if host_state is not None:
        result["connected"] = host_state == "connected"
    else:
        lowered = tail.lower()
        if (
            "feishu connected" in lowered
            or "feishu: connected" in lowered
            or "[feishu] connected" in lowered
        ):
            result["connected"] = True

    if tail:
        ts_match = re.findall(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})", tail)
        if ts_match:
            result["last_message_time"] = ts_match[-1]

    # No findable gateway process → nothing is connected, whatever old logs say.
    if result["pid"] is None:
        result["connected"] = False

    return result


def _find_host_gateway_pid(name: str) -> int | None:
    """Return the host multiplex gateway's PID when it serves this profile.

    Since Hermes 0.19 a single host gateway serves every profile on the machine.
    A served profile owns no gateway.pid of its own — the host's runtime record
    lives in the Hermes home (gateway_state.json) and lists served profile names
    in ``served_profiles``.
    """
    record = _read_live_host_record()
    if record is None:
        return None
    served = record.get("served_profiles")
    if not isinstance(served, list) or name not in served:
        return None
    return record["pid"]


# Host runtime states Hermes itself treats as "not running" even though the
# record (and its old PID) still exists on disk. None counts too: a record
# without a state was never confirmed running (gateway_multiplex_mode.py and
# get_runtime_status_running_pid keep the same rule).
_HOST_GATEWAY_DOWN_STATES = (None, "stopped", "startup_failed")


def _read_live_host_record() -> dict | None:
    """Read the host gateway's runtime record when it belongs to a live process.

    Mirrors Hermes' own liveness rules: a record in an unknown or terminal state
    (``None``/``stopped``/``startup_failed``) is not running, and a recorded
    start time that conflicts with the live process's start time means the PID
    was recycled by an unrelated process — such a stale record's
    ``served_profiles`` must not be treated as authoritative.
    """
    from hermes_multi_agent_team.utils.profile import get_hermes_home

    try:
        record = json.loads((get_hermes_home() / "gateway_state.json").read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    if record.get("gateway_state") in _HOST_GATEWAY_DOWN_STATES:
        return None
    if record.get("kind") != "hermes-gateway":
        return None
    pid = record.get("pid")
    if not isinstance(pid, int):
        return None
    try:
        os.kill(pid, 0)  # liveness check
    except OSError:
        return None
    if _start_time_conflicts(record.get("start_time"), pid):
        return None
    return record


def _start_time_conflicts(recorded: object, pid: int) -> bool:
    """PID-reuse guard, mirroring Hermes: conflict only when BOTH times are known and differ."""
    if not isinstance(recorded, int):
        return False
    current = _process_start_time(pid)
    return current is not None and current != recorded


def _process_start_time(pid: int) -> int | None:
    """Linux /proc start time (clock ticks); None where /proc is unavailable."""
    try:
        return int(Path(f"/proc/{pid}/stat").read_text().split()[21])
    except (OSError, IndexError, ValueError):
        return None


def _host_platform_state(name: str) -> str | None:
    """Platform state the live host gateway recorded for this profile's Feishu, if any.

    The multiplexed host stamps per-profile platform status into the default
    home's gateway_state.json under ``<profile>:<platform>`` keys; the launch
    profile (usually ``default``) uses the bare platform name.
    """
    record = _read_live_host_record()
    if record is None:
        return None
    served = record.get("served_profiles")
    if not isinstance(served, list) or name not in served:
        return None
    platforms = record.get("platforms")
    if not isinstance(platforms, dict):
        return None
    entry = platforms.get("feishu" if name == "default" else f"{name}:feishu")
    if isinstance(entry, dict) and isinstance(entry.get("state"), str):
        return entry["state"]
    return None


def _find_gateway_pid(name: str) -> int | None:
    """Try to find the running gateway PID for a profile."""
    from hermes_multi_agent_team.utils.profile import get_profile_dir

    pid_path = get_profile_dir(name) / "gateway.pid"
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text().strip())
            # Check if process is alive
            os.kill(pid, 0)
            return pid
        except (ValueError, OSError, ProcessLookupError):
            pass

    # Fallback: look in process list
    try:
        out = subprocess.run(
            ["pgrep", "-f", f"hermes.*--profile.*{name}.*gateway"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return int(out.stdout.strip().split("\n")[0])
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
        pass

    # Last resort: the host multiplex gateway may be serving this profile
    # (served profiles have no gateway.pid and no per-profile process).
    return _find_host_gateway_pid(name)


def gateway_restart(name: str, dry_run: bool = False) -> bool:
    """Restart the gateway for a profile. Returns True on success."""
    hermes = _hermes_bin()
    cmds = [
        [hermes, "--profile", name, "gateway", "stop"],
        [hermes, "--profile", name, "gateway", "install"],
        [hermes, "--profile", name, "gateway", "start"],
    ]
    for cmd in cmds:
        if dry_run:
            print(f"  💨 dry-run: {' '.join(cmd)}")
            continue
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
            if r.returncode != 0:
                return False
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    return True


def get_gateway_log(name: str, tail_lines: int = 500) -> str:
    """Read the tail of the gateway log for a profile."""
    from hermes_multi_agent_team.utils.profile import get_profile_dir

    log_path = get_profile_dir(name) / "logs" / "gateway.log"
    return _tail_file(log_path, lines=tail_lines)


def _tail_file(path: Path, lines: int = 200) -> str:
    """Efficiently read the last N lines of a file."""
    if not path.exists():
        return ""
    try:
        with open(path, "rb") as f:
            # Seek to end and read backwards
            f.seek(0, 2)
            size = f.tell()
            block_size = min(size, 8192 * lines)
            f.seek(max(0, size - block_size))
            data = f.read().decode("utf-8", errors="replace")
            all_lines = data.splitlines()
            return "\n".join(all_lines[-lines:])
    except OSError:
        return ""
