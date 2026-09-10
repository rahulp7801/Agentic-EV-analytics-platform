"""
scan_game_ev.py — EV scanner for a specific NBA game.

Usage:
  python scan_game_ev.py                         # defaults: NY vs HOU, tomorrow
  python scan_game_ev.py --team-a LAL --team-b GSW
  python scan_game_ev.py --team-a OKC --team-b DAL --date 20260401
"""
import sys
import time
import argparse
sys.path.insert(0, 'src')
sys.path.insert(0, 'site-packages')

import asyncio
import platform
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from dotenv import load_dotenv
load_dotenv()

import json
import pathlib

import httpx

from sportsbet.db.connection import create_async_pool
from sportsbet.graph.graph import create_graph
from sportsbet.prop.nba_agents import make_nba_quant_agent
from sportsbet.prop.nba_context_producer import make_nba_context_signals_producer
from sportsbet.prop.arbitrage import make_prop_arbitrage_agent
from sportsbet.ingestion.free_odds import PrizePicksPoller, ESPNPropsPoller
from sportsbet.ingestion.prop_odds import PlayerPropSnapshotCreate
from sportsbet.quant.vig import american_to_raw_prob
from sportsbet.config import settings
from sportsbet.ledger import Ledger
from sportsbet.arbitrage.ev import compute_expected_return, quote_terms
from sportsbet.arbitrage.kelly import fractional_kelly

def _under_kelly(true_prob: float, american_odds: int, fraction: float = 0.25) -> float:
    """Fractional Kelly for a bet at the given American odds."""
    _, payout = quote_terms(american_odds, Decimal("0"))
    return float(fractional_kelly(Decimal(str(true_prob)), payout, Decimal(str(fraction))))


_PROGRESS_PATH = pathlib.Path(__file__).parent / ".scan_progress.json"

def _write_progress(
    stage: int,
    stage_label: str,
    players_total: int = 0,
    players_done: int = 0,
    current_player: str = "",
) -> None:
    """Atomically write scan progress for the frontend to poll."""
    data = {
        "stage": stage,
        "stage_label": stage_label,
        "total_stages": 4,
        "players_total": players_total,
        "players_done": players_done,
        "current_player": current_player,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    tmp = _PROGRESS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(_PROGRESS_PATH)

# ── CLI args ──────────────────────────────────────────────────────────────────
_parser = argparse.ArgumentParser(description="NBA EV Scanner")
_parser.add_argument("--team-a", default="NY",  help="ESPN abbreviation for team A (default: NY)")
_parser.add_argument("--team-b", default="HOU", help="ESPN abbreviation for team B (default: HOU)")
_parser.add_argument("--date",   default=None,  help="Target date YYYYMMDD (default: tomorrow)")
_parser.add_argument("--force",  action="store_true", help="Bypass DB cache and re-run full scan")
_args, _unknown = _parser.parse_known_args()

# ── Config ────────────────────────────────────────────────────────────────────
TARGET_DATE = _args.date or (datetime.now() + timedelta(days=1)).strftime("%Y%m%d")
TEAM_A = _args.team_a
TEAM_B = _args.team_b
FORCE   = _args.force
TARGET_DATE_OBJ = datetime.strptime(TARGET_DATE, "%Y%m%d").date()
SEASON = TARGET_DATE_OBJ.year if TARGET_DATE_OBJ.month >= 10 else TARGET_DATE_OBJ.year - 1

_ESPN_NBA_SCOREBOARD = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
)
_ESPN_NBA_TEAMS = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams"
)

THREAD_BASE = f"scan-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


# ── Helpers ───────────────────────────────────────────────────────────────────

async def fetch_matchup_for_date(team_abbr: str, date_str: str) -> tuple[str, str] | None:
    """Return (home_team, away_team) for team_abbr on date_str (YYYYMMDD) from ESPN."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_ESPN_NBA_SCOREBOARD, params={"dates": date_str})
            resp.raise_for_status()
            events = resp.json().get("events", [])
    except httpx.HTTPError as exc:
        print(f"  [!] ESPN scoreboard unreachable: {exc}")
        return None

    team_upper = team_abbr.upper()
    for event in events:
        comp = (event.get("competitions") or [{}])[0]
        competitors = {
            c.get("homeAway", ""): c.get("team", {}).get("abbreviation", "").upper()
            for c in comp.get("competitors", [])
        }
        home = competitors.get("home", "")
        away = competitors.get("away", "")
        if team_upper in (home, away):
            return home, away
    return None


async def fetch_team_roster(team_id: str) -> list[str]:
    """Fetch all active player display names for an ESPN team ID."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/roster"
            )
            resp.raise_for_status()
            return [
                a.get("displayName", "")
                for a in resp.json().get("athletes", [])
                if a.get("displayName")
            ]
    except httpx.HTTPError as exc:
        print(f"  [!] ESPN roster fetch failed (team_id={team_id}): {exc}")
        return []


