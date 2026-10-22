"""Open ID extraction and SOUL.md update utilities."""

from __future__ import annotations

import os
import re
from pathlib import Path

from hermes_multi_agent_team.utils.profile import read_soul


def extract_open_ids(log_path: str | Path) -> dict[str, set[str]]:
    """Extract Feishu open_ids from a gateway log file.

    Scans the log for sender=bot:ou_xxx and sender=user:ou_xxx patterns.
    Also attempts to extract associated display names from nearby context.

    Returns:
        Dict mapping role ('bot' or 'user') to a set of open_id strings.
    """
    log_path = Path(log_path)
    if not log_path.exists():
        return {"bot": set(), "user": set()}

    bots: set[str] = set()
    users: set[str] = set()

    pattern = re.compile(r"sender=(bot|user):(ou_\w+)")

    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            for match in pattern.finditer(line):
                role, oid = match.group(1), match.group(2)
                if role == "bot":
                    bots.add(oid)
                else:
                    users.add(oid)
    except OSError:
        pass

    return {"bot": bots, "user": users}


def extract_open_id_with_names(log_path: str | Path) -> dict[str, dict[str, str]]:
    """Extract open_ids and attempt to pair them with display names.

    Looks for patterns like:
      sender=user:ou_xxx ... name=DisplayName
      sender=bot:ou_xxx ... name=DisplayName

    Returns:
        Dict with 'bot' and 'user' keys, each mapping open_id → display_name (or empty str).
    """
    log_path = Path(log_path)
    if not log_path.exists():
        return {"bot": {}, "user": {}}

    bots: dict[str, str] = {}
    users: dict[str, str] = {}

    sender_pattern = re.compile(r"sender=(bot|user):(ou_\w+)")
    name_pattern = re.compile(r"name=([^\s,]+)")

    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            sender_match = sender_pattern.search(line)
            if sender_match:
                role = sender_match.group(1)
                oid = sender_match.group(2)
                name_match = name_pattern.search(line)
                display_name = name_match.group(1) if name_match else ""
                target = bots if role == "bot" else users
                if oid not in target or (display_name and not target[oid]):
                    target[oid] = display_name
    except OSError:
        pass

    return {"bot": bots, "user": users}


# Real open_id inside an <at> tag: "ou_" + alphanumerics, but never a
# placeholder ("ou_xxx…" is not a real id; real Feishu ids are hex-ish).
_AT_TAG_RE = re.compile(r'<at user_id="(ou_[A-Za-z0-9]+)">([^<]+)</at>')


def harvest_open_ids(soul_text: str) -> dict[str, str]:
    """Extract name → open_id pairs from a SOUL.md's <at> tags.

    Placeholders ("ou_xxx…") are skipped. When the same name carries
    different ids across tags, the first occurrence wins — within one team
    the same name is always the same agent, and ids only disagree when a
    fill went stale.
    """
    mapping: dict[str, str] = {}
    for open_id, name in _AT_TAG_RE.findall(soul_text):
        if open_id.startswith("ou_xxx"):
            continue
        mapping.setdefault(name, open_id)
    return mapping


def harvest_own_soul_open_ids(profile_name: str) -> dict[str, str]:
    """name → open_id from ONE profile's own SOUL <at> tags, placeholders skipped.

    Re-renders (init re-run, add/remove-member) preserve each SOUL's own ids
    PER PROFILE: an open_id is only valid in the Feishu app that observed it,
    so profile P's SOUL holds P's app's namespace for every name, and merging
    several profiles' SOULs into one global name→id map (last one wins) would
    write another app's namespace into every SOUL — the map to re-apply after
    re-rendering P is P's OWN pre-render harvest, never anyone else's.
    """
    soul = read_soul(profile_name)
    return harvest_open_ids(soul) if soul else {}


