"""collect-ids command — fill SOUL.md open_ids, per profile.

Namespacing rule (the core correctness invariant): an open_id is only valid
in the app that observed it. Profile P's SOUL is therefore filled ONLY with
ids observed by P — from P's own Feishu app credentials via the group
message history API (--via-api), from [Mentioned:] entries in P's own
gateway log (mention-gated mode), or from P's own log's sender=bot line
(free mode). The historical "merge everyone into one global mapping" design
was wrong under per-app id isolation and is gone.

Fills are idempotent: only placeholder (<at user_id="ou_xxx…">) tags are
touched, so re-running never rewrites hand-filled or already-collected ids.
"""

from __future__ import annotations

import http.client
import shlex

import click

from hermes_multi_agent_team.utils.feishu_api import (
    FeishuApiError,
    _default_transport,
    base_url_for,
    fetch_chat_messages,
    fetch_chat_owner_id,
    get_tenant_token,
    one_click_auth_url,
)
from hermes_multi_agent_team.utils.open_id import (
    _read_log_text,
    distinct_user_sender_ids,
    extract_mention_ids,
    fill_soul_placeholder_open_ids,
    harvest_open_ids,
    latest_chat_id,
    own_bot_sender_ids,
)
from hermes_multi_agent_team.utils.profile import (
    get_profile_dir,
    is_standalone_profile,
    list_name_ambiguous_profiles,
    list_team_profiles,
    read_env,
    read_soul,
    read_team_metadata,
    team_metadata_corrupt,
)

# Legacy fallback for teams created before per-profile metadata existed:
# profile suffix → the name used in SOUL.md @tags.
ROLE_NAME_MAP: dict[str, str] = {
    "pm": "P酱",
    "fe": "F仔",
    "be": "B叔",
    "qa": "Q宝",
    "ui": "U酱",
}

OWNER_TAG_NAME = "主人"


def _agent_name_for_profile(profile_name: str) -> str | None:
    """The SOUL.md @tag name of this profile's agent, or None if unknown.

    Prefers the .hermes-team.json metadata init wrote (custom roles, the
    coordinator); falls back to the builtin suffix table for legacy teams.
    """
    metadata = read_team_metadata(profile_name)
    name = metadata.get("name")
    if isinstance(name, str) and name:
        return name
    parts = profile_name.rsplit("-", 1)
    if len(parts) == 2 and parts[1] in ROLE_NAME_MAP:
        return ROLE_NAME_MAP[parts[1]]
    return None


