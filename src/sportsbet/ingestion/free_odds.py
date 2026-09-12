"""Read-only ESPN game moneyline fallback; no player-prop prices are inferred."""
from __future__ import annotations

from typing import Any

import httpx
import structlog

log = structlog.get_logger()

_ESPN_SCOREBOARD_NBA = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
)
_ESPN_SCOREBOARD_NFL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
)



class ESPNOddsPoller:
    """Fetch h2h game odds from ESPN's undocumented scoreboard API.

    No API key or authentication required. Returns game moneyline odds
    normalised to Odds API format for use as an h2h fallback when The Odds
    API budget is exhausted.

    The scoreboard does not supply player-prop prices.
    """

    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout

    async def fetch_h2h_odds(self, sport: str) -> list[dict[str, Any]]:
        """Fetch current NBA or NFL game moneyline odds from ESPN.

        Args:
            sport: "nba" or "nfl"

        Returns:
            List of event dicts in Odds API-compatible format (h2h moneyline only).
            Empty list if no games scheduled or ESPN unreachable.
        """
        url = _ESPN_SCOREBOARD_NBA if sport == "nba" else _ESPN_SCOREBOARD_NFL

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        events_raw = data.get("events", [])
        normalised: list[dict] = []

        for event in events_raw:
            event_id = event.get("id", "")
            competitions = event.get("competitions", [])
            if not competitions:
                continue

            comp = competitions[0]
            odds_list: list[dict] = comp.get("odds", [])
            if not odds_list:
                continue

            competitors = {
                c.get("homeAway", ""): c.get("team", {}).get("abbreviation", "")
                for c in comp.get("competitors", [])
            }

            bookmakers: list[dict] = []
            for odds_entry in odds_list:
                provider_name = (
                    odds_entry.get("provider", {}).get("name", "espn").lower().replace(" ", "")
                )
                home_ml = _parse_espn_moneyline(odds_entry, "home")
                away_ml = _parse_espn_moneyline(odds_entry, "away")
                if home_ml is None or away_ml is None:
                    continue

                bookmakers.append({
                    "key": provider_name,
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {
                                    "name": competitors.get("home", "Home"),
                                    "price": home_ml,
                                },
                                {
                                    "name": competitors.get("away", "Away"),
                                    "price": away_ml,
                                },
                            ],
                        }
                    ],
                })

            if bookmakers:
                normalised.append({
                    "id": event_id,
                    "home_team": competitors.get("home", ""),
                    "away_team": competitors.get("away", ""),
                    "bookmakers": bookmakers,
                })

        log.info("espn_odds_fetched", sport=sport, event_count=len(normalised))
        return normalised


def _parse_espn_moneyline(odds_entry: dict, side: str) -> int | None:
    """Extract moneyline as American odds integer from an ESPN odds entry."""
    # ESPN stores odds in nested homeTeamOdds / awayTeamOdds
    key = "homeTeamOdds" if side == "home" else "awayTeamOdds"
    team_odds = odds_entry.get(key, {})
    ml = team_odds.get("moneyLine") or team_odds.get("current", {}).get("moneyLine")
    if ml is not None:
        try:
            return int(ml)
        except (ValueError, TypeError):
            pass

    # Fallback: top-level moneylineOdds string like "+130" or "-150"
    raw = odds_entry.get("moneylineOdds") or odds_entry.get(f"{side}MoneylineOdds")
    if raw:
        try:
            return int(str(raw).replace("+", "").replace("−", "-"))
        except (ValueError, TypeError):
            pass

    return None
