"""Unit tests for the Feishu API client (transport/decode/status/scope/domain).

These pin the failure modes collect-ids relies on to degrade to log parsing
instead of crashing or silently reporting empty success.
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from hermes_multi_agent_team.utils.feishu_api import (
    BASE_URL,
    LARK_BASE_URL,
    FeishuApiError,
    _check,
    _default_transport,
    base_url_for,
    one_click_auth_url,
)


class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


# --- domain → base URL (issue: BASE_URL was hardcoded to feishu.cn) ---


def test_base_url_for_domain():
    assert base_url_for("lark") == LARK_BASE_URL
    assert base_url_for("LARK") == LARK_BASE_URL  # case-insensitive like env values
    assert base_url_for(" lark ") == LARK_BASE_URL
    assert base_url_for("feishu") == BASE_URL
    assert base_url_for(None) == BASE_URL  # unset in .env → Feishu default
    assert base_url_for("") == BASE_URL


def test_one_click_auth_url_uses_domain_host():
    assert one_click_auth_url("cli_x", "im:message.group_msg").startswith(BASE_URL)
    assert one_click_auth_url("cli_x", "im:message.group_msg", base_url=LARK_BASE_URL).startswith(
        LARK_BASE_URL
    )


# --- _check: HTTP status must not pass as a code-less success ---


def test_check_raises_on_http_error_status_without_code():
    # A 5xx whose body carries no API code (proxy/HTML error) used to be
    # treated as a code-less SUCCESS → "0 id(s) filled" silence.
    with pytest.raises(FeishuApiError) as exc:
        _check(502, {"msg": "Bad Gateway"})
    assert exc.value.status == 502
    assert exc.value.code is None
    assert "Bad Gateway" in exc.value.msg


def test_check_keeps_api_code_from_error_body():
    with pytest.raises(FeishuApiError) as exc:
        _check(403, {"code": 230027, "msg": "need scope: im:message.group_msg"})
    assert exc.value.code == 230027


def test_check_passes_success_bodies():
    assert _check(200, {"code": 0, "data": {}}) == {"code": 0, "data": {}}


# --- _default_transport: non-JSON bodies are errors, not success payloads ---


def test_default_transport_raises_on_html_200(monkeypatch: pytest.MonkeyPatch):
    """A captive portal / proxy returning HTML with HTTP 200 must surface as
    FeishuApiError (collect-ids catches it and falls back to logs), not as a
    JSONDecodeError traceback."""
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(b"<html>portal login</html>", 200),
    )
    with pytest.raises(FeishuApiError) as exc:
        _default_transport("GET", "https://x/", {}, None)
    assert exc.value.status == 200
    assert "portal" in exc.value.msg


def test_default_transport_raises_on_html_http_error(monkeypatch: pytest.MonkeyPatch):
    def _raise(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 500, "Server Error", hdrs=None, fp=io.BytesIO(b"<html>oops</html>")
        )

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    with pytest.raises(FeishuApiError) as exc:
        _default_transport("GET", "https://x/", {}, None)
    assert exc.value.status == 500
    assert "oops" in exc.value.msg


def test_default_transport_parses_json(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: _FakeResponse(json.dumps({"code": 0}).encode()),
    )
    status, body = _default_transport("GET", "https://x/", {}, None)
    assert status == 200 and body == {"code": 0}


# --- missing_scope: the fallback belongs to the failing endpoint ---


def test_missing_scope_reads_scope_from_message():
    e = FeishuApiError(403, 230027, "need scope: im:chat:readonly")
    assert e.missing_scope("im:message.group_msg") == "im:chat:readonly"


def test_missing_scope_fallback_is_caller_supplied():
    # 99991672 names no scope: only the CALLER knows which endpoint failed,
    # so no fallback → None (honest report) instead of a wrong auth link.
    assert FeishuApiError(403, 99991672, "permission denied").missing_scope() is None
    assert (
        FeishuApiError(403, 99991672, "permission denied").missing_scope("im:message.group_msg")
        == "im:message.group_msg"
    )


def test_missing_scope_none_for_other_codes():
    assert FeishuApiError(400, 400, "bad request").missing_scope("x") is None