def _api_ids_for_profile(
    profile_name: str,
    chat_id: str | None,
    transport=None,
) -> tuple[dict[str, str], str | None]:
    """Ids via this profile's own app credentials (its namespace).

    Returns (mapping name→id, note-or-None). A missing-scope error prints
    the one-click auth link for THIS app and degrades to a note — the caller
    falls back to log parsing. Credentials are never echoed. ``transport``
    defaults to the real HTTP transport (None means default, never "none").
    """
    env = read_env(profile_name)
    app_id = (env.get("FEISHU_APP_ID") or "").strip()
    app_secret = (env.get("FEISHU_APP_SECRET") or "").strip()
    if not app_id or not app_secret:
        return {}, "no Feishu credentials in .env — run configure first; using logs only"

    if not chat_id:
        return {}, "no chat_id: none in this profile's log — pass --chat-id; using logs only"

    transport = transport or _default_transport
    # Lark tenants are served by a different API host than feishu.cn —
    # follow the profile's own FEISHU_DOMAIN so its credentials work.
    base_url = base_url_for(env.get("FEISHU_DOMAIN"))

    try:
        token = get_tenant_token(app_id, app_secret, transport=transport, base_url=base_url)
        mapping: dict[str, str] = {}
        for item in fetch_chat_messages(token, chat_id, transport=transport, base_url=base_url):
            for mention in item.get("mentions") or []:
                name = (mention.get("name") or "").strip()
                open_id = (mention.get("id") or "").strip()
                if name and open_id:
                    mapping.setdefault(name, open_id)
    except FeishuApiError as e:
        # Only the messages endpoint justifies the group_msg fallback — it
        # just succeeded moments ago when the error comes from chats below.
        scope = e.missing_scope("im:message.group_msg")
        if scope:
            click.echo(
                f"  🔑 {profile_name}: app lacks scope '{scope}' — open this link to "
                f"grant it, then re-run:\n     {one_click_auth_url(app_id, scope, base_url)}"
            )
            return {}, f"API scope missing ({scope}); using logs only"
        return {}, f"API error (HTTP {e.status} code={e.code}); using logs only"
    except OSError as e:
        # Offline/DNS/timeout — the API route is a convenience, not a gate.
        return {}, f"network error ({e.__class__.__name__}); using logs only"
    except (http.client.HTTPException, ValueError) as e:
        # Malformed request URL (e.g. a bad --chat-id reaching this layer
        # past the CLI's validation; InvalidURL is an HTTPException, NOT an
        # OSError) — same "API unusable → use logs" degradation.
        return {}, f"API request failed ({e.__class__.__name__}); using logs only"

    # Owner lookup (chats info, needs im:chat:readonly — a DIFFERENT scope
    # than the messages call above) is best-effort: failing it must not
    # discard the mentions already collected; report honestly and move on.
    # The wording only states the failure — it must NOT predict the @主人
    # line's state: this helper does not know the SOUL, and the log fallback
    # in the caller may still fill a placeholder @主人 later (so "left
    # unchanged" could contradict the very next "sources: log=1" line), or
    # the line may already hold a real id.
    try:
        owner = fetch_chat_owner_id(token, chat_id, transport=transport, base_url=base_url)
    except (FeishuApiError, OSError, http.client.HTTPException, ValueError) as e:
        if isinstance(e, FeishuApiError):
            detail = f"HTTP {e.status} code={e.code}"
        elif isinstance(e, OSError):
            detail = "network"
        else:
            detail = e.__class__.__name__
        click.echo(
            f"  ⚠️  {profile_name}: could not fetch chat owner for @{OWNER_TAG_NAME} ({detail})"
        )
    else:
        if owner:
            mapping.setdefault(OWNER_TAG_NAME, owner)
    return mapping, None


