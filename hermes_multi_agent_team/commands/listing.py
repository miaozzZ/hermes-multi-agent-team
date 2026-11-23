"""list command — one overview of every team and standalone bot on this machine.

Teams are grouped by the prefix recorded in each profile's metadata. Profiles
without usable metadata (none at all, or none with a recorded prefix) fall
back to name-based grouping in a separate legacy section. Standalone bots
(new-bot) and kept-but-removed profiles (remove-member --keep-profile, shown
in their own section and excluded from team member counts) also get their own
sections. Every section renders the same per-profile detail table — model,
gateway visibility, Feishu connection, masked App ID, last activity — so
`list` doubles as a "what is running on this host" inventory without a
per-team `status --prefix` round-trip.
"""

from __future__ import annotations

import click

from hermes_multi_agent_team.utils.gateway import gateway_status
from hermes_multi_agent_team.utils.profile import (
    get_profiles_dir,
    list_all_profile_names,
    read_env,
    read_model_config,
    read_team_metadata,
    team_metadata_corrupt,
)

_PROFILE_COL_W = 20
_MODEL_COL_W = 22
_APP_ID_COL_W = 14
_LAST_ACTIVE_COL_W = 19
_TABLE_W = (
    _PROFILE_COL_W + _MODEL_COL_W + 2 + 6 + _APP_ID_COL_W + _LAST_ACTIVE_COL_W + 5
)


def _infer_prefix(profile_name: str) -> str:
    """Grouping key for profiles without recorded metadata."""
    parts = profile_name.rsplit("-", 1)
    return parts[0] if len(parts) == 2 else profile_name


def _row(cells: list[tuple[str, int]]) -> str:
    """One padded table line: (text, width) cells joined by single spaces."""
    return " ".join(text.ljust(width) for text, width in cells)


def _mask_app_id(app_id: str | None) -> str:
    """Masked App ID for display, matching status' masking rule."""
    if not app_id:
        return "—"
    return app_id[:6] + "****" + app_id[-4:] if len(app_id) > 10 else app_id


def _model_cell(name: str) -> str:
    """Model (and provider, when explicitly pinned) of one profile."""
    model, provider = read_model_config(name)
    if not model:
        return "<unset>"
    if provider and provider != "auto":  # auto = Hermes credential auto-detect
        return f"{model} ({provider})"
    return model


def _render_profile_table(
    rows: list[tuple[str, str]],
    gw_status: dict[str, dict],
    sublines: dict[str, str] | None = None,
) -> None:
    """One detail table for a group of profiles.

    rows are (display_name, profile_name): display_name may carry a suffix
    like "(removed, kept)" while profile_name is the lookup key for env/model/
    gateway state. sublines prints an indented note (e.g. a standalone bot's
    role description) under the matching profile's row.
    """
    indent = "     "
    click.echo(
        indent
        + _row(
            [
                ("Profile", _PROFILE_COL_W),
                ("Model", _MODEL_COL_W),
                ("GW", 2),
                ("Feishu", 6),
                ("App ID", _APP_ID_COL_W),
                ("Last Active", _LAST_ACTIVE_COL_W),
            ]
        )
    )
    click.echo(indent + "─" * _TABLE_W)
    for display, name in rows:
        gw = gw_status.get(name) or {}
        gw_icon = "🟢" if gw.get("pid") else "⚫"
        conn_icon = "✅" if gw.get("connected") else "❌"
        app_id = _mask_app_id(read_env(name).get("FEISHU_APP_ID"))
        last_active = str(gw.get("last_message_time") or "—")
        click.echo(
            indent
            + _row(
                [
                    (display, _PROFILE_COL_W),
                    (_model_cell(name), _MODEL_COL_W),
                    (gw_icon, 2),
                    (conn_icon, 6),
                    (app_id, _APP_ID_COL_W),
                    (last_active, _LAST_ACTIVE_COL_W),
                ]
            )
        )
        if sublines:
            desc = sublines.get(name, "")
            if desc:
                click.echo(f"{indent}  └ {desc}")


def run_list() -> None:
    """Show every team (by prefix) and standalone bot on this host."""
    profiles = list_all_profile_names()
    if not profiles:
        # Real path, not a hardcoded ~/.hermes: HERMES_HOME may point elsewhere.
        click.echo(f"ℹ️  No profiles under {get_profiles_dir()} — run `hermes-team new-team` first.")
        return

    teams: dict[str, list[str]] = {}
    legacy: dict[str, list[str]] = {}
    standalone: list[str] = []
    removed: dict[str, list[str]] = {}
    corrupt: list[str] = []

    for name in profiles:
        if team_metadata_corrupt(name):
            corrupt.append(name)
            continue
        meta = read_team_metadata(name)
        if meta.get("standalone"):
            standalone.append(name)
        elif meta.get("removed"):
            # Kept on disk by remove-member --keep-profile: no longer a team
            # member (excluded from the Teams counts), but still served by the
            # gateway — give it its own section, don't hide it.
            prefix = str(meta.get("prefix") or _infer_prefix(name))
            removed.setdefault(prefix, []).append(name)
        elif meta.get("prefix"):
            teams.setdefault(str(meta["prefix"]), []).append(name)
        else:
            # No metadata at all, or metadata without a recorded prefix (very
            # old or hand-written): best-effort grouping by profile name.
            legacy.setdefault(_infer_prefix(name), []).append(name)

    # One gateway_status round per profile, shared by the header count and
    # every detail table below.
    gw_status = {name: gateway_status(name) for name in profiles}
    running = sum(1 for gw in gw_status.values() if gw.get("pid"))
    click.echo(f"\n📋 {len(profiles)} profile(s) on this host ({running} gateway-visible)\n")

    if teams:
        click.echo("🏠 Teams")
        for prefix in sorted(teams):
            members = sorted(teams[prefix])
            click.echo(f"   {prefix}  ({len(members)} profile(s))")
            _render_profile_table([(m, m) for m in members], gw_status)
        click.echo()

    if removed:
        click.echo("🗑️  Removed from team, kept on disk (remove-member --keep-profile)")
        for prefix in sorted(removed):
            click.echo(f"   {prefix}")
            _render_profile_table(
                [(f"{name} (removed, kept)", name) for name in sorted(removed[prefix])],
                gw_status,
            )
        click.echo()

    if legacy:
        click.echo("🗂️  Legacy / unclassified (no/unusable metadata — grouped by name)")
        for prefix in sorted(legacy):
            click.echo(f"   {prefix}?")
            _render_profile_table([(n, n) for n in sorted(legacy[prefix])], gw_status)
        click.echo()

    if standalone:
        click.echo("🤖 Standalone bots (new-bot)")
        sublines = {name: str(read_team_metadata(name).get("role") or "").strip() for name in standalone}
        _render_profile_table([(n, n) for n in sorted(standalone)], gw_status, sublines)
        click.echo()

    if corrupt:
        click.echo("⚠️  Unreadable metadata (skipped by team commands)")
        for name in sorted(corrupt):
            click.echo(f"   {name}")
        click.echo()
