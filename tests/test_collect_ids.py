"""Tests for collect-ids: per-profile namespace-correct id collection.

Semantics under test (the core invariant): an open_id is only valid in the
app that observed it, so profile P's SOUL is filled ONLY from P's own
sources — [Mentioned:] entries in P's inbound log (mention-gated mode),
P's own sender=bot line (free mode), or the group history API called with
P's credentials (--via-api). No global merge.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
from click.testing import CliRunner

from hermes_multi_agent_team.cli import cli
from hermes_multi_agent_team.commands.collect_ids import collect_team_ids
from hermes_multi_agent_team.utils.open_id import (
    extract_mention_ids,
    fill_soul_placeholder_open_ids,
)

CHAT = "oc_ff4a50316c4567f893f0cba23194d360"


def _make_profile(
    home: Path,
    name: str,
    *,
    metadata: dict | None,
    log_lines: list[str],
    soul_entries: list[tuple[str, str]],
) -> None:
    """soul_entries: (display name, open_id) — use 'ou_xxx…' for placeholders."""
    profile = home / "profiles" / name
    (profile / "logs").mkdir(parents=True)
    (profile / "logs" / "gateway.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    if metadata is not None:
        (profile / ".hermes-team.json").write_text(
            json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
        )
    at_lines = "\n".join(f'- @{n}：`<at user_id="{oid}">{n}</at>`' for n, oid in soul_entries)
    (profile / "SOUL.md").write_text(f"【飞书@方式】\n{at_lines}\n", encoding="utf-8")


def _inbound(mentioned: list[tuple[str, str]], sender: str = "user:ou_owner1") -> str:
    """A real-format inbound adapter line: first entry sits right after
    "text='[Mentioned: " and the list ends ", ". Names are rendered verbatim —
    callers pass the FULL agent name (parentheses suffixes are part of the
    name, per-project)."""
    entries = "".join(f"{n} (open_id={i}), " for n, i in mentioned)
    return (
        "2026-10-22 00:37:20 INFO adapter: [Feishu] Inbound group message received: "
        f"id=om_x1 type=text chat_id={CHAT} sender={sender} "
        f"text='[Mentioned: {entries}]\\n\\n正文' media=0"
    )


def _legacy_sender_bot(bot_id: str, name: str) -> str:
    return f"2026-10-20 10:00:00 msg sender=bot:{bot_id} name={name}"


# --- mention-line parsing unit tests (the five verified pitfalls) ---


def test_extract_mention_ids_handles_real_log_pitfalls():
    # Only full adapter inbound lines ("… Inbound … received: …") carry
    # mention metadata — every case below uses the real line shape.
    head = (
        "2026-10-22 00:37:20 INFO adapter: [Feishu] Inbound group message received: "
        f"id=om_x1 type=text chat_id={CHAT} sender=user:ou_o "
    )
    text = "\n".join(
        [
            # First entry right after the prefix; parenthesized suffixes are
            # part of the agent NAME (per-project naming) and stay verbatim.
            _inbound([("U酱(sc)", "ou_u1"), ("O哥(sc)", "ou_o1")]),
            # @all entries carry no open_id.
            head + "text='[Mentioned: @all]\\n\\n@all hi' media=0",
            # Truncated mid-id last entry must not match.
            head + "text='[Mentioned: P酱(sc) (open_id=ou_064c2d",
            # Names without any suffix parse the same way.
            head + "text='[Mentioned: 阿写 (open_id=ou_a1)]'",
        ]
    )
    assert extract_mention_ids(text) == {
        "U酱(sc)": "ou_u1",
        "O哥(sc)": "ou_o1",
        "阿写": "ou_a1",
    }


def test_fill_placeholders_is_idempotent(tmp_path: Path):
    soul = tmp_path / "SOUL.md"
    soul.write_text(
        "【飞书@方式】\n"
        '- @P酱：`<at user_id="ou_manua1rea1">P酱</at>`\n'  # hand-filled
        '- @Q宝：`<at user_id="ou_xxx_qa">Q宝</at>`\n',
        encoding="utf-8",
    )
    mapping = {
        "P酱": "ou_log_says_different",  # must NOT overwrite the manual id
        "Q宝": "ou_real_qa",
    }
    assert fill_soul_placeholder_open_ids(soul, mapping) == (1, 0, {"Q宝"})
    content = soul.read_text()
    assert 'user_id="ou_manua1rea1">P酱' in content
    assert 'user_id="ou_real_qa">Q宝' in content
    # Second run: nothing left to fill, nothing rewritten.
    assert fill_soul_placeholder_open_ids(soul, mapping) == (0, 0, set())
    assert soul.read_text() == content


def test_fill_preserves_file_mode(tmp_path: Path):
    """The atomic replace swaps the inode, so the temp file must inherit the
    original's permission bits — a 0600 SOUL used to silently become the
    umask default (0664, group/other-readable)."""
    soul = tmp_path / "SOUL.md"
    soul.write_text(
        '【飞书@方式】\n- @P酱：`<at user_id="ou_xxx_pm">P酱</at>`\n',
        encoding="utf-8",
    )
    os.chmod(soul, 0o600)
    fill_soul_placeholder_open_ids(soul, {"P酱": "ou_modekeep1"})
    assert 'user_id="ou_modekeep1">P酱' in soul.read_text(encoding="utf-8")
    assert stat.S_IMODE(os.stat(soul).st_mode) == 0o600


def test_fill_refuses_to_replace_symlink(tmp_path: Path):
    """Replacing a symlink with os.replace would turn the link into a plain
    file while the TARGET kept its stale placeholders — refuse instead,
    leaving both (and the link itself) untouched."""
    target = tmp_path / "real.md"
    target.write_text(
        '【飞书@方式】\n- @P酱：`<at user_id="ou_xxx_pm">P酱</at>`\n',
        encoding="utf-8",
    )
    link = tmp_path / "SOUL.md"
    link.symlink_to(target)

    with pytest.raises(OSError, match="symlink"):
        fill_soul_placeholder_open_ids(link, {"P酱": "ou_shouldNEV3R"})

    assert link.is_symlink()  # link itself untouched
    assert 'user_id="ou_xxx_pm">P酱' in target.read_text(encoding="utf-8")  # target untouched
    assert not (tmp_path / "SOUL.md.tmp").exists()  # no temp leftover


# --- log-mode collection (mention-gated + free-mode sender fallback) ---


def test_mention_mode_fills_only_from_own_log_namespace(tmp_hermes_home: Path):
    """Each profile's SOUL gets ids its OWN app observed — the same teammate
    has different ids in the two namespaces, and they must not cross."""
    _make_profile(
        tmp_hermes_home,
        "team-writer",
        metadata={"key": "writer", "name": "阿写", "coordinator": False},
        log_lines=[
            _inbound([("老板", "ou_b0ss1nwrt00")], sender="user:ou_0wnerwa001"),
        ],
        soul_entries=[
            ("阿写", "ou_xxx_writer"),
            ("老板", "ou_xxx_coordinator"),
            ("主人", "ou_xxx_owner"),
        ],
    )
    _make_profile(
        tmp_hermes_home,
        "team-boss",
        metadata={"key": "boss", "name": "老板", "coordinator": True},
        log_lines=[
            _inbound([("阿写", "ou_wrt1nb0ss00")], sender="user:ou_0wnerwb002"),
        ],
        soul_entries=[
            ("老板", "ou_xxx_coordinator"),
            ("阿写", "ou_xxx_writer"),
            ("主人", "ou_xxx_owner"),
        ],
    )

    result = CliRunner().invoke(cli, ["collect-ids", "--prefix", "team"])
    assert result.exit_code == 0, result.output

    writer_soul = (tmp_hermes_home / "profiles" / "team-writer" / "SOUL.md").read_text()
    assert 'user_id="ou_b0ss1nwrt00">老板' in writer_soul
    assert 'user_id="ou_0wnerwa001">主人' in writer_soul  # owner from own log sender
    assert 'user_id="ou_xxx_writer">阿写' in writer_soul  # own line untouched by logs

    boss_soul = (tmp_hermes_home / "profiles" / "team-boss" / "SOUL.md").read_text()
    assert 'user_id="ou_wrt1nb0ss00">阿写' in boss_soul
    assert 'user_id="ou_0wnerwb002">主人' in boss_soul

    # Namespace isolation: writer's id never appears in boss's SOUL (and vice versa).
    assert "ou_b0ss1nwrt00" not in boss_soul
    assert "ou_wrt1nb0ss00" not in writer_soul
    # Honest per-profile reporting.
    assert "sources: mention=1, log=1" in result.output


def test_free_mode_sender_bot_fills_own_line_only(tmp_hermes_home: Path):
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[_legacy_sender_bot("ou_botpm", "P酱")],
        soul_entries=[("P酱", "ou_xxx_pm"), ("F仔", "ou_xxx_fe")],
    )

    result = CliRunner().invoke(cli, ["collect-ids", "--prefix", "team"])
    assert result.exit_code == 0, result.output
    pm_soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_botpm">P酱' in pm_soul  # own line, own namespace
    assert 'user_id="ou_xxx_fe">F仔' in pm_soul  # teammate unknown to this log
    assert "1 placeholder(s) remain" in result.output


def test_legacy_team_without_metadata(tmp_hermes_home: Path):
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata=None,  # team created before metadata existed
        log_lines=[_legacy_sender_bot("ou_botpm", "P酱")],
        soul_entries=[("P酱", "ou_xxx_pm")],
    )
    result = CliRunner().invoke(cli, ["collect-ids", "--prefix", "team"])
    assert result.exit_code == 0, result.output
    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_botpm">P酱' in soul


def test_skips_profiles_removed_from_team(tmp_hermes_home: Path):
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[_inbound([("F仔", "ou_fe1npmns00")])],
        soul_entries=[("P酱", "ou_xxx_pm"), ("F仔", "ou_xxx_fe")],
    )
    _make_profile(
        tmp_hermes_home,
        "team-fe",
        metadata={"key": "fe", "name": "F仔", "coordinator": False, "removed": True},
        log_lines=[_inbound([("P酱", "ou_pm1nfens0")])],
        soul_entries=[("P酱", "ou_xxx_pm"), ("F仔", "ou_xxx_fe")],
    )

    result = CliRunner().invoke(cli, ["collect-ids", "--prefix", "team"])
    assert result.exit_code == 0, result.output
    assert "team-fe" not in result.output  # skipped entirely
    pm_soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_fe1npmns00">F仔' in pm_soul
    fe_soul = (tmp_hermes_home / "profiles" / "team-fe" / "SOUL.md").read_text()
    assert 'user_id="ou_xxx_fe">F仔' in fe_soul  # untouched


def test_skips_roster_free_bot_template_members(tmp_hermes_home: Path):
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[_inbound([("阿写", "ou_wrt1npmns0")])],
        soul_entries=[("P酱", "ou_xxx_pm"), ("阿写", "ou_xxx_writer")],
    )
    _make_profile(
        tmp_hermes_home,
        "team-writer",
        metadata={
            "key": "writer",
            "name": "阿写",
            "coordinator": False,
            "template": "bot.md.j2",
        },
        log_lines=[],
        soul_entries=[],  # roster-free SOUL written manually below
    )
    (tmp_hermes_home / "profiles" / "team-writer" / "SOUL.md").write_text(
        "你是阿写，一个内容创作。\n", encoding="utf-8"
    )

    result = CliRunner().invoke(cli, ["collect-ids", "--prefix", "team"])
    assert result.exit_code == 0, result.output
    assert "roster-free bot template" in result.output
    pm_soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_wrt1npmns0">阿写' in pm_soul


# --- --via-api mode (injectable transport, no network) ---


def _api_env(home: Path, profile: str, app_id: str) -> None:
    env = home / "profiles" / profile / ".env"
    env.write_text(f"FEISHU_APP_ID={app_id}\nFEISHU_APP_SECRET=sec-{app_id}\n", encoding="utf-8")


def _api_transport(pages: dict[str, list[dict]], owner: str | None = "ou_0wnerap1"):
    """token per app_id; history pages per chat; chats info owner."""

    def transport(method, url, headers, body):
        if url.endswith("/tenant_access_token/internal"):
            app_id = (body or {}).get("app_id", "")
            return 200, {"code": 0, "tenant_access_token": f"tok-{app_id}"}
        if "/im/v1/messages" in url:
            page_key = url.split("page_token=")[1] if "page_token=" in url else "p1"
            items = pages.get(page_key, [])
            body_out = {"code": 0, "data": {"items": items, "has_more": len(pages) > 1}}
            # crude paging: first call → page1 + token p2; second → page2
            if "page_token=" not in url and len(pages) > 1:
                body_out["data"]["page_token"] = "p2"
            return 200, body_out
        if "/im/v1/chats/" in url:
            return 200, {"code": 0, "data": {"owner_id": owner}}
        return 404, {"code": 404, "msg": f"unexpected url {url}"}

    return transport


def test_via_api_fills_from_group_history_per_profile(tmp_hermes_home: Path):
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[],  # API mode works with zero log data
        soul_entries=[("P酱", "ou_xxx_pm"), ("F仔", "ou_xxx_fe"), ("主人", "ou_xxx_owner")],
    )
    _api_env(tmp_hermes_home, "team-pm", "cli_pm")

    pages = {
        "p1": [
            {"sender": {"id": "ou_x"}, "mentions": [{"name": "F仔", "id": "ou_feviaap1"}]},
            {"sender": {"id": "ou_y"}, "mentions": [{"name": "P酱", "id": "ou_pmviaap1"}]},
        ]
    }
    collect_team_ids(prefix="team", via_api=True, chat_id=CHAT, transport=_api_transport(pages))

    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_feviaap1">F仔' in soul
    assert 'user_id="ou_pmviaap1">P酱' in soul
    assert 'user_id="ou_0wnerap1">主人' in soul  # chats owner bonus


def test_via_api_pagination_and_namespaces(tmp_hermes_home: Path, capsys):
    """Both pages are read, and each profile queries with ITS OWN token and
    gets only ITS namespace's ids — the mock keys data by Authorization, so
    a bug that reused one profile's token would show up as crossed ids."""
    for profile, tag in (("team-pm", "pm"), ("team-qa", "qa")):
        _make_profile(
            tmp_hermes_home,
            profile,
            metadata={"key": tag, "name": tag, "coordinator": False},
            log_lines=[],
            soul_entries=[("F仔", "ou_xxx_fe"), ("P酱", "ou_xxx_pm")],
        )
        _api_env(tmp_hermes_home, profile, f"cli_{tag}")

    # Per-app history: page 1 for one tag, page 2 for the other, in each
    # app's OWN id namespace (same person, different id per app).
    history = {
        "tok-cli_pm": [
            [{"mentions": [{"name": "F仔", "id": "ou_fens00pm"}]}],
            [{"mentions": [{"name": "P酱", "id": "ou_pmns00pm"}]}],
        ],
        "tok-cli_qa": [
            [{"mentions": [{"name": "F仔", "id": "ou_fens00qa"}]}],
            [{"mentions": [{"name": "P酱", "id": "ou_pmns00qa"}]}],
        ],
    }
    tokens_seen: list[str] = []
    pages_seen: dict[str, int] = {}

    def transport(method, url, headers, body):
        if url.endswith("/tenant_access_token/internal"):
            app_id = (body or {}).get("app_id", "")
            return 200, {"code": 0, "tenant_access_token": f"tok-{app_id}"}
        if "/im/v1/messages" in url:
            token = headers["Authorization"].removeprefix("Bearer ")
            tokens_seen.append(token)
            page = pages_seen.get(token, 0)
            pages_seen[token] = page + 1
            pages = history[token]
            body_out = {
                "code": 0,
                "data": {"items": pages[page], "has_more": page + 1 < len(pages)},
            }
            if page + 1 < len(pages):
                body_out["data"]["page_token"] = f"{token}-p{page + 1}"
            return 200, body_out
        if "/im/v1/chats/" in url:
            return 200, {"code": 0, "data": {"owner_id": None}}
        raise AssertionError(url)

    collect_team_ids(prefix="team", via_api=True, chat_id=CHAT, transport=transport)

    # Each profile exchanged ITS credentials for its own token, and paged
    # through its full history (2 pages each).
    assert sorted(tokens_seen) == ["tok-cli_pm", "tok-cli_pm", "tok-cli_qa", "tok-cli_qa"]

    pm_soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_fens00pm">F仔' in pm_soul and 'user_id="ou_pmns00pm">P酱' in pm_soul
    qa_soul = (tmp_hermes_home / "profiles" / "team-qa" / "SOUL.md").read_text()
    assert 'user_id="ou_fens00qa">F仔' in qa_soul and 'user_id="ou_pmns00qa">P酱' in qa_soul
    # Namespace isolation: no app's ids leak into the other profile's SOUL.
    assert "00qa" not in pm_soul
    assert "00pm" not in qa_soul