def collect_team_ids(
    prefix: str,
    via_api: bool = False,
    chat_id: str | None = None,
    transport=None,
) -> None:
    """Fill each team profile's SOUL.md open_ids from its own observations.

    ``transport`` is a test seam only; the CLI path leaves it as None, which
    is normalized to the real HTTP transport — it must never be passed
    through as a literal None into the API layer.
    """
    transport = transport or _default_transport
    profiles = list_team_profiles(prefix)
    # Legacy profiles whose names could belong to a LONGER prefix are
    # excluded from the listing — their ids must not be merged into this
    # team's mapping nor their SOULs rewritten; say why instead of silence.
    for name in list_name_ambiguous_profiles(prefix):
        click.echo(
            f"  ⚠️  {name}: name matches '{prefix}-…' but carries no recorded prefix — "
            f"it may belong to team '{name.rsplit('-', 1)[0]}'; skipped. Re-init it "
            "under its own team to record the prefix and remove the ambiguity."
        )
    # Profiles kept on disk via `remove-member --keep-profile` carry a
    # "removed" marker: they are no longer team members, so their logs must
    # not feed the mapping nor their SOULs be rewritten.
    profiles = [p for p in profiles if not read_team_metadata(p).get("removed")]

    if not profiles:
        raise click.ClickException(
            f"❌ No profiles found with prefix '{prefix}'. Run 'hermes-team init' first."
        )

    click.echo(f"\n🔍 Collecting open_ids for {len(profiles)} profile(s)")
    if via_api:
        click.echo("   🌐 via-api mode: reading group history with each profile's own app")
    else:
        click.echo(
            "   💡 mention-gated team? add --via-api to read group history via the API "
            "(complete mentions, no new messages needed)"
        )

    # Standalone bots (new-bot) carry no roster; they are not team members.
    # Profiles with unreadable metadata fail closed into the same skip.
    standalone = [p for p in profiles if is_standalone_profile(p)]
    corrupt = [p for p in profiles if p not in standalone and team_metadata_corrupt(p)]
    for name in standalone:
        click.echo(f"  ⏭️  {name}: standalone bot, skipping")
    for name in corrupt:
        click.echo(
            f"  ⚠️  {name}: unreadable .hermes-team.json — skipping (fix the file or "
            "remove the profile)"
        )
    skipped = set(standalone) | set(corrupt)
    profiles = [p for p in profiles if p not in skipped]
    if not profiles:
        click.echo("\nℹ️  No team profiles with this prefix — nothing to collect.")
        return

    # Members rendered from the roster-free bot template have no
    # 【飞书@方式】 section by design — nothing to fill, ever.
    roster_free = {p for p in profiles if read_team_metadata(p).get("template") == "bot.md.j2"}
    for name in sorted(roster_free):
        click.echo(f"  ⏭️  {name}: roster-free bot template — nothing to fill")
    targets = [p for p in profiles if p not in roster_free]
    click.echo()

    total_filled = 0
    profiles_with_gaps = 0

    for profile_name in targets:
        log_path = get_profile_dir(profile_name) / "logs" / "gateway.log"
        log_text = _read_log_text(log_path)

        # The SOUL gates the rest: without it there is nothing to fill and
        # no point parsing this profile's log. No @-section HEADING is
        # required — fill targets placeholder <at> tags wherever they are,
        # and custom templates name the section differently (the real
        # whisage team uses 【飞书@格式】); a SOUL with no <at> tags at all
        # reports as "nothing to fill" after the sources run.
        soul_path = get_profile_dir(profile_name) / "SOUL.md"
        soul_text = read_soul(profile_name)
        if not soul_text:
            click.echo(f"  ⚠️  {profile_name}: no SOUL.md found")
            continue
        # Names whose @-line in THIS SOUL already holds a real id
        # (hand-filled, or a previous collect run): those lines are done —
        # the log heuristics below must neither run for them nor warn
        # "left as-is" about lines that are in fact filled.
        hand_filled = harvest_open_ids(soul_text)

        # Per-profile mapping: name → (open_id, source). First source to
        # know a name wins; priority is api > mention > sender by
        # construction (api filled first below).
        mapping: dict[str, str] = {}
        sources: dict[str, str] = {}

        def _add(
            name: str | None,
            open_id: str | None,
            source: str,
            _mapping: dict[str, str] = mapping,
            _sources: dict[str, str] = sources,
        ) -> None:
            # Default-arg binding: _add must not capture the loop's mapping/
            # sources (B023) even though it is only ever called in-iteration.
            if name and open_id and name not in _mapping:
                _mapping[name] = open_id
                _sources[name] = source

        if via_api:
            api_ids, api_note = _api_ids_for_profile(
                profile_name, chat_id or latest_chat_id(log_path), transport
            )
            for name, open_id in api_ids.items():
                _add(name, open_id, "api")
            if api_note:
                click.echo(f"  ⚠️  {profile_name}: {api_note}")
        elif not log_text:
            click.echo(f"  ⚠️  {profile_name}: no gateway.log — nothing to parse")

        # [Mentioned:] entries in this profile's inbound log — the receiving
        # app's namespace, exactly what this SOUL needs.
        for name, open_id in extract_mention_ids(log_text).items():
            _add(name, open_id, "mention")

        # Own bot id from OUTBOUND sender=bot lines (free mode): the only id
        # in this profile's log that is this agent's own, in its own
        # namespace. Inbound sender=bot lines are TEAMMATE bots (excluded by
        # own_bot_sender_ids). Only needed when neither the API route nor a
        # hand-filled SOUL already resolved the agent's own name — otherwise
        # the log heuristic (and its ambiguity warning) would badmouth a
        # line that is in fact filled.
        agent_name = _agent_name_for_profile(profile_name)
        if agent_name not in mapping and not hand_filled.get(agent_name):
            own_bots = own_bot_sender_ids(log_path)
            if len(own_bots) == 1:
                _add(agent_name, next(iter(own_bots)), "sender")
            elif len(own_bots) > 1:
                click.echo(
                    f"  ⚠️  {profile_name}: {len(own_bots)} bot ids in its log — cannot tell "
                    "which is its own; own @-line left as-is"
                )

        # Owner's id in this app's namespace (log fallback; the group-info
        # API owner above wins). The log can only prove "this ONE human
        # talked to the bot" — with several humans observed there is no way
        # to tell which is 主人, so skip rather than freeze in a guess. When
        # the API or a hand-filled SOUL already resolved 主人 there is
        # nothing to decide: no warning (it would claim "left as-is" about
        # a filled line).
        if OWNER_TAG_NAME not in mapping and not hand_filled.get(OWNER_TAG_NAME):
            user_senders = distinct_user_sender_ids(log_path)
            if len(user_senders) == 1:
                _add(OWNER_TAG_NAME, user_senders[0], "log")
            elif len(user_senders) > 1:
                click.echo(
                    f"  ⚠️  {profile_name}: {len(user_senders)} different human senders in "
                    f"its log — cannot tell which is @{OWNER_TAG_NAME}; left as-is "
                    "(use --via-api or fill it by hand)"
                )

        # Placeholders exempt BY DESIGN (same rule as verify's open_ids
        # check): the owner line and the render-only hub — counting them
        # would report gaps on SOULs verify passes.
        meta = read_team_metadata(profile_name)
        exempt_names = {OWNER_TAG_NAME}
        hub_raw = meta.get("hub")
        if isinstance(hub_raw, dict) and isinstance(hub_raw.get("name"), str):
            exempt_names.add(hub_raw["name"])
        elif "hub" not in meta:
            exempt_names.add("M总")  # legacy teams rendered the builtin hub

        try:
            filled, remaining, filled_names = fill_soul_placeholder_open_ids(
                soul_path, mapping, exempt_names
            )
        except OSError as e:
            # Read errors above degrade silently ("nothing to fill"); a WRITE
            # error must not: the fills were NOT saved, and a bare traceback
            # would abort the remaining profiles. Report per profile, continue.
            click.echo(
                f"  ❌ {profile_name}: could not write SOUL.md ({e}) — its id(s) were "
                "NOT saved; fix the file's permissions/free space and re-run"
            )
            continue
        total_filled += filled
        if remaining:
            profiles_with_gaps += 1

        # Source breakdown of the ids ACTUALLY written to this SOUL (same
        # scale as `filled`), not of everything the sources observed — names
        # without a matching @-line in this SOUL are not part of the report.
        by_source = {
            src: sum(1 for name, s in sources.items() if s == src and name in filled_names)
            for src in ("api", "mention", "sender", "log")
        }
        parts = [f"{src}={n}" for src, n in by_source.items() if n]
        detail = f" (sources: {', '.join(parts)})" if parts else ""
        if "<at " not in soul_text:
            click.echo(f"  ℹ️  {profile_name}: no @-tags in SOUL.md — nothing to fill")
            continue
        gap = f", {remaining} placeholder(s) remain" if remaining else ", all filled ✅"
        click.echo(f"  ✅ {profile_name}: {filled} id(s) filled{gap}{detail}")

    click.echo(f"\n✅ Done! Filled {total_filled} open_id(s) across {len(targets)} profile(s)")
    if profiles_with_gaps:
        click.echo(f"   ⚠️  {profiles_with_gaps} profile(s) still have placeholders")
        click.echo(
            "   Tips: mentions in the group history cover them once the bots have been "
            "@-mentioned (--via-api); or ask those members to speak/@-mention in the group"
        )
    click.echo(f"\n📋 Next step: hermes-team verify --prefix {shlex.quote(prefix)}")
