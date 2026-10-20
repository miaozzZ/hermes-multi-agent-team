"""Open ID extraction and SOUL.md update utilities."""

from __future__ import annotations

import re
from pathlib import Path


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


def update_soul_md_open_ids(soul_path: str | Path, open_id_mapping: dict[str, str]) -> bool:
    """Update the 【飞书@方式】 section in a SOUL.md file with open_id mappings.

    Args:
        soul_path: Path to SOUL.md
        open_id_mapping: Dict mapping name/nickname → open_id (e.g. {'P酱': 'ou_xxx'})

    Returns:
        True if the section was found and updated, False otherwise.
    """
    soul_path = Path(soul_path)
    if not soul_path.exists():
        return False

    content = soul_path.read_text(encoding="utf-8")

    # Find the 【飞书@方式】 section
    section_start = content.find("【飞书@方式】")
    if section_start == -1:
        return False

    # Find the end of the section (next heading or end of file)
    next_heading = re.search(r"\n【[^】]+】", content[section_start + 1 :])
    if next_heading:
        section_end = section_start + 1 + next_heading.start()
    else:
        section_end = len(content)

    section = content[section_start:section_end]

    # Build the updated section
    # Keep the heading, replace at tags
    lines = section.split("\n")
    new_lines: list[str] = []

    for line in lines:
        # Match existing <at user_id="ou_xxx">Name</at> patterns
        at_pattern = re.compile(r'<at user_id="ou_[^"]*">([^<]+)</at>')
        match = at_pattern.search(line)
        if match:
            name = match.group(1)
            if name in open_id_mapping:
                new_line = at_pattern.sub(
                    f'<at user_id="{open_id_mapping[name]}">{name}</at>',
                    line,
                )
                new_lines.append(new_line)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    new_section = "\n".join(new_lines)
    new_content = content[:section_start] + new_section + content[section_end:]

    soul_path.write_text(new_content, encoding="utf-8")
    return True
