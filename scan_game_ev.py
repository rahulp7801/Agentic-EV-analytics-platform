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
from sportsbet.graph.graph import create_graph_with_sqlite
from sportsbet.ingestion.free_odds import PrizePicksPoller, ESPNPropsPoller
from sportsbet.ingestion.prop_odds import PlayerPropSnapshotCreate
from sportsbet.quant.vig import american_to_raw_prob
from sportsbet.config import settings
from sportsbet.arbitrage.ev import compute_expected_return, quote_terms
from sportsbet.arbitrage.kelly import fractional_kelly

# ── Under signal support ──────────────────────────────────────────────────────
from dataclasses import dataclass, field as _field
from decimal import Decimal as _Decimal

@dataclass
class _SyntheticSignal:
    """Minimal EVSignal-compatible container for synthetic Under signals."""
    ev_percentage: _Decimal
    true_probability: _Decimal
    implied_probability: _Decimal
    kelly_fraction: _Decimal
    trade_plan: list[str] = _field(default_factory=list)
    market_type: str = ""


def _under_kelly(true_prob: float, american_odds: int, fraction: float = 0.25) -> float:
    """Fractional Kelly for a bet at the given American odds."""
    _, payout = quote_terms(american_odds, Decimal("0"))
    return float(fractional_kelly(Decimal(str(true_prob)), payout, Decimal(str(fraction))))


_LEAGUE_AVG_DEF = 115.0


