"""Minimal Feishu Open API client for collect-ids --via-api.

Reads group message history per profile with that profile's own app
credentials, so every returned open_id is already in the right app's
namespace. The HTTP layer is injectable (``transport``) so tests run without
a network. App secrets are passed through, never logged or embedded in
error messages or auth links.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

BASE_URL = "https://open.feishu.cn"
LARK_BASE_URL = "https://open.larksuite.com"

# transport(method, url, headers, body|None) -> (status_code, parsed_json_or_text)
Transport = Callable[[str, str, dict[str, str], dict[str, Any] | None], tuple[int, Any]]


def base_url_for(domain: str | None) -> str:
    """The Open API host for a profile's FEISHU_DOMAIN value.

    ``lark`` tenants (configure offers the choice) are served by
    larksuite.com, not the feishu.cn domain — same credentials, different
    host, so the client must follow the profile's own setting. Anything
    missing/unknown defaults to the Feishu domain.
    """
    return LARK_BASE_URL if (domain or "").strip().lower() == "lark" else BASE_URL


class FeishuApiError(Exception):
    """A non-zero API response. Carries the machine-readable code."""

    def __init__(self, status: int, code: int | None, msg: str):
        super().__init__(f"HTTP {status} code={code} msg={msg}")
        self.status = status
        self.code = code
        self.msg = msg

    def missing_scope(self, fallback_scope: str | None = None) -> str | None:
        """The scope name this app lacks, when the error is a scope problem.

        Real-world forms seen: code 230027 with "need scope: xxx" in the
        message, and the generic permission-denied 99991672 (whose message
        names no scope). The scope is taken from the message when present;
        otherwise the CALLER's ``fallback_scope`` is used — each endpoint
        needs a different scope, so only the failing call knows the right
        fallback (messages → im:message.group_msg, chats → im:chat:readonly),
        and a blind one-size-fits-all default would print a wrong auth link.
        """
        if self.code in (230027, 99991672):
            marker = "need scope: "
            if marker in self.msg:
                return self.msg.split(marker, 1)[1].split()[0].strip()
            return fallback_scope
        return None


def _decode_or_raise(status: int, raw: str) -> Any:
    """Parse an HTTP body as JSON; a non-JSON body (portal/proxy HTML on a
    captive 200, or an HTML error page) is an API error, not a success —
    it must surface as FeishuApiError so the caller degrades to log parsing
    instead of silently reading an empty payload."""
    try:
        return json.loads(raw)
    except ValueError:
        raise FeishuApiError(status, None, raw[:200]) from None


def _default_transport(
    method: str, url: str, headers: dict[str, str], body: dict[str, Any] | None
) -> tuple[int, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, _decode_or_raise(response.status, raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        return e.code, _decode_or_raise(e.code, raw)
    # URLError (DNS/offline) propagates as an OSError subclass; the caller
    # reports it and falls back to log parsing.


def _check(status: int, body: Any) -> dict[str, Any]:
    """Raise on a non-2xx HTTP status or a non-zero API code, else return the body.

    The HTTP status is checked first: a 4xx/5xx whose body carries no API
    ``code`` (HTML error page, bare text) must not pass as a code-less
    success — that turned server errors into "0 id(s) filled" silence.
    """
    if status >= 400 or not isinstance(body, dict) or body.get("code") not in (0, None):
        code = body.get("code") if isinstance(body, dict) else None
        msg = body.get("msg") if isinstance(body, dict) else str(body)[:200]
        raise FeishuApiError(status, code, str(msg))
    return body


def get_tenant_token(
    app_id: str,
    app_secret: str,
    transport: Transport | None = None,
    base_url: str = BASE_URL,
) -> str:
    """Exchange app credentials for a tenant_access_token."""
    status, body = (transport or _default_transport)(
        "POST",
        f"{base_url}/open-apis/auth/v3/tenant_access_token/internal",
        {"Content-Type": "application/json; charset=utf-8"},
        {"app_id": app_id, "app_secret": app_secret},
    )
    token = _check(status, body).get("tenant_access_token")
    if not token:
        raise FeishuApiError(status, body.get("code"), "no tenant_access_token in response")
    return str(token)


def fetch_chat_messages(
    token: str,
    chat_id: str,
    transport: Transport | None = None,
    max_pages: int = 40,
    base_url: str = BASE_URL,
) -> list[dict[str, Any]]:
    """Group message history, newest first (follows page_token, page_size 50).

    items[].mentions is a structured array of {name, id(open_id)} in the
    CALLING app's namespace; items[].sender.id is the sender's open_id in the
    same namespace.
    """
    items: list[dict[str, Any]] = []
    page_token: str | None = None
    call = transport or _default_transport
    for _ in range(max_pages):
        url = (
            f"{base_url}/open-apis/im/v1/messages?container_id_type=chat"
            f"&container_id={chat_id}&sort_type=ByCreateTimeDesc&page_size=50"
        )
        if page_token:
            url += f"&page_token={page_token}"
        status, body = call("GET", url, {"Authorization": f"Bearer {token}"}, None)
        data = _check(status, body).get("data") or {}
        items.extend(data.get("items") or [])
        page_token = (data.get("page_token") or "").strip() or None
        if not data.get("has_more") or not page_token:
            break
    return items


def fetch_chat_owner_id(
    token: str, chat_id: str, transport: Transport | None = None, base_url: str = BASE_URL
) -> str | None:
    """The group owner's open_id in the calling app's namespace (chats/{id})."""
    status, body = (transport or _default_transport)(
        "GET",
        f"{base_url}/open-apis/im/v1/chats/{chat_id}?user_id_type=open_id",
        {"Authorization": f"Bearer {token}"},
        None,
    )
    data = _check(status, body).get("data") or {}
    owner_id = data.get("owner_id")
    return str(owner_id) if owner_id else None


def one_click_auth_url(app_id: str, scope: str, base_url: str = BASE_URL) -> str:
    """The one-click authorization link for a missing scope (no secret in it)."""
    return f"{base_url}/app/{app_id}/auth?q={scope}&op_from=openapi&token_type=tenant"