def test_via_api_scope_error_prints_auth_link_and_falls_back(tmp_hermes_home: Path, capsys):
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[_inbound([("F仔", "ou_fefr0ml0g")])],
        soul_entries=[("F仔", "ou_xxx_fe")],
    )
    _api_env(tmp_hermes_home, "team-pm", "cli_pm")

    def transport(method, url, headers, body):
        if url.endswith("/tenant_access_token/internal"):
            return 200, {"code": 0, "tenant_access_token": "tok"}
        return 400, {"code": 230027, "msg": "need scope: im:message.group_msg"}

    collect_team_ids(prefix="team", via_api=True, chat_id=CHAT, transport=transport)
    out = capsys.readouterr().out
    assert "app lacks scope 'im:message.group_msg'" in out
    assert (
        "https://open.feishu.cn/app/cli_pm/auth?q=im:message.group_msg"
        "&op_from=openapi&token_type=tenant" in out
    )
    assert "cli_pm" in out and "sec-cli_pm" not in out  # link names the app, never the secret
    # Fell back to log parsing.
    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_fefr0ml0g">F仔' in soul


def test_via_api_missing_credentials_note(tmp_hermes_home: Path, capsys):
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[_inbound([("F仔", "ou_fefr0ml0g")])],
        soul_entries=[("F仔", "ou_xxx_fe")],
    )
    collect_team_ids(prefix="team", via_api=True, chat_id=CHAT, transport=_api_transport({}))
    out = capsys.readouterr().out
    assert "no Feishu credentials in .env" in out
    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_fefr0ml0g">F仔' in soul