def _build_under_trade_plan(
    ev_pct: float,
    kelly: float,
    prop_type: str,
    line: float,
    mean_stat,
    sample_size,
    context,
    teammate_out: list[str] | None,
) -> list[str]:
    n = str(int(sample_size)) if sample_size is not None else "N/A"
    mean = f"{float(mean_stat):.1f}" if mean_stat is not None else "N/A"
    bullet_1 = (
        f"+{ev_pct:.1%} EV edge on {prop_type} UNDER {line} | "
        f"n={n} games, mu={mean} historical"
    )
    if context:
        def_r = float(context.opponent_def_rating)
        def_d = def_r - _LEAGUE_AVG_DEF
        if def_d < -0.5:
            def_tag = f"opp def {def_r:.1f} < avg {_LEAGUE_AVG_DEF:.0f} (strong D -> favorable for Under)"
        elif def_d > 0.5:
            def_tag = f"opp def {def_r:.1f} > avg {_LEAGUE_AVG_DEF:.0f} (weak D -> risk factor for Under)"
        else:
            def_tag = f"opp def {def_r:.1f} approx avg (neutral)"
        rd = context.rest_days
        rest_tag = ("B2B (fatigue -> favorable for Under)" if rd == 0
                    else "1d rest (standard)" if rd == 1
                    else f"{rd}d rest (well-rested -- slight risk for Under)")
        home_tag = "HOME (home boost -> risk for Under)" if context.is_home else "AWAY (no home boost)"
        tm_tag = ""
        if teammate_out:
            tm_tag = f" - conditioned on {', '.join(teammate_out[:2])} inactive"
        bullet_2 = f"Context: {def_tag} - {rest_tag} - {home_tag}{tm_tag}"
    else:
        bullet_2 = "Context unavailable -- edge based on historical distribution only"
    bullet_3 = f"Kelly: {kelly:.1%} bankroll stake (fractional, not flat) - No material injury flags"
    return [bullet_1, bullet_2, bullet_3]


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
SEASON  = 2025
FORCE   = _args.force
TARGET_DATE_OBJ = datetime.strptime(TARGET_DATE, "%Y%m%d").date()

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

    # PrizePicks-only goblin filter: -110 = easy "goblin" line with inflated hit rate.
    # Real sportsbooks (DraftKings, FanDuel) price standard lines at -110 — that is NOT
    # a goblin; it is the normal market vig. Only filter -110 for PrizePicks source.
    def _is_prizepicks_goblin(s: PlayerPropSnapshotCreate) -> bool:
        return s.sportsbook.lower() == "prizepicks" and int(s.price) == -110

    prop_types = list({
        s.prop_type for s in all_snapshots
        if player_name.lower() in s.player_name.lower()
        and s.side == "Over"
        and s.prop_type in _SUPPORTED_PROP_TYPES
        and not _is_prizepicks_goblin(s)
    })

    results = []
    for prop_idx, prop_type in enumerate(prop_types, 1):
        snaps = sorted(
            [s for s in all_snapshots
             if player_name.lower() in s.player_name.lower()
             and s.prop_type == prop_type
             and s.side == "Over"
             and not _is_prizepicks_goblin(s)],
            key=lambda s: american_to_raw_prob(s.price),
        )
        if not snaps:
            continue
        snap = snaps[0]
        prop_line = float(snap.line)

        prop_label = prop_type.replace("player_", "").upper()
        print(f"      [{prop_idx}/{len(prop_types)}] {prop_label} O{prop_line} — invoking graph...", flush=True)
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

        results.append({
            "player":     player_name,
            "prop_type":  prop_type,
            "line":       prop_line,
            "prop":       prop,
            "ev":         ev,
            "pending":    pending,
            "context":    context,
            "snap_price": int(snap.price),
            "snap_sportsbook": snap.sportsbook,
            "direction":  "over",
        })

        # ── Under evaluation: compute 1-true_prob vs Under implied prob ──────
        # Skip when P(Over) hit the probability floor (0.01) — that means the
        # NormalDist model ran out of resolution (line is far above historical mean).
        # Producing an Under signal here would just be 1 - floor = 0.99, which is a
        # model artifact, not a genuine edge.
        #
        # Also skip if the Over snap itself was a PrizePicks goblin line (-110 from
        # PrizePicks). Goblin lines are easy lines set well above a player's true mean —
        # their complementary Unders would always show huge +EV because 1-P(easy_over)
        # is structurally inflated. The Over side is already filtered; we must filter
        # the Under side too to avoid surfacing the same artifact from the other direction.
        _p_over_raw = float(prop.true_probability) if prop and prop.true_probability else 0.0
        if prop and prop.true_probability and _p_over_raw > 0.01 and not _is_prizepicks_goblin(snap):
            under_snaps = sorted(
                [s for s in all_snapshots
                 if player_name.lower() in s.player_name.lower()
                 and s.prop_type == snap.prop_type
                 and s.line == snap.line
                 and s.side == "Under"],
                key=lambda s: american_to_raw_prob(s.price),
            )
            if under_snaps:
                u_snap = under_snaps[0]
                u_true = 1.0 - float(prop.true_probability)
                u_implied = float(american_to_raw_prob(int(u_snap.price)))
                u_ev = u_true - u_implied
                u_price = int(u_snap.price)
                u_kelly = _under_kelly(u_true, u_price, settings.max_kelly_fraction)
                # EV cap: mirror the _EV_CAP = 0.15 guard from prop_arbitrage_agent.
                # Under signals bypass the LangGraph arbitrage node and must apply the
                # same ceiling inline. Anything above 15% is almost certainly model
                # overconfidence vs. a soft line, not a genuine market inefficiency.
                _UNDER_EV_CAP: float = 0.15
                if u_ev > 0 and u_ev <= _UNDER_EV_CAP and u_kelly > 0:
                    u_plan = _build_under_trade_plan(
                        u_ev, u_kelly,
                        prop_type.replace("player_", ""),
                        prop_line,
                        prop.mean_stat, prop.sample_size,
                        context,
                        inactive_teammates,
                    )
                    u_sig = _SyntheticSignal(
                        ev_percentage=_Decimal(str(round(u_ev, 6))),
                        true_probability=_Decimal(str(round(u_true, 6))),
                        implied_probability=_Decimal(str(round(u_implied, 6))),
                        kelly_fraction=_Decimal(str(round(u_kelly, 6))),
                        trade_plan=u_plan,
                        market_type=snap.prop_type,
                    )
                    results.append({
                        "player":        player_name,
                        "prop_type":     prop_type,
                        "line":          prop_line,
                        "prop":          prop,
                        "ev":            u_sig,
                        "pending":       [],
                        "context":       context,
                        "snap_price":    u_price,
                        "snap_sportsbook": u_snap.sportsbook,
                        "direction":     "under",
                    })

    return results


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
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

    # 2b. Check DB cache — if this game_id already has signals, skip API calls
    _game_id = f"{home_team.lower()}_{away_team.lower()}_{TARGET_DATE}"
    _cached_rows: list[dict] = []
    if not FORCE:
        _write_progress(2, f"Checking DB cache for {_game_id}...")
        print(f"\n[2b] Checking DB cache for {_game_id}...")
        try:
            _pool_check = await asyncio.wait_for(create_async_pool(), timeout=45.0)
            _cached_rows = await load_signals_from_db(_pool_check, _game_id)
            try:
                await asyncio.wait_for(_pool_check.close(), timeout=8.0)
            except Exception:
                pass
        except Exception as _ce:
            _cached_rows = []
            print(f"  [!] DB cache check failed (non-fatal): {_ce}")
    else:
        print(f"\n[2b] --force flag set — bypassing DB cache.")

    if _cached_rows:
        print(f"  Found {len(_cached_rows)} cached signal(s) in DB — skipping API calls.")
        cache_path = pathlib.Path(__file__).parent / "frontend" / "public" / "signals_cache.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        # Convert DB rows to the same export format as the full scan
        _export: list[dict] = []
        for _row in _cached_rows:
            _trade_plan = _row.get("trade_plan")
            if isinstance(_trade_plan, str):
                try:
                    _trade_plan = json.loads(_trade_plan)
                except Exception:
                    _trade_plan = []
            _pt = str(_row.get("prop_type", "")).replace("player_", "")
            _is_home = _row.get("is_home")
            _player_team     = home_team if _is_home is True else away_team
            _player_opponent = away_team if _is_home is True else home_team
            _direction = _row.get("direction") or "over"
            _export.append({
                "id": f"{str(_row['player_name']).replace(' ','_').lower()}_{_row['prop_type']}{'_under' if _direction == 'under' else ''}",
                "player": _row["player_name"],
                "team": _player_team,
                "opponent": _player_opponent,
                "sport": "nba",
                "prop_type": _pt,
                "line": float(_row["line"]),
                "direction": _direction,
                "true_prob": float(_row["true_probability"]),
                "implied_prob": float(_row["implied_probability"]),
                "ev_pct": float(_row["ev_percentage"]),
                "expected_return": float(compute_expected_return(
                    Decimal(str(_row["true_probability"])),
                    quote_terms(int(_row["american_odds"]), Decimal("0"))[1],
                )),
                "kelly_fraction": float(_row["kelly_fraction"]) if not _row.get("gated") else 0.0,
                "american_odds": int(_row["american_odds"]),
                "sportsbook": _row.get("sportsbook", "unknown"),
                "trade_plan": _trade_plan or [],
                "strength": _row.get("strength", "medium"),
                "gated": bool(_row.get("gated", False)),
                "sample_size": _row.get("sample_size"),
                "mean_stat": float(_row["mean_stat"]) if _row.get("mean_stat") is not None else None,
                "home_team": home_team,
                "away_team": away_team,
                "opponent_def_rating": float(_row["opponent_def_rating"]) if _row.get("opponent_def_rating") is not None else None,
                "rest_days": _row.get("rest_days"),
                "is_home": _is_home,
                "snapped_at": datetime.now(timezone.utc).isoformat(),
            })
        _combined = _merge_signals_cache(cache_path, _game_id, home_team, away_team, _export)
        _tmp = cache_path.with_suffix(".tmp")
        _tmp.write_text(json.dumps(_combined, indent=2), encoding="utf-8")
        _tmp.replace(cache_path)
        _PROGRESS_PATH.unlink(missing_ok=True)
        print(f"  Signals loaded from DB cache -> {cache_path}")
        print(f"  (Re-run with --force to bypass cache and re-scan)")
        return

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
            else:
                inactive.append(rname)
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
    graph = await create_graph_with_sqlite(pool=pool, api_key=settings.odds_api_key, target_date=TARGET_DATE_OBJ)
    print("ready.\n")

    ev_signals = []
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

        for r in player_results:
            prop = r["prop"]
            ev   = r["ev"]
            pending = r["pending"]
            if ev and ev.ev_percentage and float(ev.ev_percentage) > 0:
                ev_signals.append(r)
            elif pending:
                ev_signals.append({**r, "gated": True})

    _write_progress(4, "Finalizing...", players_total=len(on_slate), players_done=len(on_slate))

    # ── Persist signals to PostgreSQL ev_signals table (async, before pool close) ──
    if ev_signals:
        try:
            async with pool.acquire() as _conn:
                await _conn.execute("""
                    CREATE TABLE IF NOT EXISTS ev_signals (
                        id BIGSERIAL PRIMARY KEY,
                        scan_id VARCHAR(30) NOT NULL,
                        game_id VARCHAR(50) NOT NULL,
                        home_team VARCHAR(5) NOT NULL,
                        away_team VARCHAR(5) NOT NULL,
                        game_date VARCHAR(8) NOT NULL,
                        player_name VARCHAR(100) NOT NULL,
                        prop_type VARCHAR(40) NOT NULL,
                        line NUMERIC(7,2) NOT NULL,
                        true_probability NUMERIC(8,6) NOT NULL,
                        implied_probability NUMERIC(8,6) NOT NULL,
                        ev_percentage NUMERIC(8,6) NOT NULL,
                        kelly_fraction NUMERIC(8,6) NOT NULL,
                        american_odds SMALLINT NOT NULL,
                        sample_size SMALLINT,
                        mean_stat NUMERIC(7,2),
                        sportsbook VARCHAR(50) NOT NULL,
                        gated BOOLEAN NOT NULL DEFAULT FALSE,
                        trade_plan JSONB,
                        opponent_def_rating NUMERIC(7,2),
                        rest_days SMALLINT,
                        is_home BOOLEAN,
                        strength VARCHAR(10) NOT NULL DEFAULT 'medium',
                        direction VARCHAR(5) NOT NULL DEFAULT 'over',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                # Add direction column to pre-existing tables that lack it
                await _conn.execute(
                    "ALTER TABLE ev_signals ADD COLUMN IF NOT EXISTS direction VARCHAR(5) DEFAULT 'over'"
                )
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
                        "high" if float(_sig.ev_percentage) >= 0.15 else "medium",
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
            "id":            f"{r['player'].replace(' ','_').lower()}_{r['prop_type']}{'_under' if r.get('direction')=='under' else ''}",
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
            "expected_return": float(compute_expected_return(
                sig.true_probability, quote_terms(snap_price, Decimal("0"))[1],
            )),
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
            "snapped_at":     datetime.now(timezone.utc).isoformat(),
            "strength":       "high" if float(sig.ev_percentage) >= 0.15 else "medium",
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
