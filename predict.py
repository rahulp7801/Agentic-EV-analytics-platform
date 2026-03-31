"""
Full end-to-end pipeline test:
  Step 1 -- Fetch live NBA props directly from PrizePicks (no DB write)
  Step 2 -- nba_prop_analysis: compute model probability + EV signal

Strategy: bypass the LangGraph context_update node (which writes thousands
of rows to Supabase — takes 35+ min). Instead, fetch PrizePicks props in
memory, build PlayerPropSnapshotCreate objects directly, then pass them into
nba_prop_analysis via graph state. This tests the full quant/EV pipeline
without the snapshot-persistence bottleneck.
"""
import sys
sys.path.insert(0, 'src')
sys.path.insert(0, 'site-packages')

import asyncio
import platform
# asyncpg requires SelectorEventLoop on Windows
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from datetime import datetime, timezone
from decimal import Decimal
from dotenv import load_dotenv
load_dotenv()

from sportsbet.db.connection import create_async_pool
from sportsbet.graph.graph import create_graph_with_sqlite
from sportsbet.ingestion.free_odds import PrizePicksPoller
from sportsbet.ingestion.prop_odds import PlayerPropSnapshotCreate
from sportsbet.quant.vig import american_to_raw_prob
from sportsbet.config import settings

# Fresh thread ID each run — avoids replaying stale SQLite checkpoint state
THREAD_ID = f"predict-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

# Target player — edit to test any player on today's PrizePicks slate
PLAYER_ID = "203952"          # Andrew Wiggins NBA.com ID
PLAYER_NAME = "Andrew Wiggins"
HOME_TEAM = "MIA"
AWAY_TEAM = "IND"


async def fetch_prizepicks_snapshots(sport: str = "nba") -> list[PlayerPropSnapshotCreate]:
    """Fetch PrizePicks props and convert to PlayerPropSnapshotCreate objects (no DB write)."""
    async with PrizePicksPoller() as pp:
        raw_events = await pp.fetch_player_props(sport)

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
                        sportsbook=bookmaker.get("key", "prizepicks"),
                        prop_type=market.get("key", "unknown"),
                        line=Decimal(str(point)),
                        price=int(price),
                        implied_probability=Decimal(str(round(float(raw_prob), 6))),
                        side=outcome.get("name", ""),
                    ))
    return snapshots