async def fetch_team_ids(abbrs: list[str]) -> dict[str, str]:
    """Return {abbr: espn_team_id} for each abbreviation in abbrs."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_ESPN_NBA_TEAMS)
            resp.raise_for_status()
            teams = (
                resp.json()
                .get("sports", [{}])[0]
                .get("leagues", [{}])[0]
                .get("teams", [])
            )
    except httpx.HTTPError as exc:
        print(f"  [!] ESPN teams API unreachable: {exc}")
        return {}
    upper_abbrs = {a.upper() for a in abbrs}
    return {
        t["team"]["abbreviation"]: t["team"]["id"]
        for t in teams
        if t.get("team", {}).get("abbreviation", "").upper() in upper_abbrs
    }


def _normalize_raw_events(
    raw_events: list[dict],
    sport: str,
) -> list[PlayerPropSnapshotCreate]:
    """Convert raw Odds API-compatible event dicts into PlayerPropSnapshotCreate objects."""
    snapshots: list[PlayerPropSnapshotCreate] = []
    for event in raw_events:
        for bookmaker in event.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                for outcome in market.get("outcomes", []):
                    price = outcome.get("price")
                    point = outcome.get("point")
                    if price is None or point is None:
                        continue
                    raw_prob = american_to_raw_prob(int(price))
                    snapshots.append(PlayerPropSnapshotCreate(
                        sport=sport,
                        game_id=event.get("id"),
                        player_name=outcome.get("description") or outcome.get("name", "Unknown"),
                        sportsbook=bookmaker.get("key", "unknown"),
                        prop_type=market.get("key", "unknown"),
                        line=Decimal(str(point)),
                        price=int(price),
                        implied_probability=Decimal(str(round(float(raw_prob), 6))),
                        side=outcome.get("name", ""),
                        game_start_time=datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00")) if event.get("commence_time") else None,
                        snapped_at=datetime.fromisoformat(bookmaker["last_update"].replace("Z", "+00:00")) if bookmaker.get("last_update") else datetime.now(timezone.utc),
                    ))
    return snapshots


_ODDS_API_PLAYER_MARKETS = ",".join([
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_threes",
    "player_steals",
    "player_blocks",
])


async def _fetch_odds_api_snapshots(sport: str = "nba") -> list[PlayerPropSnapshotCreate]:
    """Fetch player prop lines from The Odds API (keyed, paid source — most reliable).

    Uses the per-event /events/{id}/odds endpoint because the top-level /odds
    endpoint does not support player prop markets.  Consumes 1 API credit per
    event (not per market), so for a typical 7-game slate this costs ~7 credits.
    """
    if not settings.odds_api_key:
        print("  [!] odds_api_key not set — skipping Odds API source.")
        return []

    sport_key = "basketball_nba" if sport == "nba" else sport
    base = "https://api.the-odds-api.com/v4"

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Step 1: list upcoming events (free, no credits)
        try:
            resp = await client.get(
                f"{base}/sports/{sport_key}/events",
                params={"apiKey": settings.odds_api_key},
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            print(f"  [!] Odds API events list unreachable: {exc}")
            return []

        events = resp.json()
        remaining = resp.headers.get("x-requests-remaining", "?")
        print(f"  Odds API: {len(events)} upcoming events  [{remaining} credits remaining]")

        if not events:
            return []

        # Step 2: fetch player props for each event in parallel (1 credit each)
        async def fetch_event_props(event: dict) -> list[dict]:
            eid = event.get("id", "")
            try:
                r = await client.get(
                    f"{base}/sports/{sport_key}/events/{eid}/odds",
                    params={
                        "apiKey": settings.odds_api_key,
                        "regions": "us",
                        "markets": _ODDS_API_PLAYER_MARKETS,
                        "oddsFormat": "american",
                    },
                )
                r.raise_for_status()
                data = r.json()
                # Return as a normalised event dict (already Odds API format)
                return [data] if data.get("bookmakers") else []
            except httpx.HTTPError:
                return []

        tasks = [fetch_event_props(e) for e in events]
        results = await asyncio.gather(*tasks)
        raw_events = [evt for group in results for evt in group]

    if not raw_events:
        print("  [!] Odds API returned 0 prop events (slate not yet posted or no markets).")
        return []

    snapshots = _normalize_raw_events(raw_events, sport)
    print(f"  Odds API: {len(snapshots)} prop outcomes across {len(raw_events)} events")
    return snapshots


async def fetch_all_snapshots(sport: str = "nba") -> list[PlayerPropSnapshotCreate]:
    """Fetch player props with a cascade: Odds API → PrizePicks → empty list.

    Sources are tried in order of reliability.  An empty result from any source
    falls through to the next rather than causing a hard abort — the caller is
    responsible for deciding whether to continue with an empty slate.
    """
    # ── Source 1: The Odds API (paid, keyed, most reliable) ──────────────────
    print("  Trying Odds API...", end=" ", flush=True)
    snapshots = await _fetch_odds_api_snapshots(sport)
    if snapshots:
        return snapshots
    print("  Odds API returned 0 props — trying PrizePicks fallback...", flush=True)

    # ── Source 2: PrizePicks public API (may be blocked by bot protection) ───
    try:
        async with PrizePicksPoller() as pp:
            raw_events = await pp.fetch_player_props(sport)
        if raw_events:
            snapshots = _normalize_raw_events(raw_events, sport)
            print(f"  PrizePicks: {len(snapshots)} prop outcomes")
            return snapshots
        print("  PrizePicks: 0 props returned.")
    except Exception as exc:
        print(f"  [!] PrizePicks unavailable: {type(exc).__name__}: {exc}")

    # ── Source 3: ESPN Bet props (free, no auth, limited coverage) ───────────
    print("  PrizePicks returned 0 props — trying ESPN fallback...", flush=True)
    try:
        async with ESPNPropsPoller() as espn:
            raw_events = await espn.fetch_player_props(sport)
        if raw_events:
            snapshots = _normalize_raw_events(raw_events, sport)
            print(f"  ESPN: {len(snapshots)} prop outcomes across {len(raw_events)} events")
            return snapshots
        print("  ESPN: 0 props returned.")
    except Exception as exc:
        print(f"  [!] ESPN props unavailable: {type(exc).__name__}: {exc}")

    # ── All sources exhausted ─────────────────────────────────────────────────
    print("  [!] All prop sources returned 0 results — slate may not be posted yet.")
    return []


async def load_signals_from_db(pool, game_id: str) -> list[dict]:
    """Return cached signal dicts from ev_signals table for a given game_id, or []."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT player_name, prop_type, line, true_probability, implied_probability,
                      ev_percentage, kelly_fraction, american_odds, sample_size, mean_stat,
                      sportsbook, gated, trade_plan, opponent_def_rating, rest_days, is_home,
                      strength, home_team, away_team, game_date,
                      COALESCE(direction, 'over') AS direction
               FROM ev_signals
               WHERE game_id = $1
               ORDER BY ev_percentage DESC""",
            game_id,
        )
    return [dict(r) for r in rows]


def _merge_signals_cache(
    cache_path: pathlib.Path,
    game_id: str,
    home_team: str,
    away_team: str,
    new_signals: list[dict],
) -> dict:
    """Merge new_signals into the combined cache, replacing any existing entries for game_id."""
    existing: dict = {}
    if cache_path.exists():
        try:
            existing = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    # Build a map of game_id -> list of signals from the existing cache
    existing_signals: list[dict] = existing.get("signals", [])
    # Remove signals for the current game (they'll be replaced)
    kept = [s for s in existing_signals if s.get("game_id") != game_id]
    # Tag each new signal with game_id so we can remove it next time
    tagged = [{**s, "game_id": game_id} for s in new_signals]
    merged = kept + tagged

    # Build games list: deduplicated set of games represented in merged signals
    games_seen: dict[str, dict] = {}
    for s in merged:
        gid = s.get("game_id", "")
        if gid and gid not in games_seen:
            # Derive game date from game_id (format: "home_away_YYYYMMDD")
            _gid_parts = gid.rsplit("_", 1)
            _gdate = _gid_parts[-1] if len(_gid_parts) == 2 and _gid_parts[-1].isdigit() else ""
            games_seen[gid] = {
                "game_id": gid,
                "home_team": s.get("home_team", ""),
                "away_team": s.get("away_team", ""),
                "date": _gdate,
            }
    # Ensure current game is listed even if no signals
    if game_id not in games_seen:
        games_seen[game_id] = {
            "game_id": game_id,
            "home_team": home_team,
            "away_team": away_team,
            "date": TARGET_DATE,
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "game": {"home_team": home_team, "away_team": away_team, "date": TARGET_DATE},
        "games": list(games_seen.values()),
        "signals": merged,
    }


async def resolve_player_id(pool, player_name: str) -> str:
    """Look up NBA.com player_id from nba_player_stats by fuzzy name match."""
    parts = player_name.split()
    if len(parts) < 2:
        return ""
    pattern = f"%{parts[0]}%{parts[-1]}%"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT player_id FROM nba_player_stats WHERE player_name ILIKE $1 LIMIT 1",
            pattern,
        )
    return str(row["player_id"]) if row else ""


async def run_ev_for_player(
    *,
    pool,
    graph,
    all_snapshots: list[PlayerPropSnapshotCreate],
    player_name: str,
    player_id: str,
    home_team: str,
    away_team: str,
    thread_id: str,
    inactive_teammates: list[str] | None = None,
) -> dict:
    """Run nba_prop_analysis for a single player. Returns a result summary dict."""
    # Prop types the query builder supports (turnovers etc. are not modelled)
    _SUPPORTED_PROP_TYPES = {
        "player_points", "player_rebounds", "player_assists", "player_threes",
        "player_steals", "player_blocks", "player_pra",
    }

    # Compare prices only within the same player/market/line. Evaluate both sides,
    # including Under-only listings; a cheaper alternate line is a different bet.
    player_quotes = [q for q in all_snapshots
        if q.player_name.strip().casefold() == player_name.strip().casefold()
        and q.prop_type in _SUPPORTED_PROP_TYPES and q.side in ("Over", "Under")
        and q.sportsbook.lower() != "prizepicks"]
    selections = sorted({(q.prop_type, q.line) for q in player_quotes})
    results = []
    for prop_idx, (prop_type, line) in enumerate(selections, 1):
        quotes = {}
        for side in ("Over", "Under"):
            candidates = [q for q in player_quotes if q.prop_type == prop_type and q.line == line and q.side == side]
            if candidates:
                quotes[side] = min(candidates, key=lambda q: american_to_raw_prob(q.price))
        snap = quotes.get("Over") or quotes["Under"]
        prop_line = float(line)

        prop_label = prop_type.replace("player_", "").upper()
        print(f"      [{prop_idx}/{len(selections)}] {prop_label} O{prop_line} — invoking graph...", flush=True)
        t0 = time.perf_counter()

        # Build injury_flags for the arbitrage agent's bullet_3 — marks
        # inactive teammates so the trade plan explicitly surfaces their absence.
        _injury_flags: dict[str, str] = {}
        if inactive_teammates:
            _injury_flags = {name: "Inactive/Out" for name in inactive_teammates}

        # situational_params activates the gamelog conditional path in
        # NBAQueryBuilder (teammate_out filter + opponent_team + home_away),
        # giving frequency-based probability from matching historical situations.
        _situational: dict = {}
        if inactive_teammates:
            _situational = {"teammate_out_signals": inactive_teammates}

        try:
            state = await asyncio.wait_for(
                graph.ainvoke(
                    {
                        "session_id": "scan",
                        "game_id": f"{home_team.lower()}_{away_team.lower()}_{TARGET_DATE}",
                        "season": SEASON,
                        "as_of_date": TARGET_DATE_OBJ,
                        "week": 1,
                        "home_team": home_team,
                        "away_team": away_team,
                        "injury_flags": _injury_flags,
                        "weather_json": None,
                        "receiver_gsis_id": player_id,
                        "player_name": player_name,
                        "prop_type": prop_type.replace("player_", ""),
                        "prop_line": prop_line,
                        "sport": "nba",
                        "created_at": datetime.now(timezone.utc),
                        "request_type": "nba_prop_analysis",
                        # Price and sportsbook exported below must be the quote evaluated.
                        "player_prop_snapshots": [snap],
                        "prop_side": snap.side.lower(),
                        "situational_params": _situational if _situational else None,
                    },
                    config={"configurable": {"thread_id": f"{thread_id}-{prop_type}"}},
                ),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            elapsed = time.perf_counter() - t0
            print(f"        => TIMEOUT after {elapsed:.0f}s — skipping", flush=True)
            continue
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            print(f"        => ERROR {type(exc).__name__}: {exc}  ({elapsed:.1f}s)", flush=True)
            continue

        elapsed  = time.perf_counter() - t0
        prop     = state.get("nba_prop_result")
        ev       = state.get("ev_signal")
        pending  = state.get("pending_signals") or []
        context  = state.get("nba_context_signals")   # NBAContextSignals | None

        # Quick inline verdict
        if ev and ev.ev_percentage and float(ev.ev_percentage) > 0:
            print(f"        => +EV +{float(ev.ev_percentage):.1%}  ({elapsed:.1f}s)", flush=True)
        elif pending:
            print(f"        => GATED +{float(pending[0].ev_percentage):.1%}  ({elapsed:.1f}s)", flush=True)
        elif prop and prop.true_probability:
            print(f"        => -EV  model={float(prop.true_probability):.1%}  ({elapsed:.1f}s)", flush=True)
        else:
            print(f"        => no data  ({elapsed:.1f}s)", flush=True)

        for side, quote in quotes.items():
            evaluated = state if quote is snap else await make_prop_arbitrage_agent(sport="nba")({
                **state, "prop_side": side.lower(), "player_prop_snapshots": [quote],
            })
            results.append({
                "player": player_name, "prop_type": prop_type, "line": prop_line,
                "prop": prop, "ev": evaluated.get("ev_signal"),
                "pending": evaluated.get("pending_signals") or [], "context": context,
                "snap_price": int(quote.price), "snap_sportsbook": quote.sportsbook,
                "direction": side.lower(), "gate_reason": evaluated.get("gate_reason"), "quote": quote,
            })

    return results


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    if TARGET_DATE_OBJ < datetime.now().date():
        raise ValueError("Historical dates require recorded pre-game quotes; use offline evaluation.")
    print(f"=== NBA EV SCANNER — {TARGET_DATE} ===")
    print(f"Target: {TEAM_A} vs {TEAM_B}\n")

    # 1. Confirm matchup exists in ESPN tomorrow schedule
    _write_progress(1, "Verifying matchup via ESPN...")
    print(f"[1/4] Verifying ESPN schedule for {TARGET_DATE}...")
    matchup = await fetch_matchup_for_date(TEAM_A, TARGET_DATE)
    if matchup is None:
        print(f"  [!] {TEAM_A} has no game on {TARGET_DATE} (or ESPN unreachable). Aborting.")
        _PROGRESS_PATH.unlink(missing_ok=True)
        return
    home_team, away_team = matchup
    print(f"  Matchup confirmed: {away_team} @ {home_team}")

    # 2. Get rosters for the two teams actually playing (from ESPN confirmation)
    # home_team / away_team are ESPN abbreviations (e.g. "MEM", "NY") — use these
    # instead of TEAM_A/TEAM_B so we never pull in players from a different game.
    _write_progress(2, f"Fetching rosters ({away_team} @ {home_team})...")
    print(f"\n[2/4] Fetching rosters from ESPN...")
    if TEAM_B.upper() not in (home_team.upper(), away_team.upper()):
        print(f"  [!] {TEAM_B} is not in the confirmed {away_team} @ {home_team} matchup — "
              f"ignoring {TEAM_B} roster to avoid cross-game player contamination.")
    team_id_map = await fetch_team_ids([home_team, away_team])
    if not team_id_map:
        print(f"  [!] Could not resolve team IDs from ESPN — roster filter will be skipped.")
    else:
        print(f"  Team IDs: {team_id_map}")
    all_players: list[str] = []
    # per_team_roster maps team abbreviation -> list of player display names
    per_team_roster: dict[str, list[str]] = {}
    for abbr, tid in team_id_map.items():
        roster = await fetch_team_roster(tid)
        if roster:
            print(f"  {abbr} ({len(roster)} players): {', '.join(roster[:5])}...")
        else:
            print(f"  {abbr} — roster fetch failed, skipping.")
        per_team_roster[abbr] = roster
        all_players.extend(roster)

    _game_id = f"{home_team.lower()}_{away_team.lower()}_{TARGET_DATE}"
    # Always evaluate current quotes; historical recommendations are audit records.

    # 3. Fetch props slate (Odds API → PrizePicks cascade)
    _write_progress(3, "Fetching prop slate (Odds API → PrizePicks → ESPN)...")
    print(f"\n[3/4] Fetching NBA prop slate...")
    all_snapshots = await fetch_all_snapshots("nba")

    def _write_no_slate_cache(reason: str) -> None:
        """Write a signals_cache.json with a human-readable reason so the frontend
        shows something useful instead of a bare empty page."""
        cache_path = pathlib.Path(__file__).parent / "frontend" / "public" / "signals_cache.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        out = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "game": {"home_team": home_team, "away_team": away_team, "date": TARGET_DATE},
            "signals": [],
            "scan_note": reason,
        }
        tmp = cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(out, indent=2))
        tmp.replace(cache_path)

    if not all_snapshots:
        msg = (
            f"No props available for {away_team} @ {home_team} on {TARGET_DATE}. "
            "Odds API, PrizePicks, and ESPN all returned 0 results — the slate may not be posted yet. "
            "Check back closer to game time."
        )
        print(f"\n  [!] {msg}")
        _write_no_slate_cache(msg)
        _PROGRESS_PATH.unlink(missing_ok=True)
        return
    print(f"  Total props: {len(all_snapshots)}")

    # Find which game players appear on the current slate.
    # If roster fetch failed (all_players is empty), fall through to the full slate
    # rather than filtering to nothing — better to scan too many than too few.

    def _norm_name(n: str) -> str:
        """Normalize a player name for fuzzy matching: lowercase, strip punctuation."""
        import re
        return re.sub(r"[^a-z0-9 ]", "", n.lower()).strip()

    if all_players:
        _norm_roster = [(_norm_name(p), p) for p in all_players]
        on_slate = sorted({
            s.player_name for s in all_snapshots
            if s.side == "Over" and any(
                _norm_name(p_orig) in _norm_name(s.player_name)
                or _norm_name(s.player_name) in _norm_name(p_orig)
                for _norm_p, p_orig in _norm_roster
            )
        })
        if not on_slate:
            # Name normalization still found no matches — roster abbrev mismatch or
            # PrizePicks hasn't posted this specific game yet. Fall back to full slate
            # so we don't silently abort when props clearly exist.
            print(f"  [!] Roster name-match returned 0 results (ESPN↔PrizePicks format mismatch). "
                  f"Falling back to full prop slate.")
            on_slate = sorted({s.player_name for s in all_snapshots if s.side == "Over"})
    else:
        # Roster fetch failed — use full prop slate filtered to Over side to avoid duplicates
        on_slate = sorted({s.player_name for s in all_snapshots if s.side == "Over"})
        print(f"  [!] Roster unavailable — using full slate ({len(on_slate)} players)")

    if not on_slate:
        msg = (
            f"No props available for {away_team} @ {home_team} on {TARGET_DATE}. "
            "PrizePicks/Odds API returned 0 results — the slate may not be posted yet."
        )
        print(f"\n  [!] {msg}")
        _write_no_slate_cache(msg)
        _PROGRESS_PATH.unlink(missing_ok=True)
        return

    print(f"  Players on slate ({len(on_slate)}): {', '.join(on_slate)}")

    # 3b. Identify inactive/absent players per team.
    # Logic: roster members who do NOT appear on the prop slate are likely inactive
    # (injured, DNP, rest). PrizePicks/Odds API only list players expected to play.
    # These are passed as teammate_out to the gamelog query so the model conditions
    # on games where the key teammate was absent — surfacing usage-boost patterns.
    on_slate_norm: set[str] = {_norm_name(n) for n in on_slate}

    def _name_on_slate(name: str) -> bool:
        nn = _norm_name(name)
        return any(nn in sl or sl in nn for sl in on_slate_norm)

    # player_team_map: slate name -> team abbr (best-effort from roster matching)
    player_team_map: dict[str, str] = {}
    team_inactives: dict[str, list[str]] = {}   # abbr -> list of inactive roster names

    for abbr, roster in per_team_roster.items():
        inactive: list[str] = []
        for rname in roster:
            if _name_on_slate(rname):
                # Player is on slate → mark which team they play for
                rn = _norm_name(rname)
                for slate_name in on_slate:
                    sn = _norm_name(slate_name)
                    if rn in sn or sn in rn:
                        player_team_map[slate_name] = abbr
            # A missing prop listing is not an injury report.
        team_inactives[abbr] = inactive
        if inactive:
            print(f"  {abbr} likely inactive ({len(inactive)}): {', '.join(inactive[:5])}"
                  + (" ..." if len(inactive) > 5 else ""))

    # 4. Run EV analysis
    _write_progress(4, f"Connecting to DB (0/{len(on_slate)} players)...", players_total=len(on_slate))
    print(f"\n[4/4] Running EV analysis for {len(on_slate)} player(s)...")
    print("  Connecting to DB...", end=" ", flush=True)
    try:
        pool = await asyncio.wait_for(create_async_pool(), timeout=45.0)
    except asyncio.TimeoutError:
        print("TIMEOUT — DB unreachable after 45s. Aborting.")
        _PROGRESS_PATH.unlink(missing_ok=True)
        return
    except Exception as exc:
        print(f"ERROR — {exc}. Aborting.")
        _PROGRESS_PATH.unlink(missing_ok=True)
        return
    print("ready.")
    print("  Building LangGraph...", end=" ", flush=True)
    graph = create_graph(
        nba_quant_node=make_nba_quant_agent(pool, target_date=TARGET_DATE_OBJ),
        nba_context_producer_node=make_nba_context_signals_producer(pool, target_date=TARGET_DATE_OBJ),
        prop_arbitrage_node=make_prop_arbitrage_agent(sport="nba"),
    )
    print("ready.\n")

    ev_signals = []
    all_results = []
    no_data = []
    scan_start = time.perf_counter()

    for i, player_name in enumerate(on_slate, 1):
        _write_progress(
            4,
            f"Analyzing {player_name} ({i}/{len(on_slate)})...",
            players_total=len(on_slate),
            players_done=i - 1,
            current_player=player_name,
        )
        player_id = await resolve_player_id(pool, player_name)
        if not player_id:
            print(f"  [{i}/{len(on_slate)}] {player_name} — no player_id in DB, skipping", flush=True)
            continue
        print(f"  [{i}/{len(on_slate)}] {player_name} (id={player_id})", flush=True)
        thread_id = f"{THREAD_BASE}-{player_name.replace(' ', '_')}"
        t_player = time.perf_counter()
        # Determine which teammates are inactive for this player's team
        player_abbr = player_team_map.get(player_name)
        inactive_mates: list[str] = []
        if player_abbr and team_inactives.get(player_abbr):
            inactive_mates = team_inactives[player_abbr]
            if inactive_mates:
                print(f"    inactive teammates: {', '.join(inactive_mates[:3])}"
                      + (" ..." if len(inactive_mates) > 3 else ""), flush=True)

        player_results = await run_ev_for_player(
            pool=pool,
            graph=graph,
            all_snapshots=all_snapshots,
            player_name=player_name,
            player_id=player_id,
            home_team=home_team,
            away_team=away_team,
            thread_id=thread_id,
            inactive_teammates=inactive_mates if inactive_mates else None,
        )
        player_elapsed = time.perf_counter() - t_player
        n_props = len(player_results)
        n_ev    = sum(1 for r in player_results if r["ev"] and r["ev"].ev_percentage and float(r["ev"].ev_percentage) > 0)
        print(f"    done — {n_props} prop(s), {n_ev} +EV  ({player_elapsed:.1f}s)", flush=True)

        all_results.extend(player_results)
        for r in player_results:
            prop = r["prop"]
            ev   = r["ev"]
            pending = r["pending"]
            if ev and ev.ev_percentage and float(ev.ev_percentage) > 0:
                ev_signals.append(r)
            elif pending:
                ev_signals.append({**r, "gated": True})

    _write_progress(4, "Finalizing...", players_total=len(on_slate), players_done=len(on_slate))

    # Both directions share one durable daily budget and one-prop-per-player guard.
    ledger = Ledger()
    for r in sorted(all_results, key=lambda r: float(r['ev'].expected_return) if r.get('ev') else -1, reverse=True):
        sig, prop, quote = r.get('ev'), r.get('prop'), r.get('quote')
        accepted, reason = False, r.get('gate_reason') or 'no_positive_edge'
        if sig is not None:
            if quote is None or quote.game_start_time is None:
                reason = 'missing_start_time'
            elif datetime.now(timezone.utc) >= quote.game_start_time:
                reason = 'game_started'
            elif not -60 <= (datetime.now(timezone.utc) - quote.snapped_at).total_seconds() <= 300:
                reason = 'stale_quote'
            else:
                accepted, reason = ledger.reserve(sig, r['line'])
            r['gated'] = not accepted
        r['gate_reason'] = reason
        r['prediction_id'] = ledger.record(THREAD_BASE, {
            'game_id': _game_id, 'player': r['player'], 'prop_type': r['prop_type'],
            'direction': r['direction'], 'line': r['line'], 'sportsbook': r.get('snap_sportsbook'),
            'american_odds': r.get('snap_price'),
            'model_probability': float(sig.true_probability) if sig else (
                float(prop.true_probability if r['direction']=='over' else 1-prop.true_probability-prop.push_probability)
                if prop and prop.true_probability is not None else None),
            'push_probability': float(prop.push_probability) if prop else 0,
            'captured_at': datetime.now(timezone.utc).isoformat(),
            'game_start_time': quote.game_start_time.isoformat() if quote and quote.game_start_time else None,
            'quote_time': quote.snapped_at.isoformat() if quote else None,
            'synthetic_price': r.get('snap_sportsbook','').lower()=='prizepicks',
            'accepted': accepted, 'gate_reason': reason,
            'stake_fraction': float(sig.kelly_fraction) if accepted else 0,
            'sample_size': prop.sample_size if prop else 0,
            'model_version': 'empirical-v2',
        })

    # ── Persist signals to PostgreSQL ev_signals table (async, before pool close) ──
    if ev_signals:
        try:
            async with pool.acquire() as _conn:
                for _r in ev_signals:
                    _ev   = _r["ev"]
                    _pend = _r["pending"]
                    _sig  = _ev if (_ev and _ev.ev_percentage and float(_ev.ev_percentage) > 0) else (_pend[0] if _pend else None)
                    _prop = _r.get("prop")
                    _ctx  = _r.get("context")
                    if not _sig:
                        continue
                    _gated = _r.get("gated", False)
                    await _conn.execute(
                        """INSERT INTO ev_signals
                           (scan_id, game_id, home_team, away_team, game_date, player_name,
                            prop_type, line, true_probability, implied_probability, ev_percentage,
                            kelly_fraction, american_odds, sample_size, mean_stat, sportsbook,
                            gated, trade_plan, opponent_def_rating, rest_days, is_home, strength,
                            direction)
                           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18::jsonb,$19,$20,$21,$22,$23)
                        """,
                        THREAD_BASE,
                        f"{home_team.lower()}_{away_team.lower()}_{TARGET_DATE}",
                        home_team, away_team, TARGET_DATE,
                        _r["player"], _r["prop_type"],
                        _r["line"],
                        float(_sig.true_probability), float(_sig.implied_probability),
                        float(_sig.ev_percentage),
                        float(_sig.kelly_fraction) if not _gated else 0.0,
                        _r["snap_price"],
                        _prop.sample_size if _prop else None,
                        float(_prop.mean_stat) if (_prop and _prop.mean_stat) else None,
                        _r.get("snap_sportsbook", "unknown"),
                        _gated,
                        json.dumps(list(_sig.trade_plan) if (not _gated and hasattr(_sig, "trade_plan") and _sig.trade_plan) else []),
                        float(_ctx.opponent_def_rating) if _ctx else None,
                        _ctx.rest_days if _ctx else None,
                        _ctx.is_home if _ctx else None,
                        "unrated",
                        _r.get("direction", "over"),
                    )
            print(f"  {len(ev_signals)} signal(s) persisted to ev_signals table.")
        except Exception as _db_exc:
            print(f"  [!] DB persistence failed (non-fatal): {_db_exc}")

    # Close pool with timeout — asyncpg hangs on Windows SelectorEventLoop without it
    try:
        await asyncio.wait_for(pool.close(), timeout=8.0)
    except (asyncio.TimeoutError, Exception):
        pass  # Process exits anyway; connections cleaned up by OS

    total_elapsed = time.perf_counter() - scan_start
    print(f"\n  Scan complete — {total_elapsed:.1f}s total")

    # ── Final report ─────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"  EV REPORT — {TEAM_A} vs {TEAM_B}")
    print(f"  Game: {away_team} @ {home_team}  |  {TARGET_DATE}")
    print("=" * 60)

    if not ev_signals:
        print("\n  No +EV opportunities found on current slate.")
    else:
        print(f"\n  {len(ev_signals)} signal(s) found:\n")
        for r in sorted(ev_signals, key=lambda x: float((x.get("ev") or x.get("pending", [None])[0]).ev_percentage or 0), reverse=True):
            ev   = r["ev"]
            pending = r["pending"]
            sig  = ev if (ev and ev.ev_percentage and float(ev.ev_percentage) > 0) else (pending[0] if pending else None)
            if not sig:
                continue
            gated = r.get("gated", False)
            tag = " [GATED]" if gated else ""
            _dir_label = "U" if r.get("direction") == "under" else "O"
            print(f"  {r['player']} — {r['prop_type'].replace('player_','').upper()} {_dir_label}{r['line']}{tag}")
            print(f"    EV:          +{float(sig.ev_percentage):.2%}")
            print(f"    Model prob:  {float(sig.true_probability):.1%}")
            print(f"    Implied:     {float(sig.implied_probability):.1%}")
            if not gated:
                print(f"    Kelly stake: {float(sig.kelly_fraction):.2%} of bankroll")
            prop = r.get("prop")
            if prop and prop.true_probability:
                print(f"    Sample:      {prop.sample_size} games | mean {float(prop.mean_stat or 0):.1f}")
            if not gated and hasattr(sig, "trade_plan") and sig.trade_plan:
                print(f"    Trade Plan:")
                for bullet in sig.trade_plan:
                    print(f"      - {bullet}".encode("ascii", "replace").decode("ascii"))
            print()

    if no_data:
        print(f"  No DB data for: {', '.join(no_data)}")

    print("=" * 60)

    # ── JSON cache export — written BEFORE the print loop so a print crash ────
    # ── (e.g. Windows cp1252 encoding on μ) cannot block the frontend update. ─
    cache_path = pathlib.Path(__file__).parent / "frontend" / "public" / "signals_cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    export = []
    for r in ev_signals:
        ev      = r["ev"]
        pending = r["pending"]
        sig     = ev if (ev and ev.ev_percentage and float(ev.ev_percentage) > 0) else (pending[0] if pending else None)
        prop    = r.get("prop")
        ctx     = r.get("context")
        snap_price = r.get("snap_price", -115)
        if not sig:
            continue

        is_home = ctx.is_home if ctx else None
        player_team     = home_team if is_home is True else away_team
        player_opponent = away_team if is_home is True else home_team

        export.append({
            "id": r["prediction_id"],
            "player":        r["player"],
            "team":          player_team,
            "opponent":      player_opponent,
            "sport":         "nba",
            "prop_type":     r["prop_type"].replace("player_", ""),
            "line":          r["line"],
            "direction":     r.get("direction", "over"),
            "true_prob":     float(sig.true_probability),
            "implied_prob":  float(sig.implied_probability),
            "ev_pct":        float(sig.ev_percentage),
            "expected_return": float(sig.expected_return),
            "push_probability": float(sig.push_probability),
            "confidence_interval": [float(x) for x in sig.confidence_interval] if sig.confidence_interval else None,
            "data_source": sig.data_source,
            "prediction_id": r.get('prediction_id'),
            "gate_reason": r.get('gate_reason'),
            "kelly_fraction": float(sig.kelly_fraction) if not r.get("gated") else 0.0,
            "american_odds": snap_price,
            "sportsbook":    r.get("snap_sportsbook", "unknown"),
            "trade_plan":    list(sig.trade_plan) if (not r.get("gated") and hasattr(sig, "trade_plan") and sig.trade_plan) else [
                f"+{float(sig.ev_percentage):.1%} EV edge on {r['prop_type'].replace('player_','')} market",
                "Kelly sizing gated by daily drawdown cap",
                "No material injury flags for this game",
            ],
            "injury_flags":   {},
            "market_type":    r["prop_type"],
            "snapped_at": r["quote"].snapped_at.isoformat(),
            "game_start_time": r["quote"].game_start_time.isoformat() if r["quote"].game_start_time else None,
            "model_version": "empirical-v2",
            "strength": "unrated",
            "gated":          r.get("gated", False),
            "sample_size":    prop.sample_size if prop else None,
            "mean_stat":      float(prop.mean_stat) if (prop and prop.mean_stat) else None,
            "home_team":      home_team,
            "away_team":      away_team,
            "opponent_def_rating": float(ctx.opponent_def_rating) if ctx else None,
            "rest_days":      ctx.rest_days if ctx else None,
            "is_home":        ctx.is_home if ctx else None,
        })

    out = _merge_signals_cache(cache_path, _game_id, home_team, away_team, export)
    tmp_path = cache_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    tmp_path.replace(cache_path)
    _PROGRESS_PATH.unlink(missing_ok=True)
    print(f"  Signals cached -> {cache_path} ({len(export)} signal(s))")

    # ── Console report (non-critical — encoding errors here don't affect output) ─
    for r in sorted(ev_signals, key=lambda x: float((x.get("ev") or x.get("pending", [None])[0]).ev_percentage or 0), reverse=True):
        ev_r   = r["ev"]
        pending = r["pending"]
        sig  = ev_r if (ev_r and ev_r.ev_percentage and float(ev_r.ev_percentage) > 0) else (pending[0] if pending else None)
        if not sig:
            continue
        gated = r.get("gated", False)
        tag = " [GATED]" if gated else ""
        prop = r.get("prop")
        try:
            _dir_label2 = "U" if r.get("direction") == "under" else "O"
            print(f"  {r['player']} -- {r['prop_type'].replace('player_','').upper()} {_dir_label2}{r['line']}{tag}")
            print(f"    EV:         +{float(sig.ev_percentage):.2%}")
            print(f"    Model prob: {float(sig.true_probability):.1%}")
            print(f"    Implied:    {float(sig.implied_probability):.1%}")
            if not gated:
                print(f"    Kelly:      {float(sig.kelly_fraction):.2%} of bankroll")
            if prop and prop.true_probability:
                print(f"    Sample:     {prop.sample_size} games | mean {float(prop.mean_stat or 0):.1f}")
            if not gated and hasattr(sig, "trade_plan") and sig.trade_plan:
                for bullet in sig.trade_plan:
                    safe = bullet.encode("ascii", errors="replace").decode("ascii")
                    print(f"      - {safe}")
            print()
        except Exception:
            pass  # encoding or other print error — cache already written, continue


if __name__ == "__main__":
    asyncio.run(main())