def test_via_api_no_chat_id_note(tmp_hermes_home: Path, capsys):
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[],  # nothing to infer the chat from
        soul_entries=[("F仔", "ou_xxx_fe")],
    )
    _api_env(tmp_hermes_home, "team-pm", "cli_pm")
    collect_team_ids(prefix="team", via_api=True, transport=_api_transport({}))
    out = capsys.readouterr().out
    assert "no chat_id" in out and "--chat-id" in out


def test_collect_ids_idempotent_rerun(tmp_hermes_home: Path):
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[_inbound([("F仔", "ou_ferea1")])],
        soul_entries=[("F仔", "ou_xxx_fe"), ("P酱", "ou_manua1rea1")],
    )
    first = CliRunner().invoke(cli, ["collect-ids", "--prefix", "team"])
    assert first.exit_code == 0, first.output
    soul_after_first = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_ferea1">F仔' in soul_after_first
    assert 'user_id="ou_manua1rea1">P酱' in soul_after_first

    second = CliRunner().invoke(cli, ["collect-ids", "--prefix", "team"])
    assert second.exit_code == 0, second.output
    assert (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text() == soul_after_first
    assert "0 id(s) filled" in second.output


# --- regression: the real CLI --via-api path (NO injected transport) ---


class _FakeUrlopenResponse:
    def __init__(self, body: dict):
        self.status = 200
        self._body = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_via_api_cli_path_without_injected_transport(tmp_hermes_home: Path, monkeypatch):
    """The CLI entry never injects a transport — the default HTTP transport
    must actually be used (it used to be bypassed by a literal None and crash
    with TypeError before the first request)."""
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[],
        soul_entries=[("F仔", "ou_xxx_fe"), ("主人", "ou_xxx_owner")],
    )
    _api_env(tmp_hermes_home, "team-pm", "cli_pm")

    calls: list[str] = []

    def fake_urlopen(request, timeout):
        url = request.full_url
        calls.append(url)
        if url.endswith("/tenant_access_token/internal"):
            return _FakeUrlopenResponse({"code": 0, "tenant_access_token": "tok"})
        if "/im/v1/messages" in url:
            return _FakeUrlopenResponse(
                {
                    "code": 0,
                    "data": {
                        "items": [{"mentions": [{"name": "F仔", "id": "ou_feCL1real"}]}],
                        "has_more": False,
                    },
                }
            )
        if "/im/v1/chats/" in url:
            return _FakeUrlopenResponse({"code": 0, "data": {"owner_id": "ou_0wCL1real"}})
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = CliRunner().invoke(
        cli, ["collect-ids", "--prefix", "team", "--via-api", "--chat-id", CHAT]
    )
    assert result.exit_code == 0, result.output

    assert calls, "the default transport was never used (bypassed again)"
    assert any(u.endswith("/tenant_access_token/internal") for u in calls)
    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_feCL1real">F仔' in soul
    assert 'user_id="ou_0wCL1real">主人' in soul
    assert "sources: api=2" in result.output