async def main():
    print(f"DB:  {'asyncpg pool'}")
    print(f"Run: {THREAD_ID}")

    # ── Step 1: Fetch PrizePicks props in memory (no Supabase write) ──────────
    print(f"\n[1/2] Fetching PrizePicks NBA props (in-memory, no DB write)...")
    snapshots = await fetch_prizepicks_snapshots("nba")
    print(f"  Props loaded: {len(snapshots)}")

    # Find the player's Over snapshot to display the line we'll test
    player_snap = next(
        (s for s in snapshots
         if PLAYER_NAME.lower() in s.player_name.lower()
         and s.prop_type == "player_points"
         and s.side == "Over"),
        None
    )
    if player_snap:
        prop_line = float(player_snap.line)
        print(f"  {PLAYER_NAME} points line: {prop_line} @ {player_snap.price} "
              f"(implied={float(player_snap.implied_probability):.1%})")
    else:
        # Fall back to a manual line if player not on today's slate
        prop_line = 12.5
        print(f"  [!] {PLAYER_NAME} not found on PrizePicks today — using manual line {prop_line}")
        pts_samples = [s for s in snapshots if s.prop_type == "player_points" and s.side == "Over"][:5]
        for s in pts_samples:
            print(f"      on slate: {s.player_name} {s.line}")

    # ── Step 2: nba_prop_analysis — model prob + EV ───────────────────────────
    print(f"\n[2/2] nba_prop_analysis: {PLAYER_NAME} Points Over {prop_line} (NBA_id={PLAYER_ID})...")

    pool = await create_async_pool()
    graph = await create_graph_with_sqlite(
        pool=pool,
        api_key=settings.odds_api_key,
    )

    result = await graph.ainvoke(
        {
            "session_id": "predict-test",
            "game_id": f"{HOME_TEAM.lower()}_{AWAY_TEAM.lower()}_{datetime.now().strftime('%Y%m%d')}",
            "season": 2025,
            "week": 1,
            "home_team": HOME_TEAM,
            "away_team": AWAY_TEAM,
            "injury_flags": {},
            "weather_json": None,
            "receiver_gsis_id": PLAYER_ID,
            "player_name": PLAYER_NAME,
            "prop_type": "points",
            "prop_line": prop_line,
            "sport": "nba",
            "created_at": datetime.now(timezone.utc),
            "request_type": "nba_prop_analysis",
            "player_prop_snapshots": snapshots,
        },
        config={"configurable": {"thread_id": THREAD_ID}},
    )

    prop = result.get("nba_prop_result")
    ev = result.get("ev_signal")
    pending = result.get("pending_signals") or []  # pre-aggregator signals

    print("\n==========================================")
    print("  PROP MODEL RESULT")
    print("==========================================")
    if prop:
        tp = prop.true_probability
        ms = prop.mean_stat
        print(f"  Player:          {PLAYER_NAME}")
        print(f"  Prop:            Points Over {prop_line}")
        print(f"  True probability: {float(tp):.1%}" if tp else "  True probability: insufficient sample")
        print(f"  Historical mean:  {float(ms):.1f} pts/game" if ms else "")
        print(f"  Sample size:      {prop.sample_size} games")
        print(f"  Data source:      {prop.data_source}")
        if prop.confidence_interval:
            lo, hi = prop.confidence_interval
            print(f"  Wilson CI 95%:    [{float(lo):.1%}, {float(hi):.1%}]")
    else:
        print("  No prop result — check DB for nba_player_stats season=2025")

    print("\n==========================================")
    print("  EV SIGNAL")
    print("==========================================")
    if ev and ev.ev_percentage and float(ev.ev_percentage) > 0:
        print(f"  EV:              +{float(ev.ev_percentage):.2%}")
        print(f"  Kelly stake:     {float(ev.kelly_fraction):.2%} of bankroll")
        print(f"  Model prob:      {float(ev.true_probability):.1%}")
        print(f"  Implied prob:    {float(ev.implied_probability):.1%}")
        print(f"  Market type:     {ev.market_type}")
        print(f"\n  Trade Plan:")
        for bullet in ev.trade_plan:
            print(f"    - {bullet}")
    elif ev:
        print(f"  -EV — model_prob={float(ev.true_probability or 0):.1%} "
              f"vs implied={float(ev.implied_probability or 0):.1%}")
        print("  No action recommended")
    elif pending:
        # Signal computed but blocked by aggregator daily drawdown gate
        s = pending[0]
        print(f"  [GATED] Signal blocked by daily drawdown limit (Kelly > 5% cap):")
        print(f"  EV:          +{float(s.ev_percentage):.2%}")
        print(f"  Kelly stake: {float(s.kelly_fraction):.2%} of bankroll")
        print(f"  Model prob:  {float(s.true_probability):.1%}")
        print(f"  Implied:     {float(s.implied_probability):.1%}")
        print(f"  (Raise daily_drawdown_limit in create_graph_with_sqlite to accept)")
    else:
        print("  No EV signal (no live odds matched or no prop result)")

    print("\n==========================================")
    print("  PIPELINE STATUS")
    print("==========================================")
    print(f"  Snapshots:   {len(snapshots)}")
    print(f"  Model:       {'YES' if prop and prop.true_probability else 'NO'}")
    if ev and ev.ev_percentage and float(ev.ev_percentage) > 0:
        ev_status = "POSITIVE"
    elif pending:
        ev_status = f"GATED (+{float(pending[0].ev_percentage):.1%} EV blocked by drawdown cap)"
    else:
        ev_status = "NONE/NEGATIVE"
    print(f"  EV signal:   {ev_status}")

    if result.get("error"):
        print(f"\n  Error: {result['error']}")

    await pool.close()


asyncio.run(main())
