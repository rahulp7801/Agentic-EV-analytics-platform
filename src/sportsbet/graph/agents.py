"""Agent nodes for the LangGraph state machine.

Phase 3 Plan 01 adds make_quant_agent(pool) — an async closure factory that
replaces the sync stub quant_agent with a real QuantParams -> SQL -> QuantResult
pipeline. The sync stub is preserved for backward-compat with tests that don't
pass a pool to create_graph().

Phase 4 Plan 04 adds make_context_agent(pool, api_key, daily_credit_cap) — an
async closure factory that replaces the sync stub context_agent. The real agent
fetches live NFL odds via OddsAPIPoller and injury reports via InjuryWeatherScraper,
assembles a ContextSignals object, and returns a partial GraphState dict. Downstream
agents read context_signals from state — never re-fetch the API.

Phase 5 Plan 01 adds make_arbitrage_agent(settings_override) — an async closure
factory that reads QuantResult and AgentOddsSnapshot from GraphState, computes
+EV percentage via fractional_kelly and compute_ev_percentage, and returns an
EVSignal with a 3-bullet trade plan. Negative-EV signals are suppressed entirely.

Phase replacement schedule:
- quant_agent (stub)  -> make_quant_agent(pool) closure (Phase 3)
- context_agent (stub) -> make_context_agent(pool, api_key, cap) closure (Phase 4)
- arbitrage_agent (stub) -> make_arbitrage_agent() closure (Phase 5, this plan)

Design: agents return dicts (partial state updates), not full GraphState.
LangGraph merges the returned dict into the current state using registered reducers.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any, Callable, Coroutine

import asyncpg
import httpx
import structlog

from sportsbet.db.connection import get_sync_engine
from sportsbet.graph.models import EVSignal, QuantParams, QuantResult
from sportsbet.graph.state import GraphState
from sportsbet.ingestion.odds import OddsSnapshotCreate, write_odds_snapshot
from sportsbet.ingestion.odds_poller import BudgetExhaustedError, OddsAPIPoller
from sportsbet.ingestion.prop_odds import PlayerPropSnapshotCreate, write_player_prop_snapshot
from sportsbet.ingestion.scraper import TEAM_ABBR_TO_ESPN_ID, InjuryWeatherScraper

if TYPE_CHECKING:
    pass

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Module-level pool cache (lazy init for production entrypoint)
# ---------------------------------------------------------------------------

_pool: asyncpg.Pool | None = None


async def get_or_create_pool() -> asyncpg.Pool:
    """Return the module-level asyncpg pool, creating it lazily on first call.

    Used by production entrypoints that don't manage pool lifecycle externally.
    Tests should create their own pool and pass it to make_quant_agent() directly.
    """
    global _pool
    if _pool is None:
        from sportsbet.db.connection import create_async_pool
        _pool = await create_async_pool()
    return _pool


# ---------------------------------------------------------------------------
# Real quant agent — closure factory (Phase 3)
# ---------------------------------------------------------------------------

def make_quant_agent(
    pool: asyncpg.Pool,
) -> Callable[[GraphState], Coroutine[Any, Any, dict[str, Any]]]:
    """Return an async quant agent node bound to the given asyncpg pool.

    The returned coroutine is compatible with LangGraph's async node interface:
    async def quant_agent(state: GraphState) -> dict

    Pipeline:
    1. Extract QuantParams from GraphState (raises ValidationError if invalid)
    2. Call run_quant_query(pool, params) to execute parameterized SQL
    3. Return partial state dict with quant_result set to QuantResult

    MIN_SAMPLE_SIZE gate is enforced inside run_quant_query — the agent always
    returns a valid QuantResult (possibly with data_source="insufficient_sample").
    """
    from sportsbet.quant.executor import run_quant_query

    async def quant_agent(state: GraphState) -> dict[str, Any]:  # type: ignore[type-arg]
        session_id = state["session_id"]
        log.info("quant_agent_invoked", session_id=session_id)

        try:
            params = QuantParams(
                game_id=state["game_id"],
                season=state["season"],
                week=state["week"],
                posteam=state["home_team"],  # default: query for home team offense
                stat_type="passing",         # default stat type; Context Agent will override
                filters={},
            )
            result = await run_quant_query(pool, params)
        except Exception as exc:
            log.error(
                "quant_agent_error",
                session_id=session_id,
                error=str(exc),
                exc_info=True,
            )
            return {
                "quant_result": QuantResult(data_source="error"),
                "error": str(exc),
            }

        log.info(
            "quant_agent_complete",
            session_id=session_id,
            data_source=result.data_source,
            sample_size=result.sample_size,
        )
        return {"quant_result": result}

    return quant_agent


# ---------------------------------------------------------------------------
# Real context agent — closure factory (Phase 4)
# ---------------------------------------------------------------------------

def make_context_agent(
    pool: asyncpg.Pool,
    api_key: str,
    daily_credit_cap: int,
    vig_method: str | None = None,
) -> Callable[[GraphState], Coroutine[Any, Any, dict[str, Any]]]:
    """Return an async context agent node bound to pool, api_key, and credit cap.

    Pipeline per invocation:
    1. Detect sport from state["sport"] (defaults to "nfl"); route to fetch_nba_odds or fetch_nfl_odds (Phase 15 — CTXT-04)
    2. Build odds_snapshot (first bookmaker h2h market) or None on budget exhaustion
    3. Persist odds snapshot to odds_snapshots table via write_odds_snapshot (DATA-03)
    4. Fetch injury reports for home + away teams via InjuryWeatherScraper
    5. Write injury rows to injury_reports table via pool
    6. Build injury_flags dict: {"P. Mahomes": "Out"} (status="Out"|"Questionable" only)
    7. Construct ContextSignals and return partial state dict

    Args:
        pool: asyncpg connection pool for injury report writes.
        api_key: The Odds API key.
        daily_credit_cap: Maximum credits per day (budget guard).
        vig_method: Devig method — "multiplicative" | "pinnacle" | None.
            None reads the value from Settings.vig_method (default "multiplicative").
            Passed to _extract_odds_snapshot on each invocation (Phase 15 — QUANT-02).

    On any sub-error (BudgetExhaustedError, httpx.HTTPError, ESPN schema error):
    - Log the error via structlog
    - Return ContextSignals with empty/None fields rather than propagating exception
    - Set state["error"] only for unrecoverable failures
    """
    from datetime import datetime, timezone

    from sportsbet.config import settings as _settings
    from sportsbet.graph.models import AgentOddsSnapshot, ContextSignals
    # OddsAPIPoller, BudgetExhaustedError, InjuryWeatherScraper imported at module level for patchability (Phase 14 — PROP-01)

    # Resolve vig_method at construction time — reads from Settings when not explicitly passed.
    # Stored in the closure so all invocations of context_agent() share the same resolved value.
    _vig_method = vig_method if vig_method is not None else _settings.vig_method

    # Lazily resolved on first agent invocation — avoids DB connection at construction
    # time. Stored in a mutable container so the closure can reassign it.
    # get_sync_engine and write_odds_snapshot are module-level names for patchability (DATA-03)
    _sync_engine_cache: list = []  # [engine] once initialized

    async def context_agent(state: GraphState) -> dict[str, Any]:  # type: ignore[type-arg]
        session_id = state["session_id"]
        game_id = state["game_id"]
        home_team = state["home_team"]
        away_team = state["away_team"]
        log.info("context_agent_invoked", session_id=session_id, game_id=game_id)

        # --- Step 1: Fetch odds (sport-routed) ---
        # Detect sport from GraphState — None and "nfl" both route to fetch_nfl_odds.
        # "nba" routes to fetch_nba_odds (Phase 15 — CTXT-04).
        sport = state.get("sport") or "nfl"  # type: ignore[attr-defined]

        odds_snapshot: AgentOddsSnapshot | None = None
        try:
            async with OddsAPIPoller(api_key=api_key, daily_credit_cap=daily_credit_cap) as poller:
                if sport == "nba":
                    raw_odds = await poller.fetch_nba_odds()
                else:
                    raw_odds = await poller.fetch_nfl_odds()
            # Extract first bookmaker h2h market for the matching game; dispatch vig_method (QUANT-02)
            odds_snapshot = _extract_odds_snapshot(raw_odds, game_id, vig_method=_vig_method)
        except BudgetExhaustedError as exc:
            log.warning("context_agent_budget_exhausted", session_id=session_id, error=str(exc))
        except Exception as exc:
            log.error("context_agent_odds_error", session_id=session_id, error=str(exc))

        # --- Step 1 (continued): Staleness gate (CTXT-02) ---
        if odds_snapshot is not None:
            from sportsbet.ingestion.odds_poller import is_stale as _is_stale
            if _is_stale(odds_snapshot.snapped_at):
                log.warning(
                    "context_agent_stale_odds_rejected",
                    session_id=session_id,
                    snapped_at=str(odds_snapshot.snapped_at),
                )
                odds_snapshot = None

        # --- Step 1b: Persist odds snapshot for CLV tracking (DATA-03) ---
        if odds_snapshot is not None:
            try:
                # Lazily initialize sync engine — avoids DB connection at closure construction time.
                # connect_args connect_timeout=5 prevents indefinite hang when DB is unavailable.
                if not _sync_engine_cache:
                    import sqlalchemy as _sa
                    from sportsbet.config import settings as _settings
                    _engine = _sa.create_engine(
                        _settings.database_url,
                        echo=False,
                        pool_pre_ping=True,
                        connect_args={"connect_timeout": 5},
                    )
                    _sync_engine_cache.append(_engine)
                snap_create = OddsSnapshotCreate(
                    game_id=odds_snapshot.game_id,
                    sportsbook=odds_snapshot.sportsbook,
                    market_type=odds_snapshot.market_type,
                    price=odds_snapshot.american_odds,  # non-null int for CLV tracking (GAP-3)
                )
                write_odds_snapshot(snap_create, engine=_sync_engine_cache[0])
                log.info("context_agent_odds_persisted", game_id=game_id)
            except Exception as exc:
                log.warning("context_agent_odds_persist_error", error=str(exc))

        # --- Step 1c: Fetch and persist NFL player prop snapshots (PROP-01) ---
        # Scoped to NFL only in Phase 14; NBA prop ingestion is Phase 15 territory.
        # Sync engine reuses _sync_engine_cache initialized in Step 1b.
        # write_player_prop_snapshot uses sync SQLAlchemy (v1 accepted tradeoff — low concurrency).
        try:
            async with OddsAPIPoller(api_key=api_key, daily_credit_cap=daily_credit_cap) as poller:
                raw_props = await poller.fetch_player_props("nfl")
            if not _sync_engine_cache:
                import sqlalchemy as _sa
                from sportsbet.config import settings as _settings_inner
                _sync_engine_cache.append(
                    _sa.create_engine(
                        _settings_inner.database_url,
                        echo=False,
                        pool_pre_ping=True,
                        connect_args={"connect_timeout": 5},
                    )
                )
            from sportsbet.quant.vig import american_to_raw_prob as _atrp
            from decimal import Decimal as _Dec
            for event_data in raw_props:
                for bookmaker in event_data.get("bookmakers", []):
                    for market in bookmaker.get("markets", []):
                        for outcome in market.get("outcomes", []):
                            price = outcome.get("price")
                            if price is None:
                                continue
                            try:
                                raw_prob = _atrp(int(price))
                                implied_prob = _Dec(str(round(float(raw_prob), 6)))
                                point = outcome.get("point")
                                snap = PlayerPropSnapshotCreate(
                                    sport="nfl",
                                    game_id=event_data.get("id"),
                                    player_name=outcome.get("name", "Unknown"),
                                    sportsbook=bookmaker.get("key", "unknown"),
                                    prop_type=market.get("key", "unknown"),
                                    line=_Dec(str(point)) if point is not None else None,
                                    price=int(price),
                                    implied_probability=implied_prob,
                                )
                                write_player_prop_snapshot(snap, engine=_sync_engine_cache[0])
                            except Exception as snap_exc:
                                log.warning("prop_snapshot_write_error", error=str(snap_exc))
            log.info("context_agent_props_persisted", game_id=game_id)
        except BudgetExhaustedError as exc:
            log.warning("context_agent_prop_budget_exhausted", error=str(exc))
        except Exception as exc:
            log.warning("context_agent_prop_fetch_error", error=str(exc))

        # --- Step 2: Fetch injury reports ---
        injury_flags: dict[str, str] = {}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                scraper = InjuryWeatherScraper(client)
                for team_abbr in (home_team, away_team):
                    team_id = TEAM_ABBR_TO_ESPN_ID.get(team_abbr)
                    if team_id is None:
                        log.warning("context_agent_unknown_team", team_abbr=team_abbr)
                        continue
                    injuries = await scraper.fetch_team_injuries(team_id)
                    await scraper.write_injury_reports(pool, injuries, team_abbr, game_id)
                    # Only flag Out and Questionable — skip Probable/Doubtful for signal clarity
                    for inj in injuries:
                        if inj.get("status") in ("Out", "Questionable"):
                            injury_flags[inj.get("player_name", "Unknown")] = inj["status"]
        except Exception as exc:
            log.error("context_agent_scraper_error", session_id=session_id, error=str(exc))

        # --- Step 3: Build ContextSignals and return ---
        signals = ContextSignals(
            game_id=game_id,
            injury_flags=injury_flags,
            weather_json=None,  # NFLWeather scraping deferred to v2
            odds_snapshot=odds_snapshot,
            signals_captured_at=datetime.now(timezone.utc),
        )
        log.info(
            "context_agent_complete",
            session_id=session_id,
            injury_count=len(injury_flags),
            has_odds=odds_snapshot is not None,
        )
        return {"context_signals": signals}

    return context_agent


def _extract_odds_snapshot(
    raw_odds: list[dict],
    game_id: str,
    vig_method: str = "multiplicative",
) -> "AgentOddsSnapshot | None":
    """Extract first bookmaker h2h market from Odds API response as AgentOddsSnapshot.

    Converts American odds to fair (devigged) Decimal implied_probability using
    the selected devig method (Phase 15 — QUANT-02):
    - "multiplicative" (default): remove_vig_multiplicative — proportional normalization.
      Both-positive-odds markets fall back to raw_probs to avoid ValueError propagation.
    - "pinnacle": remove_vig_power — power/binary-search devig correcting favorite-longshot bias.

    Returns None if raw_odds is empty, no h2h market found, or fewer than 2 outcomes.
    """
    from datetime import datetime, timezone

    from sportsbet.graph.models import AgentOddsSnapshot
    from sportsbet.quant.vig import american_to_raw_prob, remove_vig_multiplicative

    if not raw_odds:
        return None

    event = raw_odds[0]  # Use first event; caller may filter by game_id in future
    bookmakers = event.get("bookmakers", [])
    if not bookmakers:
        return None

    bookmaker = bookmakers[0]
    markets = bookmaker.get("markets", [])
    h2h = next((m for m in markets if m.get("key") == "h2h"), None)
    if h2h is None:
        return None

    outcomes = h2h.get("outcomes", [])
    if len(outcomes) < 2:
        # Need at least 2 outcomes for multiplicative devig overround calculation
        return None

    prices = [o.get("price", 0) for o in outcomes]
    if any(p == 0 for p in prices):
        return None

    raw_probs = [american_to_raw_prob(p) for p in prices]

    if vig_method == "pinnacle":
        from sportsbet.quant.vig import remove_vig_power
        fair_probs = remove_vig_power(raw_probs)
    else:
        try:
            fair_probs = remove_vig_multiplicative(raw_probs)
        except ValueError:
            # Both-positive-odds market (overround <= 1) — fall back to raw prob for first outcome
            fair_probs = raw_probs

    # Round to 10 decimal places to eliminate sub-ulp residual from Decimal division.
    # Preserves precision well beyond Kelly Criterion requirements (6 dp sufficient).
    from decimal import ROUND_HALF_EVEN
    fair_prob = fair_probs[0].quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_EVEN)

    return AgentOddsSnapshot(
        game_id=game_id,
        sportsbook=bookmaker.get("key", "unknown"),
        market_type="h2h",
        implied_probability=fair_prob,
        snapped_at=datetime.now(timezone.utc),
        american_odds=prices[0],  # raw int for CLV persistence (GAP-3)
    )


# ---------------------------------------------------------------------------
# Real arbitrage agent — closure factory (Phase 5)
# ---------------------------------------------------------------------------

def make_arbitrage_agent(
    settings_override: "Settings | None" = None,
) -> Callable[[GraphState], Coroutine[Any, Any, dict[str, Any]]]:
    """Return async arbitrage agent node with real Kelly/EV logic.

    The returned coroutine is compatible with LangGraph's async node interface:
    async def arbitrage_agent_real(state: GraphState) -> dict

    Pipeline per invocation:
    1. Read quant_result (QuantResult) and context_signals.odds_snapshot
       (AgentOddsSnapshot) from state.
    2. Guard: if quant_result is None or not QuantResult → return ev_signal=None
    3. Guard: if quant_result.true_probability is None → return ev_signal=None
    4. Guard: if odds_snapshot is None → return ev_signal=None (no odds to compare)
    5. Compute ev_pct = compute_ev_percentage(true_probability, implied_probability)
    6. If ev_pct == 0 (no positive edge) → return ev_signal=None
    7. Compute kelly_frac = fractional_kelly(p, b=Decimal("1.0"), fraction=cfg.max_kelly_fraction)
    8. Build trade_plan = build_trade_plan(ev_pct, kelly_frac, injury_flags, market_type)
    9. Construct EVSignal — Pydantic validates all constraints at construction time

    The sync arbitrage_agent stub is preserved below for backward-compat with
    Phase 2 tests using create_graph() without an arbitrage_node parameter.
    """
    from sportsbet.arbitrage.ev import build_trade_plan, compute_ev_percentage
    from sportsbet.arbitrage.kelly import fractional_kelly
    from sportsbet.config import settings as _settings

    cfg = settings_override if settings_override is not None else _settings

    async def arbitrage_agent_real(state: GraphState) -> dict[str, Any]:  # type: ignore[type-arg]
        session_id = state["session_id"]
        log.info("arbitrage_agent_invoked", session_id=session_id)

        quant_result = state.get("quant_result")  # type: ignore[attr-defined]
        context_signals = state.get("context_signals")  # type: ignore[attr-defined]

        # Guard: need real QuantResult with a probability
        if quant_result is None or not isinstance(quant_result, QuantResult):
            log.warning(
                "arbitrage_agent_no_quant_result",
                session_id=session_id,
                quant_result_type=type(quant_result).__name__,
            )
            return {"ev_signal": None, "error": "quant_result missing or invalid"}
        if quant_result.true_probability is None:
            log.info("arbitrage_agent_no_probability", session_id=session_id)
            return {"ev_signal": None}

        # Guard: need live odds snapshot
        if context_signals is None or context_signals.odds_snapshot is None:
            log.warning("arbitrage_agent_no_odds", session_id=session_id)
            return {"ev_signal": None}

        snapshot = context_signals.odds_snapshot
        true_prob: Decimal = quant_result.true_probability
        implied_prob: Decimal = snapshot.implied_probability
        injury_flags: dict[str, str] = context_signals.injury_flags

        ev_pct = compute_ev_percentage(true_prob, implied_prob)
        if ev_pct == Decimal("0"):
            log.info(
                "arbitrage_agent_no_edge",
                session_id=session_id,
                true_prob=str(true_prob),
                implied_prob=str(implied_prob),
            )
            return {"ev_signal": None}

        kelly_frac = fractional_kelly(
            p=true_prob,
            b=Decimal("1.0"),
            fraction=Decimal(str(cfg.max_kelly_fraction)),
        )

        trade_plan = build_trade_plan(ev_pct, kelly_frac, injury_flags, snapshot.market_type)

        signal = EVSignal(
            ev_percentage=ev_pct,
            true_probability=true_prob,
            implied_probability=implied_prob,
            kelly_fraction=kelly_frac,
            trade_plan=trade_plan,
            market_type=snapshot.market_type,
        )
        log.info(
            "arbitrage_agent_complete",
            session_id=session_id,
            ev_pct=str(ev_pct),
            kelly_frac=str(kelly_frac),
        )
        # pending_signals: used by correlation_guard_node and aggregator_node when
        # the full arbitrage pipeline is wired (Phase 5 Plan 03).
        return {"ev_signal": signal, "pending_signals": [signal]}

    return arbitrage_agent_real


# ---------------------------------------------------------------------------
# Backward-compat sync stub (Phase 2 — preserved for test isolation)
# ---------------------------------------------------------------------------

def quant_agent(state: GraphState) -> dict:  # type: ignore[type-arg]
    """Quant Agent stub — returns a hardcoded QuantResult fixture instance.

    Preserved for backward-compat: create_graph() without a quant_node parameter
    uses this stub so all existing Phase 2 tests continue to pass without a DB.

    Phase 3 replacement: pass make_quant_agent(pool) as quant_node to create_graph().
    data_source="fixture" signals this is stub output (never from real SQL).
    """
    log.info("stub_agent_called", agent="quant_agent", session_id=state["session_id"])
    return {
        "quant_result": QuantResult(
            true_probability=Decimal("0.62"),
            sample_size=142,
            data_source="fixture",
        )
    }


# ---------------------------------------------------------------------------
# Stub agents — Phase 4/5 replacements pending
# ---------------------------------------------------------------------------

def arbitrage_agent(state: GraphState) -> dict:  # type: ignore[type-arg]
    """Arbitrage Agent stub — returns a hardcoded EVSignal fixture instance.

    Stub: Phase 5 replaces this with real odds comparison logic.
    Fixture instance establishes interface contract for Phase 5 development.

    EVSignal fixture values:
    - ev_percentage=0.07  (7% edge over implied probability)
    - kelly_fraction=0.05 (5% fractional Kelly stake, well within 25% cap)
    - 2-item trade_plan (within CLAUDE.md 3-bullet limit)
    """
    log.info(
        "stub_agent_called", agent="arbitrage_agent", session_id=state["session_id"]
    )
    return {
        "ev_signal": EVSignal(
            ev_percentage=Decimal("0.07"),
            true_probability=Decimal("0.62"),
            implied_probability=Decimal("0.55"),
            kelly_fraction=Decimal("0.05"),
            trade_plan=["Fixture edge 1", "Fixture edge 2"],
            market_type="moneyline",
        )
    }


def context_agent(state: GraphState) -> dict:  # type: ignore[type-arg]
    """Context Agent stub — passthrough, no output model yet.

    Stub: Phase 4 replaces this with real context stream processing.
    Returns empty dict — no output model defined until Phase 4.
    """
    log.info(
        "stub_agent_called", agent="context_agent", session_id=state["session_id"]
    )
    return {}


# ---------------------------------------------------------------------------
# Real kinematic agent — closure factory (Phase 6)
# ---------------------------------------------------------------------------

def make_kinematic_agent(
    pool: asyncpg.Pool,
) -> Callable[[GraphState], Coroutine[Any, Any, dict[str, Any]]]:
    """Return an async kinematic agent node bound to the given asyncpg pool.

    The returned coroutine is compatible with LangGraph's async node interface:
    async def kinematic_agent(state: GraphState) -> dict

    Pipeline:
    1. check_ngs_availability(pool, season) — if False, return {"kinematic_result": None}
    2. Build KinematicParams from state (raises ValidationError if season < 2016)
    3. Call run_matchup_query(pool, params) to execute parameterized NGS SQL
    4. Return partial state dict with kinematic_result set to KinematicAnalysis

    Isolation: imports from sportsbet.kinematic inside the closure.
    No kinematic imports at module level — kinematic/ must not import from graph/.
    """
    from sportsbet.kinematic.availability import check_ngs_availability
    from sportsbet.kinematic.matchup import run_matchup_query
    from sportsbet.kinematic.models import KinematicParams

    async def kinematic_agent(state: GraphState) -> dict[str, Any]:  # type: ignore[type-arg]
        session_id = state["session_id"]
        season = state["season"]
        log.info("kinematic_agent_invoked", session_id=session_id, season=season)

        available = await check_ngs_availability(pool, season)
        if not available:
            log.warning("kinematic_ngs_unavailable", season=season, session_id=session_id)
            return {"kinematic_result": None}

        try:
            receiver_gsis_id: str = state.get("receiver_gsis_id", "")  # type: ignore[union-attr]
            params = KinematicParams(
                season=season,
                week=state["week"],
                receiver_gsis_id=receiver_gsis_id,
            )
            result = await run_matchup_query(pool, params)
        except Exception as exc:
            log.error(
                "kinematic_agent_error",
                session_id=session_id,
                error=str(exc),
                exc_info=True,
            )
            return {"kinematic_result": None, "error": str(exc)}

        log.info(
            "kinematic_agent_complete",
            session_id=session_id,
            geometric_mismatch_flag=result.geometric_mismatch_flag,
        )
        return {"kinematic_result": result}

    return kinematic_agent