# --- regression: owner lookup is best-effort, mentions survive its failure ---


def test_via_api_owner_failure_keeps_mentions(tmp_hermes_home: Path, capsys):
    """A missing im:chat:readonly (chats info) must only skip @主人 — never
    discard the mentions already read, and never claim the messages scope
    (which just worked) is missing."""
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[],
        soul_entries=[("F仔", "ou_xxx_fe"), ("主人", "ou_xxx_owner")],
    )
    _api_env(tmp_hermes_home, "team-pm", "cli_pm")

    def transport(method, url, headers, body):
        if url.endswith("/tenant_access_token/internal"):
            return 200, {"code": 0, "tenant_access_token": "tok"}
        if "/im/v1/messages" in url:
            return 200, {
                "code": 0,
                "data": {"items": [{"mentions": [{"name": "F仔", "id": "ou_fe0kkeep"}]}]},
            }
        if "/im/v1/chats/" in url:
            return 403, {"code": 99991672, "msg": "permission denied"}  # chats scope missing
        raise AssertionError(url)

    collect_team_ids(prefix="team", via_api=True, chat_id=CHAT, transport=transport)
    out = capsys.readouterr().out
    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_fe0kkeep">F仔' in soul  # mentions NOT discarded
    assert 'user_id="ou_xxx_owner">主人' in soul  # owner left as-is
    assert "could not fetch chat owner" in out and "99991672" in out
    # The messages scope just worked — no wrong auth link for it.
    assert "im:message.group_msg" not in out
    assert "/auth?q=" not in out
    # Exempt @主人 placeholder does not count as a gap.
    assert "all filled ✅" in out


def test_via_api_http_5xx_degrades_to_logs_not_silent_success(tmp_hermes_home: Path, capsys):
    """A 5xx with a code-less body must be reported as an API error and fall
    back to log parsing — not read as an empty success."""
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[_inbound([("F仔", "ou_fefr0ml0g")])],
        soul_entries=[("F仔", "ou_xxx_fe")],
    )
    _api_env(tmp_hermes_home, "team-pm", "cli_pm")

    def transport(method, url, headers, body):
        if url.endswith("/tenant_access_token/internal"):
            return 200, {"code": 0, "tenant_access_token": "tok"}
        return 502, {"msg": "Bad Gateway"}  # proxy error, no API code

    collect_team_ids(prefix="team", via_api=True, chat_id=CHAT, transport=transport)
    out = capsys.readouterr().out
    assert "API error (HTTP 502 code=None); using logs only" in out
    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_fefr0ml0g">F仔' in soul  # log fallback applied


def test_via_api_lark_domain_uses_larksuite_host(tmp_hermes_home: Path, capsys):
    """FEISHU_DOMAIN=lark profiles call open.larksuite.com (their credentials
    do not work against the feishu.cn host)."""
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[],
        soul_entries=[("F仔", "ou_xxx_fe")],
    )
    env = tmp_hermes_home / "profiles" / "team-pm" / ".env"
    env.write_text(
        "FEISHU_APP_ID=cli_pm\nFEISHU_APP_SECRET=sec\nFEISHU_DOMAIN=lark\n", encoding="utf-8"
    )
    seen: list[str] = []

    def transport(method, url, headers, body):
        seen.append(url)
        if url.endswith("/tenant_access_token/internal"):
            return 200, {"code": 0, "tenant_access_token": "tok"}
        if "/im/v1/messages" in url:
            return 200, {
                "code": 0,
                "data": {"items": [{"mentions": [{"name": "F仔", "id": "ou_fe1nLark"}]}]},
            }
        if "/im/v1/chats/" in url:
            return 200, {"code": 0, "data": {"owner_id": "ou_0wnerLark"}}
        raise AssertionError(url)

    collect_team_ids(prefix="team", via_api=True, chat_id=CHAT, transport=transport)
    assert seen and all(u.startswith("https://open.larksuite.com/") for u in seen)
    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_fe1nLark">F仔' in soul


# --- regression: log-derived @主人 must not guess among several humans ---


def test_owner_not_filled_when_several_human_senders(tmp_hermes_home: Path):
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[
            _inbound([("F仔", "ou_fe1owner")], sender="user:ou_owner1"),
            _inbound([("F仔", "ou_fe1owner")], sender="user:ou_stranger7"),
        ],
        soul_entries=[("F仔", "ou_xxx_fe"), ("主人", "ou_xxx_owner")],
    )
    result = CliRunner().invoke(cli, ["collect-ids", "--prefix", "team"])
    assert result.exit_code == 0, result.output
    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_fe1owner">F仔' in soul
    assert 'user_id="ou_xxx_owner">主人' in soul  # no guess frozen in
    assert "cannot tell which is @主人" in result.output


def test_inbound_metadata_ignores_tokens_inside_message_body(tmp_hermes_home: Path):
    """chat_id=/sender= quoted in a message body are data, not metadata —
    they must not win "latest chat/sender" selection."""
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[
            # A logged chat where someone pasted id-looking text into the body.
            _inbound([("F仔", "ou_fe1body")], sender="user:ou_real0wner").replace(
                "text='", "text='psst chat_id=oc_bodyfake sender=user:ou_bodyfake "
            ),
        ],
        soul_entries=[("F仔", "ou_xxx_fe"), ("主人", "ou_xxx_owner")],
    )
    result = CliRunner().invoke(cli, ["collect-ids", "--prefix", "team"])
    assert result.exit_code == 0, result.output
    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_real0wner">主人' in soul  # NOT ou_bodyfake


# --- regression: mention names may contain commas (team_config allows them) ---


def test_extract_mention_ids_keeps_comma_names_whole():
    text = "\n".join(
        [
            _inbound([("A,B", "ou_aaa"), ("C", "ou_ccc")]),  # comma w/o space
            _inbound([("A, B", "ou_sp1")]),  # comma WITH space (", " separator!)
        ]
    )
    assert extract_mention_ids(text) == {"A,B": "ou_aaa", "C": "ou_ccc", "A, B": "ou_sp1"}


def test_extract_mention_ids_atall_between_real_mentions():
    text = (
        "2026-10-22 00:37:20 INFO adapter: [Feishu] Inbound group message received: "
        f"id=om_x1 type=text chat_id={CHAT} sender=user:ou_owner1 "
        "text='[Mentioned: @all, P酱 (open_id=ou_pm1), ]\\n\\n正文' media=0"
    )
    assert extract_mention_ids(text) == {"P酱": "ou_pm1"}


# --- regression: remaining count matches verify's exemption rule ---


