"""Sleeper free API client for NFL/NBA player injury and status data.

No authentication required. The Sleeper API is publicly accessible.

fetch_sleeper_team_injuries() fetches all active players for a sport, filters
by team abbreviation, and returns injury-status dicts compatible with the
context_agent pipeline (keys: player_name, status, position, team).

Endpoints used:
    GET https://api.sleeper.app/v1/players/{sport}
    Returns ALL players with: full_name, status, injury_status, team, position

Status normalization:
    Sleeper "injury_status" → canonical status:
      "Out"          → "Out"
      "Questionable" → "Questionable"
      "Doubtful"     → "Doubtful"
      "IR"           → "Out"
      "PUP-R"        → "Out"
      "Sus"          → "Out"
    Players with no injury_status and not on IR are excluded.
"""
from __future__ import annotations

from typing import Any

from httpx import AsyncClient as _AsyncClient
import structlog

log = structlog.get_logger()

_SLEEPER_BASE = "https://api.sleeper.app/v1"

_SLEEPER_STATUS_MAP: dict[str, str] = {
    "Out": "Out",
    "Questionable": "Questionable",
    "Doubtful": "Doubtful",
    "Injured_Reserve": "Out",
    "IR": "Out",
    "PUP-R": "Out",
    "Sus": "Out",
}


async def fetch_sleeper_team_injuries(
    sport: str,
    team_abbr: str,
    timeout: float = 12.0,
) -> list[dict[str, str]]:
    """Fetch current injury status for all players on a team via Sleeper API.

    Makes a single GET /players/{sport} call (returns all players for the sport)
    then filters by team. This avoids per-player API calls and keeps rate usage low.

    Args:
        sport: "nfl" or "nba"
        team_abbr: Team abbreviation to filter on (e.g. "KC", "LAL").
                   Comparison is case-insensitive.
        timeout: HTTP timeout in seconds.

    Returns:
        List of dicts — each with keys: player_name, status, position, team.
        Only players with a known injury/IR status are included.
        Empty list if the API is unreachable or the team has no injuries.
    """
    url = f"{_SLEEPER_BASE}/players/{sport}"
    try:
        async with _AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            players: dict[str, Any] = resp.json()
    except Exception as exc:
        log.warning(
            "sleeper_fetch_failed",
            sport=sport,
            team=team_abbr,
            error=str(exc),
        )
        return []

    injuries: list[dict[str, str]] = []
    for _pid, player in players.items():
        if not isinstance(player, dict):
            continue
        player_team: str = (player.get("team") or "").upper()
        if player_team != team_abbr.upper():
            continue

        injury_status: str | None = player.get("injury_status")
        sleeper_status: str = player.get("status", "") or ""

        canonical: str | None = None
        if injury_status and injury_status in _SLEEPER_STATUS_MAP:
            canonical = _SLEEPER_STATUS_MAP[injury_status]
        elif sleeper_status in _SLEEPER_STATUS_MAP:
            canonical = _SLEEPER_STATUS_MAP[sleeper_status]

        if canonical is None:
            continue

        full_name: str = (
            player.get("full_name")
            or f"{player.get('first_name', '')} {player.get('last_name', '')}".strip()
            or "Unknown"
        )
        position: str = player.get("position", "Unknown") or "Unknown"

        injuries.append({
            "player_name": full_name,
            "status": canonical,
            "position": position,
            "team": team_abbr.upper(),
        })

    log.info(
        "sleeper_injuries_fetched",
        sport=sport,
        team=team_abbr,
        injury_count=len(injuries),
    )
    return injuries
