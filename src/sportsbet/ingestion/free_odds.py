"""Free odds pollers with no API key required.

DraftKingsPoller  — fetches live NBA/NFL player prop odds from DraftKings'
                    unofficial public API (no auth, no rate limit).
ESPNOddsPoller    — fetches NBA/NFL h2h game odds from ESPN's hidden scoreboard
                    API (no auth). Used as h2h fallback when Odds API is over
                    budget or unavailable.

Both normalise their output to the same Odds API-compatible dict format so the
context_agent prop-processing loop can consume them without changes:

    [
        {
            "id": "<event_id>",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "markets": [
                        {
                            "key": "player_points",
                            "outcomes": [
                                {
                                    "name": "LeBron James",
                                    "description": "Over",
                                    "price": -110,
                                    "point": 24.5,
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    ]
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# DraftKings sportsbook base URL (US)
_DK_BASE = "https://sportsbook.draftkings.com/sites/US-SB/api/v1"

# DraftKings event group IDs (stable sport taxonomy IDs)
_DK_NBA_GROUP = 42648
_DK_NFL_GROUP = 88808

# Offer category names to normalise to Odds API market keys
_DK_CATEGORY_TO_MARKET: dict[str, str] = {
    "points": "player_points",
    "rebounds": "player_rebounds",
    "assists": "player_assists",
    "3-pointers made": "player_threes",
    "steals": "player_steals",
    "blocks": "player_blocks",
    "pts + reb + ast": "player_points_rebounds_assists",
    "passing yards": "player_pass_yds",
    "passing touchdowns": "player_pass_tds",
    "rushing yards": "player_rush_yds",
    "rushing touchdowns": "player_rush_tds",
    "receiving yards": "player_rec_yds",
    "receptions": "player_receptions",
}

# ESPN base URLs
_ESPN_SCOREBOARD_NBA = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
)
_ESPN_SCOREBOARD_NFL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
)

# ESPN Core API — prop bet provider ID (100 = ESPN BET / consensus line)
_ESPN_CORE_BASE = "https://sports.core.api.espn.com/v2/sports"
_ESPN_PROP_PROVIDER = 100

# ESPN prop type name → Odds API market key (player-stat props only)
_ESPN_TYPE_TO_MARKET: dict[str, str] = {
    "total points": "player_points",
    "total rebounds": "player_rebounds",
    "total assists": "player_assists",
    "total 3-point field goals": "player_threes",
    "total steals": "player_steals",
    "total blocks": "player_blocks",
    "total points, rebounds, and assists": "player_points_rebounds_assists",
    "total points and rebounds": "player_points_rebounds_assists",
    "total points and assists": "player_points_rebounds_assists",
    "total assists and rebounds": "player_rebounds",  # closest available key
}


# ---------------------------------------------------------------------------
# DraftKings poller
# ---------------------------------------------------------------------------


class DraftKingsPoller:
    """Fetch live player prop odds from DraftKings' undocumented public API.

    No API key or authentication required. DraftKings exposes this API to
    power their own web frontend — it is publicly accessible but unofficial.

    Usage (async context manager):
        async with DraftKingsPoller() as poller:
            props = await poller.fetch_player_props("nba")

    Returns list of event dicts in Odds API-compatible format so the existing
    context_agent prop-processing loop consumes them without modification.
    """

    def __init__(self, timeout: float = 15.0) -> None:
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._client_cm: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "DraftKingsPoller":
        self._client_cm = httpx.AsyncClient(
            base_url=_DK_BASE,
            timeout=self._timeout,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        self._client = await self._client_cm.__aenter__()
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        if self._client_cm is not None:
            await self._client_cm.__aexit__(exc_type, exc_val, exc_tb)
            self._client_cm = None
            self._client = None

    async def fetch_player_props(self, sport: str) -> list[dict[str, Any]]:
        """Fetch all live player prop offers for today's games.

        Args:
            sport: "nba" or "nfl"

        Returns:
            List of event dicts in Odds API-compatible format.
            Empty list if no games are live or API is unreachable.
        """
        assert self._client is not None, "called outside async context manager"

        group_id = _DK_NBA_GROUP if sport == "nba" else _DK_NFL_GROUP

        # Step 1: fetch the event group — contains all events + offer categories
        resp = await self._client.get(
            f"/eventgroups/{group_id}",
            params={"format": "json"},
        )
        resp.raise_for_status()
        data = resp.json()

        event_group = data.get("eventGroup", {})
        events_raw: list[dict] = event_group.get("events", [])
        offer_categories: list[dict] = event_group.get("offerCategories", [])

        log.info(
            "dk_eventgroup_fetched",
            sport=sport,
            event_count=len(events_raw),
            category_count=len(offer_categories),
        )

        if not events_raw:
            return []

        # Build event_id -> event dict for normalisation
        event_map: dict[str, dict] = {str(e["eventId"]): e for e in events_raw}

        # Step 2: traverse offer categories to collect player prop offers
        # Structure: offerCategories -> offerSubcategoryDescriptors -> offerSubcategory -> offers
        normalised: dict[str, dict] = {}  # event_id -> normalised event dict

        for category in offer_categories:
            category_name = category.get("name", "").lower()
            market_key = _DK_CATEGORY_TO_MARKET.get(category_name)
            if market_key is None:
                continue  # skip non-prop categories (game lines, futures, etc.)

            for sub_desc in category.get("offerSubcategoryDescriptors", []):
                sub_cat = sub_desc.get("offerSubcategory", {})
                for offer in sub_cat.get("offers", []):
                    # Each offer is a list of outcomes (Over/Under for one player)
                    if not isinstance(offer, list):
                        continue
                    _add_offer_to_events(offer, market_key, normalised, event_map)

        result = list(normalised.values())
        log.info("dk_props_normalised", sport=sport, event_count=len(result))
        return result


def _add_offer_to_events(
    offer: list[dict],
    market_key: str,
    normalised: dict[str, dict],
    event_map: dict[str, dict],
) -> None:
    """Parse a single DraftKings offer (list of outcomes) and add to normalised dict."""
    for outcome in offer:
        event_id = str(outcome.get("eventId", ""))
        if not event_id:
            continue

        # Ensure event entry exists
        if event_id not in normalised:
            raw_event = event_map.get(event_id, {})
            normalised[event_id] = {
                "id": event_id,
                "home_team": raw_event.get("teamName1", ""),
                "away_team": raw_event.get("teamName2", ""),
                "bookmakers": [
                    {"key": "draftkings", "markets": []}
                ],
            }

        bookmaker = normalised[event_id]["bookmakers"][0]

        # Find or create the market entry for this market_key
        market_entry = next(
            (m for m in bookmaker["markets"] if m["key"] == market_key),
            None,
        )
        if market_entry is None:
            market_entry = {"key": market_key, "outcomes": []}
            bookmaker["markets"].append(market_entry)

        # DraftKings outcome fields:
        #   label     = "Over 24.5" or "Under 24.5" or "LeBron James Over 24.5"
        #   oddsAmerican = "-110" (string)
        #   line      = 24.5 (float, sometimes in label only)
        #   participant = player name (when present)
        label: str = outcome.get("label", "")
        odds_str: str = str(outcome.get("oddsAmerican", "0")).replace("−", "-")
        line_val = outcome.get("line")
        participant: str = outcome.get("participant", "")

        # Parse side (Over/Under) and player name from label
        side = "Over" if "over" in label.lower() else "Under" if "under" in label.lower() else label
        player_name = participant or _extract_player_from_label(label)

        try:
            price = int(odds_str) if odds_str and odds_str != "0" else None
        except (ValueError, TypeError):
            price = None

        if price is None or not player_name:
            continue

        market_entry["outcomes"].append({
            "name": side,
            "description": player_name,
            "price": price,
            "point": float(line_val) if line_val is not None else None,
        })


def _extract_player_from_label(label: str) -> str:
    """Extract player name from DraftKings label like 'LeBron James Over 24.5'."""
    for keyword in ("Over", "Under", "over", "under"):
        if keyword in label:
            return label[: label.index(keyword)].strip()
    return label.strip()


# ---------------------------------------------------------------------------
# ESPN props poller (player prop fallback)
# ---------------------------------------------------------------------------


class ESPNPropsPoller:
    """Fetch live NBA player prop odds from ESPN's Core API (no auth required).

    Uses ESPN's undocumented sports.core.api.espn.com endpoint which powers
    ESPN BET. Returns props normalised to the same Odds API-compatible format
    as OddsAPIPoller so the context_agent loop consumes them unchanged.

    Prop items arrive in consecutive pairs (same athlete + type): index 0 is
    the Over line, index 1 is the Under line. Athlete names are resolved via
    parallel requests to the athlete detail endpoint.

    Usage:
        async with ESPNPropsPoller() as poller:
            props = await poller.fetch_player_props("nba")
    """

    def __init__(self, timeout: float = 15.0) -> None:
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._client_cm: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "ESPNPropsPoller":
        self._client_cm = httpx.AsyncClient(timeout=self._timeout)
        self._client = await self._client_cm.__aenter__()
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        if self._client_cm is not None:
            await self._client_cm.__aexit__(exc_type, exc_val, exc_tb)
            self._client_cm = None
            self._client = None

    async def fetch_player_props(self, sport: str) -> list[dict[str, Any]]:
        """Fetch all player prop odds for today's games.

        Args:
            sport: "nba" or "nfl"

        Returns:
            List of event dicts in Odds API-compatible format.
            Empty list if no games scheduled or ESPN unreachable.
        """
        assert self._client is not None, "called outside async context manager"

        # Step 1: get today's events from the scoreboard
        if sport == "nba":
            league = "basketball/leagues/nba"
            scoreboard_url = _ESPN_SCOREBOARD_NBA
        else:
            league = "football/leagues/nfl"
            scoreboard_url = _ESPN_SCOREBOARD_NFL

        sb_resp = await self._client.get(scoreboard_url)
        sb_resp.raise_for_status()
        events_raw = sb_resp.json().get("events", [])

        if not events_raw:
            log.info("espn_props_no_events_today", sport=sport)
            return []

        log.info("espn_props_events_found", sport=sport, event_count=len(events_raw))

        # Step 2: for each event, fetch propBets (paginated) in parallel
        tasks = [
            self._fetch_event_props(league, e)
            for e in events_raw
        ]
        event_results = await asyncio.gather(*tasks, return_exceptions=True)

        normalised: list[dict[str, Any]] = []
        for result in event_results:
            if isinstance(result, Exception):
                log.warning("espn_props_event_error", error=str(result))
                continue
            if result:
                normalised.append(result)

        log.info("espn_props_fetched", sport=sport, event_count=len(normalised))
        return normalised

    async def _fetch_event_props(
        self, league: str, event: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Fetch and normalise prop bets for a single event."""
        assert self._client is not None
        event_id = event.get("id", "")
        comp = (event.get("competitions") or [{}])[0]
        competitors = {
            c.get("homeAway", ""): c.get("team", {}).get("abbreviation", "")
            for c in comp.get("competitors", [])
        }

        # Fetch all pages of propBets
        base_url = (
            f"{_ESPN_CORE_BASE}/{league}/events/{event_id}"
            f"/competitions/{event_id}/odds/{_ESPN_PROP_PROVIDER}/propBets"
        )
        all_items: list[dict] = []
        page = 1
        while True:
            resp = await self._client.get(
                base_url, params={"lang": "en", "region": "us", "limit": 200, "page": page}
            )
            resp.raise_for_status()
            data = resp.json()
            all_items.extend(data.get("items", []))
            if page >= data.get("pageCount", 1):
                break
            page += 1

        if not all_items:
            return None

        # Step 3: resolve unique athlete IDs → names in parallel
        unique_athlete_refs: dict[str, str] = {}  # ref_url → athlete_id
        for item in all_items:
            ref = item.get("athlete", {}).get("$ref", "")
            if ref:
                athlete_id = ref.split("/athletes/")[-1].split("?")[0]
                unique_athlete_refs[athlete_id] = ref

        name_map = await self._resolve_athlete_names(unique_athlete_refs)

        # Step 4: group consecutive pairs by (athlete_id, type_id) → Over/Under
        outcomes_by_market: dict[str, list[dict]] = {}  # market_key → outcomes

        # Track pairing: consecutive items with same (athlete_id, type_id) = Over then Under
        pair_tracker: dict[tuple[str, str], int] = {}  # (athlete_id, type_id) → pair_index

        for item in all_items:
            type_name = item.get("type", {}).get("name", "").lower()
            market_key = _ESPN_TYPE_TO_MARKET.get(type_name)
            if market_key is None:
                continue  # skip game-level bets (spreads, totals, quarters)

            ref = item.get("athlete", {}).get("$ref", "")
            athlete_id = ref.split("/athletes/")[-1].split("?")[0] if ref else ""
            type_id = item.get("type", {}).get("id", "")
            player_name = name_map.get(athlete_id, "Unknown")

            odds_block = item.get("odds", {})
            line_val = item.get("current", {}).get("target", {}).get("value")
            if line_val is None:
                line_val = odds_block.get("total", {}).get("value")

            try:
                price = int(str(odds_block.get("american", {}).get("value", "0")).replace("+", ""))
            except (ValueError, TypeError):
                continue

            if not player_name or price == 0:
                continue

            pair_key = (athlete_id, type_id)
            pair_index = pair_tracker.get(pair_key, 0)
            pair_tracker[pair_key] = pair_index + 1

            side = "Over" if pair_index % 2 == 0 else "Under"

            if market_key not in outcomes_by_market:
                outcomes_by_market[market_key] = []

            outcomes_by_market[market_key].append({
                "name": side,
                "description": player_name,
                "price": price,
                "point": float(line_val) if line_val is not None else None,
            })

        if not outcomes_by_market:
            return None

        markets = [
            {"key": mk, "outcomes": outcomes}
            for mk, outcomes in outcomes_by_market.items()
        ]

        return {
            "id": event_id,
            "home_team": competitors.get("home", ""),
            "away_team": competitors.get("away", ""),
            "bookmakers": [{"key": "espn_bet", "markets": markets}],
        }

    async def _resolve_athlete_names(
        self, athlete_refs: dict[str, str]
    ) -> dict[str, str]:
        """Resolve athlete IDs to display names via parallel ESPN athlete API calls."""
        assert self._client is not None

        async def fetch_name(athlete_id: str, ref_url: str) -> tuple[str, str]:
            try:
                r = await self._client.get(ref_url)  # type: ignore[union-attr]
                r.raise_for_status()
                data = r.json()
                name = data.get("displayName") or data.get("fullName") or "Unknown"
                return athlete_id, name
            except Exception:
                return athlete_id, "Unknown"

        results = await asyncio.gather(
            *[fetch_name(aid, ref) for aid, ref in athlete_refs.items()]
        )
        return dict(results)


# ---------------------------------------------------------------------------
# ESPN odds poller (h2h fallback)
# ---------------------------------------------------------------------------


class ESPNOddsPoller:
    """Fetch h2h game odds from ESPN's undocumented scoreboard API.

    No API key or authentication required. Returns game moneyline odds
    normalised to Odds API format for use as an h2h fallback when The Odds
    API budget is exhausted.

    Does NOT provide player props — use ESPNPropsPoller for those.
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