def test_remaining_skips_owner_and_hub_placeholders(tmp_hermes_home: Path):
    """主人 and the render-only hub are placeholders BY DESIGN (verify exempts
    them); collect-ids must not report them as gaps on an otherwise full SOUL."""
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},  # legacy: no hub key → M总
        log_lines=[_inbound([("F仔", "ou_fe1exempt")])],
        soul_entries=[
            ("F仔", "ou_xxx_fe"),
            ("主人", "ou_xxx_owner"),
            ("M总", "ou_xxx_hub"),
        ],
    )
    result = CliRunner().invoke(cli, ["collect-ids", "--prefix", "team"])
    assert result.exit_code == 0, result.output
    # F仔 (mention) + 主人 (sole log sender) are filled; the exempt M总
    # placeholder stays but is NOT reported as a gap.
    assert "2 id(s) filled" in result.output
    assert "placeholder(s) remain" not in result.output
    assert "all filled ✅" in result.output
    assert "still have placeholders" not in result.output
    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_fe1exempt">F仔' in soul
    assert 'user_id="ou_owner1">主人' in soul
    assert 'user_id="ou_xxx_hub">M总' in soul


# --- regression: resolved-by-API names must not trigger log-heuristic warnings ---


def test_via_api_resolved_names_silence_log_heuristics(tmp_hermes_home: Path, capsys):
    """API resolved P酱 (own line) and 主人 (chats owner) — the log fallbacks
    must stay quiet about them: their "left as-is / cannot tell" warnings
    would claim lines are unfilled when the SOUL is actually complete."""
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[
            _inbound([("F仔", "ou_feunused")], sender="user:ou_owner1"),
            _inbound([("F仔", "ou_feunused")], sender="user:ou_stranger7"),  # 2nd human
            _legacy_sender_bot("ou_botA", "P酱"),
            _legacy_sender_bot("ou_botB", "P酱"),  # 2nd bot id → ambiguous own line
        ],
        soul_entries=[("P酱", "ou_xxx_pm"), ("F仔", "ou_xxx_fe"), ("主人", "ou_xxx_owner")],
    )
    _api_env(tmp_hermes_home, "team-pm", "cli_pm")

    def transport(method, url, headers, body):
        if url.endswith("/tenant_access_token/internal"):
            return 200, {"code": 0, "tenant_access_token": "tok"}
        if "/im/v1/messages" in url:
            return 200, {
                "code": 0,
                "data": {
                    "items": [
                        {
                            "mentions": [
                                {"name": "F仔", "id": "ou_feAP1f1ll"},
                                {"name": "P酱", "id": "ou_pmAP1f1ll"},
                            ]
                        }
                    ]
                },
            }
        if "/im/v1/chats/" in url:
            return 200, {"code": 0, "data": {"owner_id": "ou_api0wner"}}
        raise AssertionError(url)

    collect_team_ids(prefix="team", via_api=True, chat_id=CHAT, transport=transport)
    out = capsys.readouterr().out
    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_api0wner">主人' in soul  # API owner actually filled
    assert 'user_id="ou_pmAP1f1ll">P酱' in soul
    assert 'user_id="ou_feAP1f1ll">F仔' in soul
    assert "cannot tell which is @主人" not in out  # was filled — no false alarm
    assert "own @-line left as-is" not in out
    assert "3 id(s) filled" in out and "sources: api=3" in out


# --- regression: --chat-id default inference from the log ---


def _recording_transport(urls: list[str], items: list[dict] | None = None):
    def transport(method, url, headers, body):
        urls.append(url)
        if url.endswith("/tenant_access_token/internal"):
            return 200, {"code": 0, "tenant_access_token": "tok"}
        if "/im/v1/messages" in url:
            return 200, {"code": 0, "data": {"items": items or [], "has_more": False}}
        if "/im/v1/chats/" in url:
            return 200, {"code": 0, "data": {"owner_id": None}}
        raise AssertionError(url)

    return transport


def test_via_api_infers_chat_id_from_log(tmp_hermes_home: Path, capsys):
    """README-documented default: no --chat-id → the messages request uses
    the latest chat_id observed in this profile's own gateway log."""
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[_inbound([("F仔", "ou_fe1nfered")])],  # inbound line carries chat_id=CHAT
        soul_entries=[("F仔", "ou_xxx_fe")],
    )
    _api_env(tmp_hermes_home, "team-pm", "cli_pm")

    urls: list[str] = []
    collect_team_ids(
        prefix="team",
        via_api=True,
        transport=_recording_transport(urls, [{"mentions": [{"name": "F仔", "id": "ou_feINF1"}]}]),
    )
    messages_urls = [u for u in urls if "/im/v1/messages" in u]
    assert messages_urls and f"container_id={CHAT}" in messages_urls[0]
    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_feINF1">F仔' in soul


def test_via_api_group_chat_id_beats_newer_p2p_line(tmp_hermes_home: Path, capsys):
    """The default inference must target the team GROUP even when a newer
    p2p inbound line appears later in the log (DM history is not the team)."""
    p2p = (
        "2026-10-22 09:00:00 INFO adapter: [Feishu] Inbound message received: "
        "id=om_p2p type=text chat_id=oc_p2pchat1d sender=user:ou_owner1 text='hi' media=0"
    )
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[
            _inbound([("F仔", "ou_fe1group")]),  # group line, earlier
            p2p,  # newer p2p line — must NOT win
        ],
        soul_entries=[("F仔", "ou_xxx_fe")],
    )
    _api_env(tmp_hermes_home, "team-pm", "cli_pm")

    urls: list[str] = []
    collect_team_ids(prefix="team", via_api=True, transport=_recording_transport(urls))
    messages_urls = [u for u in urls if "/im/v1/messages" in u]
    assert messages_urls and f"container_id={CHAT}" in messages_urls[0]
    assert "oc_p2pchat1d" not in "".join(messages_urls)


def test_latest_chat_id_prefers_group_falls_back_to_any(tmp_path: Path):
    from hermes_multi_agent_team.utils.open_id import latest_chat_id

    group_then_dm = tmp_path / "a.log"
    group_then_dm.write_text(
        _inbound([("F仔", "ou_x")]).replace("00:37:20", "08:00:00")
        + "\n"
        + "2026-10-22 09:00:00 INFO adapter: [Feishu] Inbound message received: "
        "id=om_p2p type=text chat_id=oc_dm00000001 sender=user:ou_o text='hi' media=0" + "\n",
        encoding="utf-8",
    )
    assert latest_chat_id(group_then_dm) == CHAT  # group wins over newer DM

    dm_only = tmp_path / "b.log"
    dm_only.write_text(
        "2026-10-22 09:00:00 INFO adapter: [Feishu] Inbound message received: "
        "id=om_p2p type=text chat_id=oc_dm00000001 sender=user:ou_o text='hi' media=0\n",
        encoding="utf-8",
    )
    assert latest_chat_id(dm_only) == "oc_dm00000001"  # DM-only bot still infers


# --- regression: --chat-id validation and malformed-URL degradation ---


def test_chat_id_option_rejects_malformed_value(tmp_hermes_home: Path):
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[],
        soul_entries=[("F仔", "ou_xxx_fe")],
    )
    result = CliRunner().invoke(
        cli, ["collect-ids", "--prefix", "team", "--via-api", "--chat-id", "oc bad"]
    )
    assert result.exit_code == 2  # usage error, not a traceback
    assert "must be a Feishu chat id" in result.output