# ---------------------------------------------------------------------------
# Mention-gated mode (FEISHU_REQUIRE_MENTION=true)
#
# Inbound admission rejects non-@-messages before they are logged, so
# sender=bot lines never accumulate and the classic extraction below finds
# nothing. What DOES accumulate is the adapter's inbound line:
#
#   [Feishu] Inbound group message received: id=om_xxx type=text
#   chat_id=oc_xxx sender=user:ou_xxx
#   text='[Mentioned: P酱(sc) (open_id=ou_xxx), U酱(sc) (open_id=ou_yyy), ]\n\n正文'
#
# whose [Mentioned:] entries carry open_ids in the RECEIVING app's namespace —
# exactly the ids this profile's own SOUL needs. Parsing pitfalls (verified
# against real logs): the first entry sits right after the body's opening
# quote (text='[Mentioned: " or text="[Mentioned: " — Hermes logs text=%r, so
# a body containing a single quote renders double-quoted);
# entry names are verbatim agent names and may THEMSELVES contain
# parentheses ("U酱(sc)" — the suffix is a deliberate, per-project part of
# the name, NOT a tenant marker to strip), so the entry name is everything
# before the literal " (open_id=" marker and nothing is normalized away;
# "@all" entries have no open_id; the text is truncated (~120 chars) so the
# last entry may be cut mid-id (an incomplete entry simply fails to match
# and is skipped).
# ---------------------------------------------------------------------------

# Segment: from "[Mentioned: " to the first "]" OR end of line — a truncated
# line has no closing "]" and must not swallow the NEXT line's mentions.
_MENTION_SEGMENT_RE = re.compile(r"\[Mentioned:\s*((?:[^\]\n])*)")
# Entry tail: a complete entry ENDS with " (open_id=ou_xxx)" — anchored to the
# piece's end so the name may itself contain commas (team_config allows them;
# only "<>" and newlines are rejected). Incomplete tails (a truncated last
# entry cut mid-id) do not match and are skipped.
_MENTION_ENTRY_RE = re.compile(r"^(.*?)\s*\(open_id=(ou_[0-9A-Za-z]+)\)$")
_INBOUND_LINE_MARKERS = ("Inbound", "received")
_INBOUND_GROUP_RE = re.compile(r"Inbound\s+group\s+message\s+received")
_INBOUND_CHAT_ID_RE = re.compile(r"chat_id=(oc_[0-9A-Za-z]+)")
_INBOUND_SENDER_RE = re.compile(r"sender=(bot|user):(ou_[0-9A-Za-z]+)")
# Hermes logs the body via repr (text=%r): a body whose first ~120 chars
# contain a single quote renders as text="…" with DOUBLE quotes, so the
# body's opening quote is either ' or " — never assume the literal text='.
_TEXT_QUOTE_RE = re.compile(r"text=(['\"])")


def _inbound_lines(log_text: str) -> list[str]:
    """Only the adapter's inbound metadata lines ("… Inbound … received: …").

    chat_id=/sender= carry per-message metadata, but those same tokens can
    appear inside a message body (text='… chat_id=… sender=user:…') — a body
    must never take part in "which chat / which sender" decisions, so every
    consumer below scans these marked lines only, cut at the body's start
    (whichever quote style repr chose). A line the cut leaves intact (no
    ``text=`` at all) is metadata-only by construction.
    """
    lines: list[str] = []
    for line in log_text.splitlines():
        if all(m in line for m in _INBOUND_LINE_MARKERS):
            lines.append(_TEXT_QUOTE_RE.split(line, 1)[0])
    return lines


def extract_mention_ids(log_text: str) -> dict[str, str]:
    """name → open_id from a message's OWN [Mentioned:] header — the receiving
    app's namespace.

    Only the adapter's inbound lines ("… Inbound … received: …") are parsed,
    and only the segment sitting IMMEDIATELY after the line's FIRST ``text=``
    quote (single OR double — Hermes logs ``text=%r``) is adapter-rendered
    mention metadata; anything else is message CONTENT — a ``[Mentioned: …]``
    (or even a whole adapter line with its own ``text='``) pasted into the
    body, or a QUOTED message's text logged on a non-inbound line (e.g.
    ``reply_to_text='[Mentioned: …]'``), is another observation and must not
    leak its ids into this SOUL ("only ids this app observed").

    Names are returned VERBATIM (they may contain parentheses — "U酱(sc)"
    is a complete agent name whose suffix is part of the project's naming, not a tenant marker — or COMMAS, which team_config permits), so they match
    SOUL.md @tag names as-is. Entries are split on the ", " separator and a
    piece with no trailing "(open_id=…)" is treated as a comma-name fragment
    and re-joined with the next piece, never as a standalone name ("A,B"
    must not fill member "B"). The first entry wins on repeats (within one
    app's namespace a name maps to one id; disagreement means a stale fill).
    """
    mapping: dict[str, str] = {}
    for line in log_text.splitlines():
        if not all(m in line for m in _INBOUND_LINE_MARKERS):
            continue  # not an adapter inbound line — no mention metadata here
        quoted = _TEXT_QUOTE_RE.split(line, 1)  # first quote start only — pastes come later
        if len(quoted) < 3:
            continue
        segment = _MENTION_SEGMENT_RE.match(quoted[2])
        if not segment:
            continue
        # Pieces between ", " separators; an entry that does not END with
        # "(open_id=…)" is either "@all", a truncated tail, or the leading
        # fragment of a comma-containing name — accumulate the latter,
        # drop the rest.
        pending: list[str] = []
        for piece in segment.group(1).split(", "):
            if piece.strip() == "@all":
                pending = []  # the all-members marker belongs to no name
                continue
            entry = _MENTION_ENTRY_RE.match(piece)
            if entry:
                name = ", ".join([*pending, entry.group(1)]).strip()
                mapping.setdefault(name, entry.group(2))
                pending = []
            else:
                pending.append(piece)
    return mapping


