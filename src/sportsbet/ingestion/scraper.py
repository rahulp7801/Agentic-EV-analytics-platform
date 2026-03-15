"""ESPN Core API injury scraper for the Context Agent pipeline.

InjuryWeatherScraper fetches structured injury data from ESPN's undocumented
Core API and writes rows to the injury_reports table via asyncpg.

Design decisions (locked):
- ESPN Core API preferred over HTML scraping per RESEARCH.md (stable JSON,
  no Playwright required for injury data).
- parse_espn_injury_item uses .get() with "Unknown" fallback at every level —
  ESPN's API is undocumented and schema drift is expected.
- write_injury_reports uses asyncpg $N positional params, never f-strings in SQL.
- scraped_at uses server_default=now() — NOT passed in the INSERT statement.
- Weather scraping (Playwright/NFLWeather.com) deferred to v2 — Context Agent
  accepts weather_json=None for all games in v1.

Source map: sports.core.api.espn.com/v2/sports/football/leagues/nfl/teams/{id}/injuries
Team ID reference: ESPN Community gist nntrn/ee26cb2a0716de0947a0a4e9a157bc1c
"""
from __future__ import annotations

from typing import Optional

import asyncpg
import httpx
import structlog

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ESPN_INJURIES_URL = (
    "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"
    "/teams/{team_id}/injuries?limit=100"
)

# Mapping of NFL team abbreviation → ESPN numeric team ID.
# Source: ESPN Core API community gist (nntrn/ee26cb2a0716de0947a0a4e9a157bc1c)
# 32 teams as of 2025 season. Verify against live API on first run.
TEAM_ABBR_TO_ESPN_ID: dict[str, int] = {
    "ARI": 22,
    "ATL": 1,
    "BAL": 33,
    "BUF": 2,
    "CAR": 29,
    "CHI": 3,
    "CIN": 4,
    "CLE": 5,
    "DAL": 6,
    "DEN": 7,
    "DET": 8,
    "GB": 9,
    "HOU": 34,
    "IND": 11,
    "JAX": 30,
    "KC": 12,
    "LAC": 24,
    "LA": 14,
    "LV": 13,
    "MIA": 15,
    "MIN": 16,
    "NE": 17,
    "NO": 18,
    "NYG": 19,
    "NYJ": 20,
    "PHI": 21,
    "PIT": 23,
    "SEA": 26,
    "SF": 25,
    "TB": 27,
    "TEN": 10,
    "WAS": 28,
}


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def parse_espn_injury_item(item: dict[str, object]) -> dict[str, str]:
    """Parse a single ESPN Core API injury item into a flat injury dict.

    Uses .get() with "Unknown" fallback at every level to tolerate ESPN schema
    drift — the API is undocumented and field presence is not guaranteed.

    Args:
        item: A single element from the ESPN injuries endpoint "items" list.

    Returns:
        Dict with keys: player_name, status, position (all str).
        Any missing field returns "Unknown" rather than raising KeyError.
    """
    athlete = item.get("athlete", {})
    if not isinstance(athlete, dict):
        athlete = {}

    player_name: str = str(athlete.get("displayName", "Unknown"))
    status: str = str(item.get("status", "Unknown"))

    position_obj = athlete.get("position", {})
    if not isinstance(position_obj, dict):
        position_obj = {}
    position: str = str(position_obj.get("abbreviation", "Unknown"))

    if player_name == "Unknown":
        log.warning(
            "espn_injury_schema_drift",
            reason="displayName missing from athlete object",
            raw_item=item,
        )

    return {
        "player_name": player_name,
        "status": status,
        "position": position,
    }


# ---------------------------------------------------------------------------
# Scraper class
# ---------------------------------------------------------------------------


class InjuryWeatherScraper:
    """Fetches injury data from ESPN Core API and writes to PostgreSQL.

    Accepts an injected httpx.AsyncClient to allow mocking in tests — no live
    network calls are made unless a real client is provided by the caller.

    Weather scraping (Playwright/NFLWeather.com) is NOT included in v1.
    The Context Agent accepts weather_json=None for all games until v2.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def fetch_team_injuries(self, team_id: int) -> list[dict[str, str]]:
        """Fetch injury items from ESPN Core API for a single team.

        Returns a list of parsed injury dicts (player_name, status, position).
        Falls back gracefully on missing fields — never raises on schema drift.

        Args:
            team_id: ESPN numeric team ID (use TEAM_ABBR_TO_ESPN_ID for lookup).

        Returns:
            List of dicts, each with keys: player_name, status, position.
            Empty list if the API returns no items or an unexpected response.
        """
        url = ESPN_INJURIES_URL.format(team_id=team_id)
        response = await self._client.get(url)
        response.raise_for_status()
        data: dict[str, object] = response.json()

        items = data.get("items", [])
        if not isinstance(items, list):
            log.warning("espn_injuries_unexpected_shape", team_id=team_id, data=data)
            return []

        return [parse_espn_injury_item(item) for item in items if isinstance(item, dict)]

    async def write_injury_reports(
        self,
        pool: asyncpg.Pool,
        injuries: list[dict[str, str]],
        team_abbr: str,
        game_id: Optional[str] = None,
    ) -> int:
        """Write parsed injury dicts to the injury_reports table.

        Uses asyncpg $N positional params — no f-strings in SQL per CLAUDE.md
        SQL injection prevention requirement.

        scraped_at is NOT included in the INSERT — the column uses
        server_default=now() so PostgreSQL sets it at write time.

        Args:
            pool: asyncpg connection pool.
            injuries: List of parsed injury dicts (from fetch_team_injuries or
                      parse_espn_injury_item). Each must have player_name,
                      status, position keys.
            team_abbr: NFL team abbreviation (e.g. "KC"). Written to team_abbr column.
            game_id: Optional FK to games.game_id. None if game not yet known.

        Returns:
            Number of rows inserted.
        """
        inserted = 0
        for injury in injuries:
            player_name = injury.get("player_name", "Unknown")
            status = injury.get("status", "Unknown")
            position = injury.get("position", "Unknown")

            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO injury_reports"
                    " (game_id, player_name, status, position, team_abbr, source)"
                    " VALUES ($1, $2, $3, $4, $5, $6)",
                    game_id,
                    player_name,
                    status,
                    position,
                    team_abbr,
                    "espn_core_api",
                )
            inserted += 1

        log.info(
            "injury_reports_written",
            count=inserted,
            team_abbr=team_abbr,
            game_id=game_id,
        )
        return inserted