def test_api_layer_degrades_on_invalid_url_not_traceback(
    tmp_hermes_home: Path, capsys, monkeypatch
):
    """A bad chat_id reaching the API layer past the CLI gate (direct
    collect_team_ids callers) degrades to log parsing — InvalidURL is an
    HTTPException, which used to escape as a traceback."""
    import http.client

    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[_inbound([("F仔", "ou_fefr0ml0g")])],
        soul_entries=[("F仔", "ou_xxx_fe")],
    )
    _api_env(tmp_hermes_home, "team-pm", "cli_pm")

    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/tenant_access_token/internal"):
            return _FakeUrlopenResponse({"code": 0, "tenant_access_token": "tok"})
        raise http.client.InvalidURL("URL can't contain control characters.")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    # No transport injected → the DEFAULT transport is exercised.
    collect_team_ids(prefix="team", via_api=True, chat_id="oc bad")
    out = capsys.readouterr().out
    assert "API request failed (InvalidURL); using logs only" in out
    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_fefr0ml0g">F仔' in soul  # log fallback applied


# --- regression: source breakdown matches the filled count ---


def test_sources_breakdown_counts_only_written_ids(tmp_hermes_home: Path, capsys):
    """The API may observe names this SOUL does not carry (here: a chats
    owner with no @主人 line) — the report must not count them as fills."""
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[],
        soul_entries=[("F仔", "ou_xxx_fe")],  # no 主人 line in this SOUL
    )
    _api_env(tmp_hermes_home, "team-pm", "cli_pm")

    def transport(method, url, headers, body):
        if url.endswith("/tenant_access_token/internal"):
            return 200, {"code": 0, "tenant_access_token": "tok"}
        if "/im/v1/messages" in url:
            return 200, {
                "code": 0,
                "data": {"items": [{"mentions": [{"name": "F仔", "id": "ou_feSRC01"}]}]},
            }
        if "/im/v1/chats/" in url:
            return 200, {
                "code": 0,
                "data": {"owner_id": "ou_0wnerNOFIL"},
            }  # observed, never written
        raise AssertionError(url)

    collect_team_ids(prefix="team", via_api=True, chat_id=CHAT, transport=transport)
    out = capsys.readouterr().out
    assert "1 id(s) filled" in out
    assert "sources: api=1" in out  # NOT api=2 — the owner was never written
    assert "api=2" not in out
    # And a rerun fills nothing → no source detail at all.
    collect_team_ids(prefix="team", via_api=True, chat_id=CHAT, transport=transport)
    out2 = capsys.readouterr().out
    assert "0 id(s) filled" in out2
    assert "sources:" not in out2


# --- regression: a teammate bot's inbound sender is NOT this bot's own id ---


def test_own_line_not_filled_from_teammate_inbound_sender(tmp_hermes_home: Path):
    """Inbound sender=bot lines are TEAMMATE bots @-mentioning this bot —
    the only such line must not be mistaken for this profile's own id (the
    wrong id would be frozen in by idempotent re-runs and would survive
    re-renders)."""
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[
            # The ONLY bot sender in the log — on an inbound line, and it is
            # a teammate's id, not P酱's own.
            _inbound([("F仔", "ou_fenspm0001")], sender="bot:ou_teammate1"),
        ],
        soul_entries=[("P酱", "ou_xxx_pm"), ("F仔", "ou_xxx_fe")],
    )
    result = CliRunner().invoke(cli, ["collect-ids", "--prefix", "team"])
    assert result.exit_code == 0, result.output
    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_fenspm0001">F仔' in soul  # genuine mention still fills
    assert 'user_id="ou_xxx_pm">P酱' in soul  # own line stays a placeholder…
    assert "ou_teammate1" not in soul  # …and never takes the teammate's id
    assert "1 placeholder(s) remain" in result.output  # reported honestly
    assert "sender=1" not in result.output  # no phantom own-id source


def test_own_line_still_filled_from_outbound_sender_line(tmp_hermes_home: Path):
    """Outbound sender=bot lines (free mode) remain the own-id source even
    when the log ALSO carries inbound teammate-bot senders."""
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[
            _inbound([("F仔", "ou_fenspm0001")], sender="bot:ou_teammate1"),
            _legacy_sender_bot("ou_ownB0tpm1", "P酱"),  # outbound → own id
        ],
        soul_entries=[("P酱", "ou_xxx_pm"), ("F仔", "ou_xxx_fe")],
    )
    result = CliRunner().invoke(cli, ["collect-ids", "--prefix", "team"])
    assert result.exit_code == 0, result.output
    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_ownB0tpm1">P酱' in soul  # own line from outbound line
    assert "ou_teammate1" not in soul


# --- regression: pasted [Mentioned:] text in a body is not an observation ---


def _inbound_with_pasted_mention(pasted: str) -> str:
    """A real inbound line whose BODY carries pasted [Mentioned:] text —
    the genuine header mentions 老板 only."""
    genuine = _inbound([("老板", "ou_bosreal01")], sender="user:ou_owner1")
    return genuine.replace("\\n\\n正文", f"\\n\\n{pasted}")


def test_extract_mention_ids_ignores_pasted_mention_in_body():
    pasted_mention = _inbound_with_pasted_mention("看这个 [Mentioned: F仔 (open_id=ou_FAKEID01)]")
    assert extract_mention_ids(pasted_mention) == {"老板": "ou_bosreal01"}
    # …and even a pasted ADAPTER line with its own text=' quote.
    pasted_line = _inbound_with_pasted_mention(
        "看这个 text='[Mentioned: F仔 (open_id=ou_FAKEID01)]'"
    )
    assert extract_mention_ids(pasted_line) == {"老板": "ou_bosreal01"}


def test_pasted_mention_in_body_does_not_fill_soul(tmp_hermes_home: Path):
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[_inbound_with_pasted_mention("看这个 [Mentioned: F仔 (open_id=ou_FAKEID01)]")],
        soul_entries=[("老板", "ou_xxx_coordinator"), ("F仔", "ou_xxx_fe")],
    )
    result = CliRunner().invoke(cli, ["collect-ids", "--prefix", "team"])
    assert result.exit_code == 0, result.output
    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_bosreal01">老板' in soul  # genuine header fills
    assert 'user_id="ou_xxx_fe">F仔' in soul  # pasted id never used…
    assert "ou_FAKEID01" not in soul
    assert "sources: mention=1" in result.output  # only the real observation


# --- regression: hand-filled SOUL lines silence the log heuristics ---


def _plain_inbound(sender: str) -> str:
    """An inbound metadata line with a plain body (no mention header)."""
    return (
        "2026-10-22 INFO adapter: [Feishu] Inbound group message received: "
        f"id=om_x1 type=text chat_id={CHAT} sender={sender} text='hi' media=0"
    )