def _read_log_text(log_path: str | Path) -> str:
    log_path = Path(log_path)
    if not log_path.exists():
        return ""
    try:
        return log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def own_bot_sender_ids(log_path: str | Path) -> set[str]:
    """Bot sender ids seen on OUTBOUND (non-inbound) log lines only — the
    candidates for this profile's OWN bot id.

    Inbound metadata lines carry ``sender=bot:ou_teammate`` when a teammate
    bot writes to this bot — that id belongs to the TEAMMATE (observed in
    this app's namespace, but not this bot's own). Treating it as "own"
    filled a member's @-line with a teammate's id, which idempotent re-runs
    froze in and the re-render harvest then propagated into re-rendered
    SOULs. Subtracting every bot id that appears on an inbound line leaves
    only ids this adapter itself emitted (outbound ``sender=bot:`` lines,
    free mode).
    """
    bots = set(extract_open_id_with_names(log_path).get("bot", {}).keys())
    if not bots:
        return set()
    inbound_bots = {
        oid
        for line in _inbound_lines(_read_log_text(log_path))
        for role, oid in _INBOUND_SENDER_RE.findall(line)
        if role == "bot"
    }
    return bots - inbound_bots


def latest_chat_id(log_path: str | Path) -> str | None:
    """The most recent GROUP chat_id (oc_xxx) in a gateway log, if any.

    Only inbound adapter metadata lines count — a chat_id quoted inside a
    message body (text='…') is data, not metadata, and must not win. Group
    lines ("Inbound group message received") beat ANY newer p2p line: the
    caller reads the team GROUP's history, and a private chat's id would
    point that request at the wrong conversation. A p2p id is used only
    when no group line exists at all (a bot that has only ever seen DMs).
    """
    group_ids: list[str] = []
    any_ids: list[str] = []
    for line in _inbound_lines(_read_log_text(log_path)):
        m = _INBOUND_CHAT_ID_RE.search(line)
        if m:
            any_ids.append(m.group(1))
            if _INBOUND_GROUP_RE.search(line):
                group_ids.append(m.group(1))
    chosen = group_ids or any_ids
    return chosen[-1] if chosen else None


def distinct_user_sender_ids(log_path: str | Path) -> list[str]:
    """The distinct human sender ids (sender=user:ou_xxx) on inbound lines,
    oldest first. Bot senders are excluded; message-body occurrences of
    "sender=user:…" are not metadata and never counted.

    Filling SOUL's @主人 line from the log assumes "the human who talked to
    this bot is the owner" — an assumption that only holds while this list
    has exactly ONE entry; with several humans the log cannot tell which one
    owns the team and the caller must skip the fill (a wrong guess would be
    frozen in by idempotent re-runs and is exempt from verify). The
    group-info API owner (collect-ids --via-api) has no such ambiguity.
    """
    ids: dict[str, None] = {}
    for line in _inbound_lines(_read_log_text(log_path)):
        for role, oid in _INBOUND_SENDER_RE.findall(line):
            if role == "user":
                ids.setdefault(oid, None)
    return list(ids)


