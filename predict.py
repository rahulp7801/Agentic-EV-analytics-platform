"""
Full end-to-end pipeline test:
  Step 1 — context_update: fetch live NBA odds + player prop snapshots from The Odds API
  Step 2 — nba_prop_analysis: compute probability vs historical DB data, then compute EV signal
"""
import asyncio
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv()

from sportsbet.db.connection import create_async_pool
from sportsbet.graph.graph import create_graph_with_sqlite
from sportsbet.config import settings

THREAD_ID = "live-test-10"

# LeBron James NBA player ID (LAL has ESPN propBets posted today)
PLAYER_ID = "2544"
PLAYER_NAME = "LeBron James"

async def main():
    print(f"Odds API key loaded: {'YES' if settings.odds_api_key else 'NO - check .env'}")

    pool = await create_async_pool()
    graph = await create_graph_with_sqlite(
        pool=pool,
        api_key=settings.odds_api_key,
    )

    base_state = {
        "session_id": "live-test",
        "game_id": "bos_atl_today",
        "season": 2024,
        "week": 1,
        "home_team": "LAL",
        "away_team": "BKN",
        "injury_flags": {},
        "weather_json": None,
        "receiver_gsis_id": PLAYER_ID,
        "player_name": PLAYER_NAME,
        "prop_type": "points",
        "prop_line": 24.5,
        "sport": "nba",
        "created_at": datetime.now(timezone.utc),
    }

    # ── Step 1: Pull live NBA odds + player prop snapshots ──────────────────
    print("\n[1/2] Fetching live NBA odds and player prop snapshots...")
    ctx_result = await graph.ainvoke(
        {**base_state, "request_type": "context_update"},
        config={"configurable": {"thread_id": THREAD_ID}},
    )

    snapshots = ctx_result.get("player_prop_snapshots") or []
    print(f"  Player prop snapshots fetched: {len(snapshots)}")

    # Find the player's Over points snapshot to preview the odds we'll compare against
    player_snap = next(
        (s for s in snapshots
         if PLAYER_NAME.lower() in s.player_name.lower()
         and s.prop_type == "player_points"
         and getattr(s, "side", "Over") in ("Over", "")),
        None
    )
    if player_snap:
        print(f"  Found {PLAYER_NAME} snapshot: line={player_snap.line}, "
              f"implied_prob={float(player_snap.implied_probability):.1%}, "
              f"book={player_snap.sportsbook}, side={getattr(player_snap, 'side', '?')}")
    else:
        print(f"  No live {PLAYER_NAME} points snapshot found (no game today or API returned no match)")

    # ── Step 2: Run NBA prop analysis + EV signal ───────────────────────────
    print(f"\n[2/2] Running NBA prop analysis for {PLAYER_NAME} points (line: 24.5)...")
    result = await graph.ainvoke(
        {**base_state, "request_type": "nba_prop_analysis"},
        config={"configurable": {"thread_id": THREAD_ID}},
    )

    prop = result.get("nba_prop_result") or result.get("prop_result")
    ev = result.get("ev_signal")

    print("\n==========================================")
    print("  PROP RESULT")
    print("==========================================")
    if prop:
        print(f"  Player:          {PLAYER_NAME}")
        print(f"  Prop:            Points O/U 24.5")
        print(f"  True probability:{float(prop.true_probability):.1%}" if prop.true_probability else "  True probability: insufficient sample")
        print(f"  Historical mean: {float(prop.mean_stat):.1f} pts/game" if prop.mean_stat else "")
        print(f"  Sample size:     {prop.sample_size} games")
        print(f"  Data source:     {prop.data_source}")
    else:
        print("  No prop result returned")

    print("\n==========================================")
    print("  EV SIGNAL")
    print("==========================================")
    if ev:
        print(f"  EV:              +{float(ev.ev_percentage):.2%}")
        print(f"  Kelly stake:     {float(ev.kelly_fraction):.2%} of bankroll")
        print(f"  Trade plan:")
        for bullet in ev.trade_plan:
            print(f"    • {bullet}")
    else:
        print("  No +EV signal (either -EV, no live odds, or line already matched true prob)")

    if result.get("error"):
        print(f"\n  Error: {result['error']}")

asyncio.run(main())
