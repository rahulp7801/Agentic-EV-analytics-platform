"""Runtime agent factories and fail-closed legacy entry points for LangGraph.

Real quant, context, pricing and kinematic nodes are created with explicit
database/provider dependencies. Agents return partial state updates; LangGraph
merges them using the state reducers. Calling a legacy entry point directly
returns an unavailable error and never fixture analysis.
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
from sportsbet.ingestion.prop_odds import PlayerPropSnapshotCreate, write_player_prop_snapshot, parse_event_quotes
from sportsbet.ingestion.scraper import TEAM_ABBR_TO_ESPN_ID, InjuryWeatherScraper
from sportsbet.ingestion.sleeper import fetch_sleeper_team_injuries as _fetch_sleeper_injuries

if TYPE_CHECKING:
    pass

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# stat_type inference constants and helper (Quick Task 2 — QUANT-03)
# ---------------------------------------------------------------------------

_RUSHING_PROP_TYPES: frozenset[str] = frozenset({"rush_yds", "rush_tds", "carries"})
_RECEIVING_PROP_TYPES: frozenset[str] = frozenset({"rec_yds", "rec_tds", "receptions", "targets"})


def _infer_stat_type(prop_filters: "dict | None") -> "str | None":
    """Infer quant stat_type from prop_filters.prop_type.

    Returns None for non-prop routes (prop_filters is None or prop_type is absent).
    Returns "rushing" for NFL rushing prop types.
    Returns "receiving" for NFL receiving prop types.
    Returns "passing" as default for any other prop_type (pass_yds, pass_tds, NBA props).
    """
    if not prop_filters:
        return None
    pt = prop_filters.get("prop_type")
    if pt in _RUSHING_PROP_TYPES:
        return "rushing"
    if pt in _RECEIVING_PROP_TYPES:
        return "receiving"
    if pt is not None:
        return "passing"
    return None


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
                stat_type=state.get("stat_type") or "passing",  # QUANT-03: read from state, default "passing"
                filters={},
            )
            result = await run_quant_query(pool, params)
        except Exception as exc:
            log.error(
                "quant_agent_error",
                session_id=session_id,
                error_type=type(exc).__name__,
            )
            return {
                "quant_result": QuantResult(data_source="error"),
                "error": "quant_query_failed",
                "ev_signal": None, "pending_signals": [], "cleared_signals": [],
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

def _extract_situational_params(
    signals: "ContextSignals",
) -> "dict[str, Any] | None":
    """Extract situational parameters from ContextSignals for GraphState injection.

    Reads injury_flags from the constructed ContextSignals object and returns a
    structured dict when any players have Out or Inactive status. Returns None
    when no relevant injury context exists — avoids noise in non-injury scenarios.

    Called inside make_context_agent closure after ContextSignals is built.
    Pure function: no async, no DB access. (Phase 18 — SC-3)

    Args:
        signals: ContextSignals object produced by the context agent.

    Returns:
        {"teammate_out_signals": [player_name, ...]} when Out/Inactive players exist,
        None otherwise.
    """
    flags = signals.injury_flags
    if not flags:
        return None
    out_players = [
        player_name
        for player_name, status in flags.items()
        if status in ("Out", "Inactive")
    ]
    if not out_players:
        return None
    return {"teammate_out_signals": out_players}


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

    On any provider sub-error:
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
            odds_snapshot = _extract_odds_snapshot(raw_odds, game_id, vig_method=_vig_method, outcome_name=state.get("outcome_name"))
        except BudgetExhaustedError as exc:
            log.warning("context_agent_odds_budget_exhausted", session_id=session_id, error_type=type(exc).__name__)
        except Exception as exc:
            log.error("context_agent_odds_error", session_id=session_id, error_type=type(exc).__name__)

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
                    outcome_name=odds_snapshot.outcome_name,
                    game_start_time=odds_snapshot.game_start_time,
                )
                write_odds_snapshot(snap_create, engine=_sync_engine_cache[0])
                log.info("context_agent_odds_persisted", game_id=game_id)
            except Exception as exc:
                log.warning("context_agent_odds_persist_error", error_type=type(exc).__name__)

        # --- Step 1c: Fetch and persist player prop snapshots (PROP-01, sport-routed) ---
        # sport variable resolved at line 187; "nba" routes NBA prop markets, "nfl" routes NFL markets.
        # Sync engine reuses _sync_engine_cache initialized in Step 1b.
        # write_player_prop_snapshot uses sync SQLAlchemy (v1 accepted tradeoff — low concurrency).
        # _prop_snapshots initialized BEFORE try block so it is always in scope at Step 3
        # even if the try block raises (except blocks log and continue). (Phase 23 — PROP-06)
        _prop_snapshots: list = []
        try:
            try:
                async with OddsAPIPoller(api_key=api_key, daily_credit_cap=daily_credit_cap) as poller:
                    raw_props = await poller.fetch_player_props(sport)
                log.info("context_agent_props_source", source="odds_api")
            except Exception as odds_api_exc:
                log.warning(
                    "context_agent_sportsbook_props_unavailable",
                    error_type=type(odds_api_exc).__name__,
                )
                # Public projection lines without prices cannot become sportsbook
                # quotes. Keep the context request useful while props stay absent.
                raw_props = []
            matches=[event for event in raw_props if event.get('id')==game_id]
            if len(matches)>1:
                raise ValueError('Duplicate prop event identity')
            if matches:
                _prop_snapshots=parse_event_quotes(matches[0],sport)
            if _prop_snapshots and not _sync_engine_cache:
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
            for snap in _prop_snapshots:
                try:
                    write_player_prop_snapshot(snap,engine=_sync_engine_cache[0])
                except Exception as snap_exc:
                    log.warning('prop_snapshot_write_error',error_type=type(snap_exc).__name__)
            log.info("context_agent_props_persisted",game_id=game_id,count=len(_prop_snapshots))
        except BudgetExhaustedError as exc:
            log.warning("context_agent_prop_budget_exhausted", error_type=type(exc).__name__)
        except Exception as exc:
            log.warning("context_agent_prop_fetch_error", error_type=type(exc).__name__)

        # --- Step 2: Fetch injury reports ---
        injury_flags: dict[str, str] = {}
        # injury_details: richer per-player context (name, team, position, status)
        # Used to build teammate_out_contexts for PropQueryBuilder's player_stats absence filter.
        injury_details: list[dict[str, str]] = []
        try:
            if sport == "nba":
                # Sleeper API covers NBA injuries — fetch both teams in parallel (each call
                # downloads the full players list, so parallel cuts latency in half).
                import asyncio as _asyncio
                home_injs, away_injs = await _asyncio.gather(
                    _fetch_sleeper_injuries("nba", home_team),
                    _fetch_sleeper_injuries("nba", away_team),
                    return_exceptions=True,
                )
                for team_abbr, sleeper_injuries in (
                    (home_team, home_injs if not isinstance(home_injs, Exception) else []),
                    (away_team, away_injs if not isinstance(away_injs, Exception) else []),
                ):
                    for inj in sleeper_injuries:
                        status = inj.get("status", "Unknown")
                        name = inj.get("player_name", "Unknown")
                        position = inj.get("position", "Unknown")
                        if status in ("Out", "Questionable"):
                            injury_flags[name] = status
                            injury_details.append({
                                "name": name,
                                "team": team_abbr,
                                "position": position,
                                "status": status,
                            })
            else:
                # NFL: ESPN Core API (primary) + Sleeper supplement
                async with httpx.AsyncClient(timeout=10.0) as client:
                    scraper = InjuryWeatherScraper(client)
                    for team_abbr in (home_team, away_team):
                        team_id = TEAM_ABBR_TO_ESPN_ID.get(team_abbr)
                        if team_id is None:
                            log.warning("context_agent_unknown_team", team_abbr=team_abbr)
                            continue
                        injuries = await scraper.fetch_team_injuries(team_id)
                        await scraper.write_injury_reports(pool, injuries, team_abbr, game_id)
                        for inj in injuries:
                            status = inj.get("status", "Unknown")
                            name = inj.get("player_name", "Unknown")
                            position = inj.get("position", "Unknown")
                            if status in ("Out", "Questionable"):
                                injury_flags[name] = status
                                injury_details.append({
                                    "name": name,
                                    "team": team_abbr,
                                    "position": position,
                                    "status": status,
                                })
                # Supplement NFL with Sleeper (catches IR/PUP players ESPN may miss)
                try:
                    for team_abbr in (home_team, away_team):
                        sleeper_injs = await _fetch_sleeper_injuries("nfl", team_abbr)
                        for inj in sleeper_injs:
                            name = inj.get("player_name", "Unknown")
                            status = inj.get("status", "Unknown")
                            # Only add players not already captured by ESPN
                            if name not in injury_flags and status in ("Out", "Questionable"):
                                injury_flags[name] = status
                                injury_details.append({
                                    "name": name,
                                    "team": inj.get("team", team_abbr),
                                    "position": inj.get("position", "Unknown"),
                                    "status": status,
                                })
                except Exception as sleeper_exc:
                    log.warning("context_agent_sleeper_supplement_failed", error_type=type(sleeper_exc).__name__)
        except Exception as exc:
            log.error("context_agent_scraper_error", session_id=session_id, error_type=type(exc).__name__)

        # --- Step 3: Build ContextSignals and return ---
        signals = ContextSignals(
            game_id=game_id,
            injury_flags=injury_flags,
            weather_json=None,  # NFLWeather scraping deferred to v2
            odds_snapshot=odds_snapshot,
            signals_captured_at=datetime.now(timezone.utc),
        )
        # Extract situational params from injury signals (Phase 18 — SC-3).
        # Non-None when Out/Inactive players exist; None otherwise (no noise).
        # Build richer situational_params from injury_details (has team+position context).
        # teammate_out_contexts enables PropQueryBuilder's player_stats absence filter,
        # which works for historical data (unlike the injury_reports INTERVAL approach).
        out_details = [d for d in injury_details if d["status"] == "Out"]
        situational_params: dict | None = None
        if out_details:
            situational_params = {
                "teammate_out_signals": [d["name"] for d in out_details],
                "teammate_out_contexts": [
                    {"name": d["name"], "team": d["team"], "position": d["position"]}
                    for d in out_details
                ],
            }
        log.info(
            "context_agent_complete",
            session_id=session_id,
            injury_count=len(injury_flags),
            has_odds=odds_snapshot is not None,
        )
        return {
            "context_signals": signals,
            "situational_params": situational_params,
            "player_prop_snapshots": _prop_snapshots if _prop_snapshots else None,
            "stat_type": _infer_stat_type(state.get("prop_filters")),  # QUANT-03: always set
        }

    return context_agent


def _extract_odds_snapshot(
    raw_odds: list[dict], game_id: str, vig_method: str = "multiplicative",
    outcome_name: str | None = None,
) -> "AgentOddsSnapshot | None":
    """Match one provider event and named h2h outcome; preserve observed quote time.

    The default selection is the matched event's home team. Internal game IDs
    must be mapped to provider IDs before calling; never attach unrelated odds.
    """
    from datetime import datetime
    from decimal import ROUND_HALF_EVEN
    from sportsbet.graph.models import AgentOddsSnapshot
    from sportsbet.quant.vig import american_to_raw_prob, remove_vig_multiplicative, remove_vig_power

    events = [e for e in raw_odds if e.get('id') == game_id]
    if len(events) != 1:
        return None
    event = events[0]
    selection = outcome_name or event.get('home_team')
    if not selection or not event.get('commence_time'):
        return None
    try:
        start = datetime.fromisoformat(event['commence_time'].replace('Z','+00:00'))
        if start.tzinfo is None:
            return None
    except (ValueError, TypeError, AttributeError):
        return None
    for book in event.get('bookmakers', []):
        for market in book.get('markets', []):
            if market.get('key') != 'h2h' or not book.get('key'):
                continue
            outcomes = market.get('outcomes', [])
            names = [o.get('name') for o in outcomes]
            if len(outcomes) < 2 or len(set(names)) != len(names) or selection not in names or not all(names):
                continue
            prices = [o.get('price') for o in outcomes]
            if any(type(price) is not int or abs(price) < 100 for price in prices):
                continue
            updated = market.get('last_update') or book.get('last_update')
            try:
                observed = datetime.fromisoformat(updated.replace('Z','+00:00'))
                if observed.tzinfo is None:
                    continue
            except (ValueError, TypeError, AttributeError):
                continue
            raw_probs = [american_to_raw_prob(price) for price in prices]
            try:
                fair_probs = remove_vig_power(raw_probs) if vig_method == 'pinnacle' else remove_vig_multiplicative(raw_probs)
            except ValueError:
                fair_probs = raw_probs
            index = names.index(selection)
            return AgentOddsSnapshot(game_id=game_id, sportsbook=book['key'], market_type='h2h',
                implied_probability=fair_probs[index].quantize(Decimal('0.0000000001'), rounding=ROUND_HALF_EVEN),
                snapped_at=observed, american_odds=prices[index], outcome_name=selection, game_start_time=start)
    return None


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

    The fail-closed legacy entry point below is retained for import compatibility.
    """
    from sportsbet.arbitrage.ev import build_trade_plan, compute_ev_percentage, compute_expected_return, quote_terms
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

        if quant_result.prediction_target != "market_outcome":
            return {"ev_signal": None, "pending_signals": [], "gate_reason": "incompatible_prediction_target"}
        true_prob: Decimal = quant_result.true_probability
        injury_flags: dict[str, str] = (context_signals.injury_flags if context_signals else {})

        # Prefer player-specific prop snapshot over h2h when available.
        # prop_type in state is a short key ("points") — map to Odds API market key ("player_points").
        player_name: str = state.get("player_name", "")  # type: ignore[assignment]
        raw_prop_type: str = state.get("prop_type", "") or ""  # type: ignore[assignment]
        prop_market_key = f"player_{raw_prop_type}" if raw_prop_type else ""
        player_prop_snapshots: list = state.get("player_prop_snapshots") or []  # type: ignore[assignment]

        prop_snap = None
        if player_name and prop_market_key and player_prop_snapshots:
            prop_snap = next(
                (
                    s for s in player_prop_snapshots
                    if player_name.strip().casefold() == s.player_name.strip().casefold()
                    and s.prop_type == prop_market_key
                    and getattr(s, "side", None) == "Over"
                    and state.get("prop_line") is not None and s.line == Decimal(str(state["prop_line"]))
                ),
                None,
            )

        if prop_snap is not None:
            implied_prob: Decimal = prop_snap.implied_probability
            american_odds = prop_snap.price
            active_market_type = prop_snap.prop_type
            log.info(
                "prop_arbitrage_agent.enter",
                sport=state.get("sport"),
                player=player_name,
                prop_type=prop_market_key,
                source=getattr(prop_snap, "sportsbook", "unknown"),
            )
        elif raw_prop_type:
            return {"ev_signal": None, "pending_signals": [], "gate_reason": "missing_matching_prop_quote"}
        else:
            # Only a market-outcome model may consume game odds.
            if context_signals is None or context_signals.odds_snapshot is None:
                log.warning("arbitrage_agent_no_odds", session_id=session_id)
                return {"ev_signal": None}
            snapshot = context_signals.odds_snapshot
            implied_prob = snapshot.implied_probability
            american_odds = snapshot.american_odds
            active_market_type = snapshot.market_type
            log.info("prop_arbitrage_agent.enter", sport=state.get("sport"))

        try:
            implied_prob, net_payout = quote_terms(american_odds, implied_prob)
        except ValueError:
            return {"ev_signal": None}
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
            b=net_payout,
            fraction=Decimal(str(cfg.max_kelly_fraction)),
        )

        if kelly_frac <= Decimal("0"):
            return {"ev_signal": None}
        trade_plan = build_trade_plan(ev_pct, kelly_frac, injury_flags, active_market_type)

        signal = EVSignal(
            ev_percentage=ev_pct,
            expected_return=compute_expected_return(true_prob, net_payout),
            game_id=state.get("game_id"),
            player_name=state.get("player_name"),
            true_probability=true_prob,
            implied_probability=implied_prob,
            kelly_fraction=kelly_frac,
            trade_plan=trade_plan,
            market_type=active_market_type,
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
# Fail-closed legacy direct entry points
# ---------------------------------------------------------------------------

def quant_agent(state: GraphState) -> dict:  # type: ignore[type-arg]
    """Legacy direct entry point that fails closed without a configured database."""
    return {"error": "quant_agent_not_configured", "quant_result": None,
            "ev_signal": None, "pending_signals": [], "cleared_signals": []}


# ---------------------------------------------------------------------------
# Direct calls also fail closed; runtime callers use the real factories above.
# ---------------------------------------------------------------------------

def arbitrage_agent(state: GraphState) -> dict:  # type: ignore[type-arg]
    """Legacy direct entry point that fails closed without a real analysis input."""
    return {"error": "arbitrage_agent_not_configured", "ev_signal": None,
            "pending_signals": [], "cleared_signals": []}


def context_agent(state: GraphState) -> dict:  # type: ignore[type-arg]
    """Legacy direct entry point that fails closed without configured providers."""
    return {"error": "context_agent_not_configured", "context_signals": None,
            "ev_signal": None, "pending_signals": [], "cleared_signals": []}


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

        try:
            available = await check_ngs_availability(pool, season)
            if not available:
                log.warning("kinematic_ngs_unavailable", season=season, session_id=session_id)
                return {"kinematic_result": None}

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
                error_type=type(exc).__name__,
            )
            return {"kinematic_result": None, "error": "kinematic_query_failed",
                "ev_signal": None, "pending_signals": [], "cleared_signals": []}

        log.info(
            "kinematic_agent_complete",
            session_id=session_id,
            geometric_mismatch_flag=result.geometric_mismatch_flag,
        )
        return {"kinematic_result": result}

    return kinematic_agent