def atomic_write_text(path: str | Path, content: str) -> None:
    """Write text so a failure never damages the file already on disk.

    write_text truncates FIRST, so a mid-write failure (ENOSPC, EACCES) could
    leave a cut-down file; a sibling temp file + os.replace keeps the
    original intact, and the write error propagates to the caller (every
    caller reports it per profile and moves on).

    - The temp file inherits the original's permission bits — os.replace
      swaps the inode, so without this a 0600 SOUL would silently become the
      umask default (e.g. 0664, group/other-readable). A first write (no
      file yet) uses the process default.
    - A SYMLINK is refused rather than replaced: replacing would turn the
      link into a plain file while the TARGET keeps its stale content —
      raise so the caller can tell the user.
    - A read-only file (0444) in a writable directory is still replaced
      (rename needs no file write permission), preserving its mode; an
      unwritable DIRECTORY fails cleanly instead (the price of never
      truncating in place).
    """
    path = Path(path)
    if path.is_symlink():
        raise OSError(
            f"{path} is a symlink — refusing to replace it; "
            "write the link target or remove the link"
        )
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        tmp_path.write_text(content, encoding="utf-8")
        if path.exists():
            os.chmod(tmp_path, path.stat().st_mode & 0o777)
        os.replace(tmp_path, path)
    except OSError:
        try:
            tmp_path.unlink()
        except OSError:
            pass  # best-effort cleanup of the leftover temp file
        raise


# Any ou_ id (placeholders contain underscores — "ou_xxx_fe" — which the
# real-id-only _AT_TAG_RE deliberately does not match).
_ANY_AT_TAG_RE = re.compile(r'<at user_id="(ou_[^"]*)">([^<]+)</at>')


def _apply_placeholder_fill(
    content: str, mapping: dict[str, str], exempt_names: set[str] | frozenset[str]
) -> tuple[str, int, int, set[str]]:
    """The placeholder-only fill rule applied to TEXT (see fill_soul…)."""
    filled = 0
    filled_names: set[str] = set()

    def _replace(match: re.Match) -> str:
        nonlocal filled
        current_id, name = match.group(1), match.group(2)
        mapped = mapping.get(name)
        if current_id.startswith("ou_xxx") and mapped and mapped != current_id:
            filled += 1
            filled_names.add(name)
            return f'<at user_id="{mapped}">{name}</at>'
        return match.group(0)

    new_content = _ANY_AT_TAG_RE.sub(_replace, content)
    remaining = sum(
        1
        for open_id, name in _ANY_AT_TAG_RE.findall(new_content)
        if open_id.startswith("ou_xxx") and name not in exempt_names
    )
    return new_content, filled, remaining, filled_names


def fill_placeholders_in_text(content: str, mapping: dict[str, str]) -> tuple[str, int]:
    """Apply a harvested id map to freshly RENDERED text before it is written.

    The re-render flows (init re-run, add/remove-member, roster patches)
    render a SOUL whose @-lines are all placeholders, then re-apply the
    profile's OWN harvested ids. Doing that on the content string — instead
    of write-then-fill on the file — closes the two-step window: a failed
    write can no longer leave a placeholder-only SOUL whose collected ids
    were lost (the next harvest would read only placeholders). Matching goes
    by <at> TAG, so custom section headings work like the bundled one.
    Returns (new_content, number of ids applied).
    """
    new_content, filled, _, _ = _apply_placeholder_fill(content, mapping, frozenset())
    return new_content, filled


def fill_soul_placeholder_open_ids(
    soul_path: str | Path, mapping: dict[str, str], exempt_names: set[str] | frozenset[str] = ()
) -> tuple[int, int, set[str]]:
    """Idempotent fill: replace ONLY placeholder <at> tags with mapped ids.

    Real ids already in the file are never touched — collect-ids may run
    against SOULs with hand-filled ids, and a re-run must not rewrite them
    (only exact no-ops). Re-renders use the same rule via
    fill_placeholders_in_text: a fresh render leaves only placeholders, so
    the placeholder-only rule is exact, and matching goes by <at> TAG —
    custom section headings (e.g. 【飞书@格式】) work exactly like the
    bundled 【飞书@方式】. Returns (filled tag count, remaining non-exempt
    placeholders, names actually written) so the caller can report a source
    breakdown that matches the filled count — not every observed name exists
    in this SOUL.

    ``exempt_names`` lists roster names whose placeholders are BY DESIGN and
    exempt from the remaining-count — the same set verify exempts (主人 and
    the render-only hub): counting them would report "N placeholders remain"
    for a SOUL verify passes, forever. The write (when anything changed) is
    atomic — see atomic_write_text.
    """
    soul_path = Path(soul_path)
    if not soul_path.exists():
        return (0, 0, set())
    try:
        content = soul_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return (0, 0, set())

    new_content, filled, remaining, filled_names = _apply_placeholder_fill(
        content, mapping, exempt_names
    )
    if new_content != content:
        atomic_write_text(soul_path, new_content)
    return (filled, remaining, filled_names)