def test_hand_filled_soul_silences_log_heuristics(tmp_hermes_home: Path):
    """Hand-filled ids (README-supported) are final: an ambiguous log must
    not print "left as-is" warnings about lines that are actually filled."""
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[
            _plain_inbound("user:ou_h1"),
            _plain_inbound("user:ou_h2"),
            _legacy_sender_bot("ou_botA", "P酱"),
            _legacy_sender_bot("ou_botB", "P酱"),  # 2 bot ids + 2 humans: ambiguous
        ],
        soul_entries=[("P酱", "ou_handfill1"), ("主人", "ou_handfill2")],  # both hand-filled
    )
    result = CliRunner().invoke(cli, ["collect-ids", "--prefix", "team"])
    assert result.exit_code == 0, result.output
    assert "own @-line left as-is" not in result.output
    assert "cannot tell which is @主人" not in result.output
    assert "0 id(s) filled, all filled ✅" in result.output  # consistent story
    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_handfill1">P酱' in soul and 'user_id="ou_handfill2">主人' in soul


# --- regression: owner-fetch failure must not misstate a hand-filled line ---


def test_via_api_owner_failure_with_hand_filled_owner(tmp_hermes_home: Path, capsys):
    """--via-api + a hand-filled real @主人 + chats info 403: the warning
    must not claim "its placeholder is left as-is" about a line that holds a
    real id (the round-3 class of self-contradiction, API side)."""
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[],
        soul_entries=[("F仔", "ou_xxx_fe"), ("主人", "ou_handowner1")],  # owner hand-filled
    )
    _api_env(tmp_hermes_home, "team-pm", "cli_pm")

    def transport(method, url, headers, body):
        if url.endswith("/tenant_access_token/internal"):
            return 200, {"code": 0, "tenant_access_token": "tok"}
        if "/im/v1/messages" in url:
            return 200, {
                "code": 0,
                "data": {"items": [{"mentions": [{"name": "F仔", "id": "ou_feOWN403"}]}]},
            }
        if "/im/v1/chats/" in url:
            return 403, {"code": 99991672, "msg": "permission denied"}
        raise AssertionError(url)

    collect_team_ids(prefix="team", via_api=True, chat_id=CHAT, transport=transport)
    out = capsys.readouterr().out
    assert "could not fetch chat owner" in out and "99991672" in out
    # The warning only states the failure — no prediction about the @主人
    # line's state (it may hold a real id, or be filled by the log fallback
    # later; both made the old "left unchanged" claim wrong or right by luck).
    assert "left unchanged" not in out
    assert "placeholder is left as-is" not in out
    assert "1 id(s) filled, all filled ✅" in out  # consistent final state
    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_feOWN403">F仔' in soul
    assert 'user_id="ou_handowner1">主人' in soul  # hand-filled id untouched


# --- regression: hub-dict metadata exemption (builtin-team shape) ---


def test_hub_dict_metadata_exempts_hub_placeholder(tmp_hermes_home: Path):
    """Teams whose metadata records the render-only hub as a DICT — the
    shape init.py writes for the builtin team ("hub": {"name": "M总", …}) —
    must exempt that hub's placeholder exactly like the legacy no-hub-key
    branch; a regression here re-introduces "placeholders remain forever"
    on default teams."""
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={
            "key": "pm",
            "name": "P酱",
            "coordinator": False,
            # The exact shape init.py:299 persists for the builtin team.
            "hub": {"name": "M总", "nickname": "M总", "role": "总管"},
        },
        log_lines=[_inbound([("F仔", "ou_fe1hubdct")], sender="user:ou_owner1")],
        soul_entries=[("F仔", "ou_xxx_fe"), ("主人", "ou_xxx_owner"), ("M总", "ou_xxx_hub")],
    )
    result = CliRunner().invoke(cli, ["collect-ids", "--prefix", "team"])
    assert result.exit_code == 0, result.output
    # F仔 (mention) + 主人 (sole log sender) filled; both 主人 and the
    # hub-dict M总 placeholders are exempt → no gap reported.
    assert "2 id(s) filled, all filled ✅" in result.output
    assert "placeholder(s) remain" not in result.output
    assert "still have placeholders" not in result.output
    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_xxx_hub">M总' in soul  # render-only hub stays a placeholder


def test_multiple_outbound_bot_ids_warn_and_keep_own_placeholder(tmp_hermes_home: Path):
    """The ambiguous own-id log (>1 outbound bot senders, own line still a
    placeholder) prints the heuristic's warning and leaves the line as-is."""
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[
            _legacy_sender_bot("ou_botA", "P酱"),
            _legacy_sender_bot("ou_botB", "P酱"),  # 2 outbound ids: ambiguous
        ],
        soul_entries=[("P酱", "ou_xxx_pm")],
    )
    result = CliRunner().invoke(cli, ["collect-ids", "--prefix", "team"])
    assert result.exit_code == 0, result.output
    assert "2 bot ids in its log — cannot tell which is its own; own @-line left as-is" in (
        result.output
    )
    assert "1 placeholder(s) remain" in result.output
    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_xxx_pm">P酱' in soul  # no guess frozen in


def test_fills_souls_with_custom_section_heading(tmp_hermes_home: Path):
    """Custom templates name the roster section differently (the real
    whisage team uses 【飞书@格式】) — filling must not depend on the
    bundled templates' 【飞书@方式】 heading, only on <at> tags."""
    profile = tmp_hermes_home / "profiles" / "t-pm"
    (profile / "logs").mkdir(parents=True)
    (profile / ".hermes-team.json").write_text(
        json.dumps(
            {
                "key": "pm",
                "name": "P酱(sc)",
                "coordinator": False,
                "team": "T",
                "prefix": "t",
                "template": "pm.md.j2",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (profile / "SOUL.md").write_text(
        "【飞书@格式】\n"
        '- @P酱(sc)：`<at user_id="ou_xxx_pm">P酱(sc)</at>`\n'
        '- @F仔(sc)：`<at user_id="ou_xxx_fe">F仔(sc)</at>`\n',
        encoding="utf-8",
    )
    (profile / "logs" / "gateway.log").write_text(
        "2026-10-22 INFO adapter: [Feishu] Inbound group message received: "
        "id=om_x type=text chat_id=oc_c1 sender=user:ou_0wner111 "
        "text='[Mentioned: F仔(sc) (open_id=ou_fe111abc)]' media=0\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["collect-ids", "--prefix", "t"])
    assert result.exit_code == 0, result.output
    assert "no 【飞书@方式】 section" not in result.output
    soul = (profile / "SOUL.md").read_text()
    assert 'user_id="ou_fe111abc">F仔(sc)' in soul
    assert "1 id(s) filled" in result.output


def test_soul_without_any_at_tags_reports_info(tmp_hermes_home: Path, capsys):
    profile = tmp_hermes_home / "profiles" / "t-pm"
    (profile / "logs").mkdir(parents=True)
    (profile / ".hermes-team.json").write_text(
        json.dumps(
            {
                "key": "pm",
                "name": "P酱",
                "coordinator": False,
                "team": "T",
                "prefix": "t",
                "template": "pm.md.j2",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (profile / "SOUL.md").write_text("一个完全没有 @ 标签的人设。\n", encoding="utf-8")
    (profile / "logs" / "gateway.log").write_text("", encoding="utf-8")

    from hermes_multi_agent_team.commands.collect_ids import collect_team_ids

    collect_team_ids(prefix="t")
    out = capsys.readouterr().out
    assert "no @-tags in SOUL.md — nothing to fill" in out
    assert "all filled ✅" not in out


# --- regression: Hermes logs the body via repr — text="…" for bodies with
# single quotes; only adapter inbound lines carry observations ---


def test_double_quoted_repr_inbound_line_is_parsed(tmp_path: Path):
    """A body containing a single quote renders repr-DOUBLE-quoted
    (text="…"): the [Mentioned:] header must still parse, and id-like tokens
    inside the body must not leak into chat/sender metadata."""
    from hermes_multi_agent_team.utils.open_id import distinct_user_sender_ids, latest_chat_id

    line = (
        "2026-10-22 00:37:20 INFO adapter: [Feishu] Inbound group message received: "
        f"id=om_x1 type=text chat_id={CHAT} sender=user:ou_real0wner "
        'text="[Mentioned: F仔 (open_id=ou_feDBLQTE1), ]\\n\\n'
        "it's quoting chat_id=oc_bodyfake sender=user:ou_bodyfake\" media=0"
    )
    assert extract_mention_ids(line) == {"F仔": "ou_feDBLQTE1"}

    log = tmp_path / "gateway.log"
    log.write_text(line + "\n", encoding="utf-8")
    assert distinct_user_sender_ids(log) == ["ou_real0wner"]  # body token is not metadata
    assert latest_chat_id(log) == CHAT  # oc_bodyfake never wins


def test_reply_to_text_quoted_message_is_not_an_observation():
    """A quoted message's [Mentioned:] content logged on a NON-inbound line
    (reply_to_text='…' — whose tail contains a literal text=' substring!) is
    another message's text, not this app's inbound observation."""
    quoted = (
        "2026-10-22 00:41:00 INFO gateway: session context "
        "reply_to_text='[Mentioned: Q宝 (open_id=ou_qaQU0TED)]\\n\\n原话'"
    )
    assert extract_mention_ids(quoted) == {}


# --- regression: network failure degrades to log parsing, honestly ---


def test_via_api_network_error_degrades_to_logs(tmp_hermes_home: Path, capsys):
    """Offline/DNS/timeout (urllib URLError, an OSError subclass) — the most
    common real-world API failure — must print the network-error note and
    fall back to the log sources."""
    import urllib.error

    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[_inbound([("F仔", "ou_fefr0ml0g")])],
        soul_entries=[("F仔", "ou_xxx_fe")],
    )
    _api_env(tmp_hermes_home, "team-pm", "cli_pm")

    def transport(method, url, headers, body):
        raise urllib.error.URLError("timed out")

    collect_team_ids(prefix="team", via_api=True, chat_id=CHAT, transport=transport)
    out = capsys.readouterr().out
    assert "network error (URLError); using logs only" in out
    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_fefr0ml0g">F仔' in soul  # SOUL fell back to the log source
    assert "sources: mention=1" in out


# --- regression: owner-fetch failure wording vs the log fallback ---


def test_via_api_owner_failure_then_log_fallback_fills_owner(tmp_hermes_home: Path, capsys):
    """Owner query failure + a single human sender in the log: the warning
    must only state the failure — the log fallback right after DOES fill
    @主人, and the old "line is left unchanged" prediction contradicted the
    very next "sources: log=1" line."""
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[_inbound([("F仔", "ou_feOWNF1")], sender="user:ou_solehuman")],
        soul_entries=[("F仔", "ou_xxx_fe"), ("主人", "ou_xxx_owner")],
    )
    _api_env(tmp_hermes_home, "team-pm", "cli_pm")

    def transport(method, url, headers, body):
        if url.endswith("/tenant_access_token/internal"):
            return 200, {"code": 0, "tenant_access_token": "tok"}
        if "/im/v1/messages" in url:
            return 200, {"code": 0, "data": {"items": []}}
        if "/im/v1/chats/" in url:
            return 403, {"code": 99991672, "msg": "permission denied"}
        raise AssertionError(url)

    collect_team_ids(prefix="team", via_api=True, chat_id=CHAT, transport=transport)
    out = capsys.readouterr().out
    assert "could not fetch chat owner" in out
    assert "left unchanged" not in out  # no prediction the fill contradicts
    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_solehuman">主人' in soul  # the log fallback DID fill it
    assert "log=1" in out


# --- regression: --chat-id is meaningless without --via-api ---


def test_chat_id_without_via_api_is_a_usage_error(tmp_hermes_home: Path):
    """--chat-id only feeds the --via-api history request; without the flag
    it used to be accepted (even validated!) yet silently ignored — the user
    believed the API route ran while only logs were parsed."""
    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[],
        soul_entries=[("F仔", "ou_xxx_fe")],
    )
    result = CliRunner().invoke(cli, ["collect-ids", "--prefix", "team", "--chat-id", CHAT])
    assert result.exit_code == 2
    assert "--chat-id only applies together with --via-api" in result.output
    # The command never ran — nothing was written.
    soul = (tmp_hermes_home / "profiles" / "team-pm" / "SOUL.md").read_text()
    assert 'user_id="ou_xxx_fe">F仔' in soul


# --- regression: an unwritable SOUL fails per profile, not with a traceback ---


def test_soul_write_failure_reports_profile_and_continues(tmp_hermes_home: Path, monkeypatch):
    """A SOUL write that fails (full disk, unwritable dir) must not escape
    as a bare PermissionError/OSError traceback nor abort the remaining
    profiles: the failure is reported per profile and later profiles are
    still filled. The original SOUL must stay intact (atomic replace)."""
    import os as os_mod

    _make_profile(
        tmp_hermes_home,
        "team-pm",
        metadata={"key": "pm", "name": "P酱", "coordinator": False},
        log_lines=[_inbound([("F仔", "ou_feWRTFAlL")])],
        soul_entries=[("F仔", "ou_xxx_fe")],
    )
    _make_profile(
        tmp_hermes_home,
        "team-qa",
        metadata={"key": "qa", "name": "Q宝", "coordinator": False},
        log_lines=[_inbound([("F仔", "ou_feWRTFAl2")])],
        soul_entries=[("F仔", "ou_xxx_fe")],
    )

    real_replace = os_mod.replace

    def _failing_replace(src, dst, *args, **kwargs):
        if str(dst).endswith("team-pm/SOUL.md"):
            raise OSError(28, "No space left on device")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr("hermes_multi_agent_team.utils.open_id.os.replace", _failing_replace)

    result = CliRunner().invoke(cli, ["collect-ids", "--prefix", "team"])
    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output
    assert "could not write SOUL.md" in result.output and "team-pm" in result.output
    assert "NOT saved" in result.output
    # The failed profile's SOUL is intact and no temp file was left behind.
    pm_dir = tmp_hermes_home / "profiles" / "team-pm"
    assert 'user_id="ou_xxx_fe">F仔' in (pm_dir / "SOUL.md").read_text()
    assert not (pm_dir / "SOUL.md.tmp").exists()
    # The later profile was still processed and filled.
    qa_soul = (tmp_hermes_home / "profiles" / "team-qa" / "SOUL.md").read_text()
    assert 'user_id="ou_feWRTFAl2">F仔' in qa_soul
