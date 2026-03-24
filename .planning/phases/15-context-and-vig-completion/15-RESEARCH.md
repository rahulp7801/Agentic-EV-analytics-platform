# Phase 15: Context and Vig Completion - Research

**Researched:** 2026-03-23
**Domain:** OddsAPIPoller NBA extension, make_context_agent NBA routing, config-selectable devig dispatch
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| QUANT-02 | System converts raw sportsbook odds to implied probabilities with configurable vig removal method (multiplicative or Pinnacle sharp) | Both `remove_vig_multiplicative` and `remove_vig_power` are fully implemented in `src/sportsbet/quant/vig.py` and unit-tested. The gap is that `_extract_odds_snapshot` in `agents.py` hardcodes `remove_vig_multiplicative` — no config flag exists to switch to `remove_vig_power` at runtime. |
| CTXT-01 | System ingests live odds asynchronously from The Odds API with a budget manager that tracks per-request cost and enforces a configurable daily API spend cap | `OddsAPIPoller` is complete with `fetch_nfl_odds()`, `fetch_player_props()`, and budget management. The gap is `fetch_nba_odds()` does not exist — NBA game-level h2h/spreads/totals cannot be fetched. Adding it mirrors the existing `fetch_nfl_odds` pattern exactly. |
| CTXT-04 | Context Agent updates a global game state JSON on binary state changes and propagates the updated state through GraphState | `make_context_agent` is currently NFL-scoped (`fetch_nfl_odds()` in Step 1). When routed with an NBA game context, no game-level odds are fetched and `ContextSignals.odds_snapshot` is always None for NBA games. The fix is to detect sport from state and route to `fetch_nba_odds()` instead. |
</phase_requirements>

---

## Summary

Phase 15 closes two remaining v1 gaps, each requiring a targeted additive change.

**Gap 1 (CTXT-01 / CTXT-04 / Flow 2 — NBA game context broken):** `OddsAPIPoller` has no `fetch_nba_odds()` method. `make_context_agent` always calls `fetch_nfl_odds()` regardless of which sport the game belongs to. The result: any NBA `context_update` request produces a `ContextSignals` with `odds_snapshot=None`. The fix is two-step: (a) add `fetch_nba_odds()` to `OddsAPIPoller` mirroring `fetch_nfl_odds()` but using `NBA_SPORT_KEY`, and (b) make `make_context_agent` select between the two methods based on a sport signal from state.

**Gap 2 (QUANT-02 partial — Pinnacle method orphaned):** `remove_vig_power` is complete and tested in `sportsbet.quant.vig` but `_extract_odds_snapshot` hardcodes `remove_vig_multiplicative`. QUANT-02 requires the method to be configurable. The fix is to add a `vig_method: Literal["multiplicative", "pinnacle"]` field to `Settings` (defaulting to `"multiplicative"`) and thread it through `make_context_agent` → `_extract_odds_snapshot` so the correct function is called at runtime.

**Primary recommendation:** One plan, two targeted changes. No new dependencies, no migrations, no new agent logic beyond the two extension points. All existing NFL context agent tests must remain green — changes are strictly additive.

---

## Standard Stack

### Core (all already installed — no new dependencies)

| Library | Version | Purpose | Status |
|---------|---------|---------|--------|
| `httpx` | >=0.27 | Async HTTP client used by `OddsAPIPoller` | Already in use |
| `pydantic` | >=2.7,<3.0 | `Settings` field addition for `vig_method` | Already in use |
| `pydantic_settings` | >=2.3 | `BaseSettings` subclass for `Settings` | Already in use |
| `structlog` | >=24.1 | Structured logging in agent closures | Already in use |
| `pytest-asyncio` | installed | `asyncio_mode = "auto"` for async tests | Already in use |

**No new packages required for this phase.**

---

## Architecture Patterns

### Pattern 1: Additive method on OddsAPIPoller (fetch_nba_odds)

**What:** `fetch_nba_odds` is a direct copy of `fetch_nfl_odds` with `NFL_SPORT_KEY` replaced by `NBA_SPORT_KEY`. Both constants are already defined at module level in `odds_poller.py`.

**When to use:** Any time game-level NBA h2h/spreads/totals are needed from The Odds API.

**Key design constraints from existing code:**
- Budget guard fires before HTTP request (`_credits_remaining < 1` check) — must be identical to `fetch_nfl_odds` guard
- Response header `x-requests-remaining` updates `_credits_remaining` — identical tracking
- `raise_for_status()` called before `.json()` — identical error propagation
- Returns `list[dict]` — identical return type

```python
# Source: src/sportsbet/ingestion/odds_poller.py — mirrors fetch_nfl_odds exactly
async def fetch_nba_odds(
    self,
    regions: str = "us",
    markets: str = "h2h,spreads,totals",
) -> list[dict]:
    """Fetch current NBA odds from The Odds API.

    Raises:
        BudgetExhaustedError: If _credits_remaining is not None and < 1.
        httpx.HTTPStatusError: If the API returns a non-2xx status.

    Returns:
        Parsed JSON list of event dicts from the Odds API.
    """
    if self._credits_remaining is not None and self._credits_remaining < 1:
        raise BudgetExhaustedError(
            f"Odds API daily credit cap reached. "
            f"credits_remaining={self._credits_remaining}, "
            f"daily_credit_cap={self._daily_credit_cap}"
        )

    assert self._client is not None, "fetch_nba_odds called outside async context manager"

    response = await self._client.get(
        f"/v4/sports/{NBA_SPORT_KEY}/odds",
        params={
            "apiKey": self._api_key,
            "regions": regions,
            "markets": markets,
        },
    )
    response.raise_for_status()

    self._credits_remaining = int(
        response.headers.get("x-requests-remaining", "0")
    )

    log.info(
        "odds_api_fetched",
        credits_remaining=self._credits_remaining,
        sport_key=NBA_SPORT_KEY,
    )

    return response.json()
```

### Pattern 2: Sport detection in make_context_agent

**What:** `make_context_agent` currently hardcodes `poller.fetch_nfl_odds()`. To support NBA, it must detect the sport from state before choosing which method to call. The sport signal can come from `state["request_type"]` (already in GraphState — `"context_update"` is used for both sports) or from an explicit sport field.

**Sport detection options:**

| Option | Mechanism | Tradeoff |
|--------|-----------|----------|
| A — detect from `request_type` | `"nba_context_update"` vs `"context_update"` | Requires new router entry, breaks existing tests |
| B — detect from `state.get("sport", "nfl")` | New optional GraphState field | Minimal change; non-NBA callers unaffected |
| C — detect from game_id prefix | Parse `"2024_01_BOS_MIA"` for team codes | Fragile; game_id format is not sport-tagged |

**Recommendation: Option B.** Add an optional `sport: str` field to `GraphState` (defaulting to `"nfl"` via `state.get("sport", "nfl")`). Existing tests that omit the field continue to work. The context agent reads `state.get("sport", "nfl")` to decide between `fetch_nfl_odds()` and `fetch_nba_odds()`.

```python
# Inside make_context_agent closure, Step 1:
sport = state.get("sport", "nfl")  # type: ignore[attr-defined]
if sport == "nba":
    raw_odds = await poller.fetch_nba_odds()
else:
    raw_odds = await poller.fetch_nfl_odds()
```

**Critical:** The `sport` field addition to `GraphState` must be `Optional[str]` or use `state.get("sport", "nfl")` access only — existing test fixtures do NOT set it. TypedDict fields without defaults break existing state dicts at runtime if LangGraph validates completeness.

**Safe pattern (matching Phase 14 prop_filters decision):**
```python
# state.py — add after prop_filters field
sport: str | None  # type: ignore[misc]  # "nfl" | "nba" — defaults to "nfl" when None
```
Agents use: `sport = state.get("sport") or "nfl"` — handles both missing and None.

### Pattern 3: Config-selectable vig method via Settings

**What:** Add `vig_method: Literal["multiplicative", "pinnacle"]` to `Settings` in `config.py`. Thread it through `make_context_agent` into `_extract_odds_snapshot` as a parameter.

**Pydantic v2 Literal field in BaseSettings:**
```python
# Source: Pydantic v2 BaseSettings — Literal fields with defaults are supported
from typing import Literal

class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8")

    # existing fields ...
    vig_method: Literal["multiplicative", "pinnacle"] = "multiplicative"
```

**Environment variable support:** Pydantic BaseSettings maps `VIG_METHOD=pinnacle` (uppercase env var) to `settings.vig_method` automatically.

**Threading vig_method through the call chain:**

Current call chain:
```
make_context_agent(pool, api_key, daily_credit_cap)
  └── _extract_odds_snapshot(raw_odds, game_id)   # hardcodes remove_vig_multiplicative
```

Phase 15 call chain:
```
make_context_agent(pool, api_key, daily_credit_cap, vig_method="multiplicative")
  └── _extract_odds_snapshot(raw_odds, game_id, vig_method="multiplicative")
       └── if vig_method == "pinnacle": remove_vig_power(raw_probs)
           else: remove_vig_multiplicative(raw_probs)
```

**Signature changes:**
```python
# _extract_odds_snapshot — add vig_method parameter
def _extract_odds_snapshot(
    raw_odds: list[dict],
    game_id: str,
    vig_method: str = "multiplicative",
) -> "AgentOddsSnapshot | None":
    ...
    try:
        if vig_method == "pinnacle":
            from sportsbet.quant.vig import remove_vig_power
            fair_probs = remove_vig_power(raw_probs)
        else:
            fair_probs = remove_vig_multiplicative(raw_probs)
    except ValueError:
        fair_probs = raw_probs
```

**make_context_agent — read vig_method from settings at construction time:**
```python
def make_context_agent(
    pool: asyncpg.Pool,
    api_key: str,
    daily_credit_cap: int,
    vig_method: str | None = None,  # None = read from settings
) -> ...:
    from sportsbet.config import settings as _settings
    _vig_method = vig_method if vig_method is not None else _settings.vig_method

    ...
    odds_snapshot = _extract_odds_snapshot(raw_odds, game_id, vig_method=_vig_method)
```

**Alternative (simpler):** Do not change `make_context_agent` signature. Instead, import `settings` inside `_extract_odds_snapshot` and read `settings.vig_method` directly. This avoids any parameter threading. Trade-off: `_extract_odds_snapshot` is harder to test in isolation because it reads global settings.

**Recommendation: Thread the parameter.** Keep `_extract_odds_snapshot` a pure function that takes `vig_method` as an argument — consistent with the existing Pydantic/pure-function philosophy of the codebase. The `make_context_agent` factory reads from settings at construction time and passes the resolved value.

### Pattern 4: Mock patchability — test considerations

**What:** `_extract_odds_snapshot` is a module-level function in `agents.py`, not inside a closure, so it is patchable via `patch("sportsbet.graph.agents._extract_odds_snapshot")`. This pattern is already used in `test_context.py` line 479.

For testing vig_method dispatch:
```python
# Two-method dispatch test — does NOT require live HTTP
raw_probs = [american_to_raw_prob(-110), american_to_raw_prob(-110)]
mult_result = remove_vig_multiplicative(raw_probs)
power_result = remove_vig_power(raw_probs)
# symmetric market: mult gives [0.5, 0.5], power is very close but non-identical
```

For an asymmetric market (-200/+170), the outputs diverge more clearly:
```python
fav = american_to_raw_prob(-200)  # ~0.6667
dog = american_to_raw_prob(170)   # ~0.3704
mult_result = remove_vig_multiplicative([fav, dog])  # [~0.6429, ~0.3571]
power_result = remove_vig_power([fav, dog])           # [~0.6499, ~0.3501]  (favorite gets more)
```

### Anti-Patterns to Avoid

- **Do NOT add `vig_method` to `GraphState`:** This is a configuration concern, not a per-request state concern. Read from `Settings` at agent construction time.
- **Do NOT change `_extract_odds_snapshot` to import settings internally:** Keeps it testable as a pure function.
- **Do NOT add a new `request_type` for NBA context_update:** The existing `"context_update"` type is sport-agnostic — use the `sport` state field instead.
- **Do NOT break the existing `fetch_nfl_odds` mock in test_context.py:** `test_context_agent_updates_graphstate` and `test_downstream_reads_state` both patch `OddsAPIPoller.fetch_nfl_odds`. After Phase 15, the closure calls either `fetch_nfl_odds` OR `fetch_nba_odds` depending on state. Tests that do not set `state["sport"]` default to NFL and continue using `fetch_nfl_odds` — no change needed.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| NBA odds endpoint URL | Custom URL string | `NBA_SPORT_KEY = "basketball_nba"` (already defined in odds_poller.py) | Constant already exists; reuse it |
| Power devig | New implementation | `remove_vig_power` from `sportsbet.quant.vig` | Already implemented, tested, and Decimal-safe |
| Multiplicative devig | New implementation | `remove_vig_multiplicative` from `sportsbet.quant.vig` | Same |
| Config loading | Manual env var read | Pydantic `BaseSettings` `vig_method` field | Handles `.env` file, env vars, and type validation automatically |
| Budget guard copy-paste | New budget logic | Identical guard pattern from `fetch_nfl_odds` | Both checks use same `_credits_remaining < 1` condition |

---

## Common Pitfalls

### Pitfall 1: Existing context tests patch fetch_nfl_odds by name — NBA routing must be conditional

**What goes wrong:** If `make_context_agent` always calls `fetch_nba_odds()` (or always branches on sport), existing tests that patch `OddsAPIPoller.fetch_nfl_odds` will pass through un-patched `fetch_nba_odds` and make real HTTP calls (or fail with `AttributeError: fetch_nba_odds`).

**Why it happens:** The tests in `test_context.py` (lines 282-315 and 344-373) patch `fetch_nfl_odds` on the `OddsAPIPoller` class. They do not set `state["sport"]` — they rely on the default NFL behavior.

**How to avoid:** Gate the NBA branch on `state.get("sport") == "nba"` (not `!= "nfl"`). When sport is unset or None or "nfl", always call `fetch_nfl_odds`. Tests that do not set sport continue to exercise the NFL path. Add a dedicated NBA test that explicitly sets `state["sport"] = "nba"` and patches `fetch_nba_odds`.

**Warning signs:** `test_context_agent_updates_graphstate` or `test_downstream_reads_state` failing after Phase 15 changes.

### Pitfall 2: vig_method "pinnacle" on symmetric markets produces nearly identical output to "multiplicative"

**What goes wrong:** The success criterion requires "a test confirming the outputs differ." On a symmetric -110/-110 market, `remove_vig_power` returns values very close to `[0.5, 0.5]` (because the overround is only 1.047), making the difference sub-millionth.

**Why it happens:** `remove_vig_power` converges to the same result as multiplicative when the market is symmetric and the overround is small.

**How to avoid:** Use an asymmetric market for the difference test. `-200/+170` has more overround and greater favorite-longshot bias. The `test_vig.py::test_power_favors_favorite` test already documents this: `power[0] > mult[0]` on `-200/+170`. Reuse this fixture in the Phase 15 config test.

**Warning signs:** Test asserting `power_result != mult_result` failing on symmetric markets.

### Pitfall 3: `both-positive-odds` fallback path with Pinnacle method

**What goes wrong:** `_extract_odds_snapshot` currently catches `ValueError` from `remove_vig_multiplicative` for both-positive-odds markets and falls back to `raw_probs`. `remove_vig_power` does NOT raise `ValueError` — it converges correctly even for underdog-heavy markets. The fallback logic must be preserved for the multiplicative path only.

**Why it happens:** The `ValueError` guard in `_extract_odds_snapshot` (line ~350 of `agents.py`) catches `remove_vig_multiplicative`'s overround <= 1 guard. `remove_vig_power` has no such guard — its binary search finds k=1 when overround approaches 1.

**How to avoid:** Keep the `try/except ValueError` only around `remove_vig_multiplicative`. For `remove_vig_power`, no try/except needed unless you want to guard against edge cases (e.g., all-zero raw_probs, which would never come from a real Odds API response).

```python
if vig_method == "pinnacle":
    from sportsbet.quant.vig import remove_vig_power
    fair_probs = remove_vig_power(raw_probs)  # no ValueError path for power
else:
    try:
        fair_probs = remove_vig_multiplicative(raw_probs)
    except ValueError:
        fair_probs = raw_probs
```

### Pitfall 4: Module-level import for mock patchability — `fetch_nba_odds` must be on the class, not a module function

**What goes wrong:** `fetch_nba_odds` is a method on `OddsAPIPoller`. Tests patch it via `patch.object(OddsAPIPoller, "fetch_nba_odds", ...)`. This is the same pattern used for `fetch_nfl_odds` and `fetch_player_props` in the existing test suite.

**How to avoid:** Follow the exact same mock pattern as `test_context_agent_updates_graphstate` (lines 282-315) but replace `fetch_nfl_odds` with `fetch_nba_odds` and set `state["sport"] = "nba"`.

### Pitfall 5: GraphState `sport` field — Optional pattern is mandatory

**What goes wrong:** If `sport: str` is declared as a required TypedDict field (without Optional/None), every existing test fixture that builds a GraphState dict will be missing it. This causes runtime failures or mypy errors.

**Why it happens:** Same issue documented in Phase 14 for `prop_filters` — TypedDict fields without defaults require presence in every dict used as that type.

**How to avoid:** Declare as `sport: str | None` and access via `state.get("sport") or "nfl"` everywhere. This is the locked Phase 14 pattern (`prop_filters: dict[str, Any] | None`). Follow it exactly.

---

## Code Examples

Verified patterns from the existing codebase:

### fetch_nba_odds — full implementation

```python
# Source: src/sportsbet/ingestion/odds_poller.py
# Mirrors fetch_nfl_odds exactly; only NBA_SPORT_KEY differs
async def fetch_nba_odds(
    self,
    regions: str = "us",
    markets: str = "h2h,spreads,totals",
) -> list[dict]:
    if self._credits_remaining is not None and self._credits_remaining < 1:
        raise BudgetExhaustedError(
            f"Odds API daily credit cap reached. "
            f"credits_remaining={self._credits_remaining}, "
            f"daily_credit_cap={self._daily_credit_cap}"
        )

    assert self._client is not None, "fetch_nba_odds called outside async context manager"

    response = await self._client.get(
        f"/v4/sports/{NBA_SPORT_KEY}/odds",
        params={"apiKey": self._api_key, "regions": regions, "markets": markets},
    )
    response.raise_for_status()
    self._credits_remaining = int(response.headers.get("x-requests-remaining", "0"))
    log.info("odds_api_fetched", credits_remaining=self._credits_remaining, sport_key=NBA_SPORT_KEY)
    return response.json()
```

### Settings.vig_method field addition

```python
# Source: src/sportsbet/config.py
from typing import Literal
from pydantic import ConfigDict
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+psycopg://localhost/sportsbet"
    database_url_async: str = "postgresql+asyncpg://localhost/sportsbet"
    postgres_db: str = "sportsbet"
    log_level: str = "INFO"
    bankroll_usd: float = 10000.0
    max_kelly_fraction: float = 0.25
    vig_method: Literal["multiplicative", "pinnacle"] = "multiplicative"  # ADD
```

### _extract_odds_snapshot — vig_method dispatch

```python
# Source: src/sportsbet/graph/agents.py — _extract_odds_snapshot
def _extract_odds_snapshot(
    raw_odds: list[dict],
    game_id: str,
    vig_method: str = "multiplicative",  # ADD parameter
) -> "AgentOddsSnapshot | None":
    from sportsbet.graph.models import AgentOddsSnapshot
    from sportsbet.quant.vig import american_to_raw_prob, remove_vig_multiplicative

    # ... (existing None guards unchanged) ...

    raw_probs = [american_to_raw_prob(p) for p in prices]

    if vig_method == "pinnacle":
        from sportsbet.quant.vig import remove_vig_power
        fair_probs = remove_vig_power(raw_probs)
    else:
        try:
            fair_probs = remove_vig_multiplicative(raw_probs)
        except ValueError:
            fair_probs = raw_probs

    # ... (quantize and construct AgentOddsSnapshot — unchanged) ...
```

### make_context_agent — vig_method and sport threading

```python
# Source: src/sportsbet/graph/agents.py — make_context_agent
def make_context_agent(
    pool: asyncpg.Pool,
    api_key: str,
    daily_credit_cap: int,
    vig_method: str | None = None,  # ADD
) -> ...:
    from sportsbet.config import settings as _settings
    _vig_method = vig_method if vig_method is not None else _settings.vig_method

    async def context_agent(state: GraphState) -> dict[str, Any]:
        # ... existing Step 1 header ...
        sport = state.get("sport") or "nfl"  # type: ignore[attr-defined]

        odds_snapshot = None
        try:
            async with OddsAPIPoller(api_key=api_key, daily_credit_cap=daily_credit_cap) as poller:
                if sport == "nba":
                    raw_odds = await poller.fetch_nba_odds()
                else:
                    raw_odds = await poller.fetch_nfl_odds()
            odds_snapshot = _extract_odds_snapshot(raw_odds, game_id, vig_method=_vig_method)
        except BudgetExhaustedError as exc:
            ...
```

### GraphState sport field addition (state.py)

```python
# Source: src/sportsbet/graph/state.py — add after prop_filters field
sport: str | None  # type: ignore[misc]  # "nfl" | "nba" — None defaults to "nfl" in context agent
```

### Test: NBA context_update produces non-None odds_snapshot

```python
# New test in tests/test_context.py or tests/test_vig_completion.py
@pytest.mark.asyncio
async def test_nba_context_agent_fetches_nba_odds() -> None:
    """make_context_agent with state['sport']='nba' calls fetch_nba_odds, not fetch_nfl_odds."""
    mock_pool = MagicMock()
    with (
        patch.object(OddsAPIPoller, "fetch_nba_odds", new_callable=AsyncMock, return_value=NBA_ODDS_FIXTURE),
        patch.object(OddsAPIPoller, "fetch_player_props", new_callable=AsyncMock, return_value=[]),
        patch("sportsbet.graph.agents.write_player_prop_snapshot"),
        patch("sportsbet.graph.agents.write_odds_snapshot"),
        patch("sportsbet.ingestion.scraper.InjuryWeatherScraper.fetch_team_injuries",
              new_callable=AsyncMock, return_value=[]),
        patch("sportsbet.ingestion.scraper.InjuryWeatherScraper.write_injury_reports",
              new_callable=AsyncMock, return_value=0),
    ):
        agent = make_context_agent(mock_pool, api_key="test_key", daily_credit_cap=500)
        state = _make_full_state()
        state["sport"] = "nba"  # force NBA path
        result = await agent(state)

    assert result["context_signals"].odds_snapshot is not None
```

### Test: vig_method="pinnacle" produces different result than "multiplicative" on asymmetric market

```python
def test_pinnacle_devig_differs_from_multiplicative() -> None:
    """Setting vig_method='pinnacle' in config causes _extract_odds_snapshot to use remove_vig_power.

    Uses asymmetric -200/+170 market where power method visibly diverges from multiplicative.
    """
    from sportsbet.graph.agents import _extract_odds_snapshot

    ASYMMETRIC_ODDS = [{
        "id": "game_001",
        "bookmakers": [{
            "key": "draftkings",
            "markets": [{
                "key": "h2h",
                "outcomes": [
                    {"name": "Team A", "price": -200},
                    {"name": "Team B", "price": 170},
                ],
            }],
        }],
    }]

    snap_mult = _extract_odds_snapshot(ASYMMETRIC_ODDS, "game_001", vig_method="multiplicative")
    snap_power = _extract_odds_snapshot(ASYMMETRIC_ODDS, "game_001", vig_method="pinnacle")

    assert snap_mult is not None
    assert snap_power is not None
    # Power method assigns higher implied_probability to the favorite
    assert snap_power.implied_probability != snap_mult.implied_probability
    assert snap_power.implied_probability > snap_mult.implied_probability
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `fetch_nfl_odds()` hardcoded in context agent | `fetch_nba_odds()` or `fetch_nfl_odds()` based on `state["sport"]` | Phase 15 | NBA game context (ContextSignals.odds_snapshot) populated for NBA routes |
| `remove_vig_multiplicative` hardcoded in `_extract_odds_snapshot` | Config-selectable: `multiplicative` (default) or `pinnacle` | Phase 15 | `VIG_METHOD=pinnacle` in `.env` enables Pinnacle-method fair probability |
| `Settings` has no vig_method | `Settings.vig_method: Literal["multiplicative", "pinnacle"] = "multiplicative"` | Phase 15 | Environment-configurable without code changes |

**No deprecated patterns in this phase** — all changes are additive to existing code.

---

## Open Questions

1. **Should NBA prop ingestion (`fetch_player_props("nba")`) also be added to make_context_agent in Phase 15?**
   - What we know: Phase 14 added NFL prop ingestion (Step 1c). Phase 15 adds NBA game-level odds. The Phase 14 research explicitly deferred NBA prop ingestion to Phase 15.
   - What's unclear: Phase 15 success criteria only requires NBA game-level odds (`odds_snapshot` non-None). NBA prop ingestion is a separate concern.
   - Recommendation: Add NBA game-level odds only (matching CTXT-04 and Flow 2 success criteria). NBA prop ingestion (analogous to Step 1c for "nba") is a natural follow-on but is NOT in the Phase 15 success criteria. Do not add it unless the planner explicitly scopes it in.

2. **Should create_graph_with_sqlite() accept vig_method as a parameter?**
   - What we know: The production factory creates `make_context_agent`. It currently takes `api_key` and `daily_credit_cap`. If vig_method lives in Settings, the factory can read it from `settings.vig_method` without accepting a new parameter.
   - Recommendation: Do not add `vig_method` as a parameter to `create_graph_with_sqlite`. Instead, `make_context_agent` reads `settings.vig_method` when `vig_method=None` (its new default). The factory need not change. Config is environment-driven via `.env`.

3. **Does the NBA SPORT_KEY "basketball_nba" return game-level odds in pre-season/off-season?**
   - What we know: The Odds API returns an empty list when no events are scheduled. `_extract_odds_snapshot` already handles empty `raw_odds` by returning None. Budget guard protects against empty responses consuming credits unnecessarily (they still consume 1 credit).
   - What's unclear: No live API testing possible without credentials.
   - Recommendation: Document that empty list from `fetch_nba_odds()` is a valid response and `odds_snapshot=None` will result — consistent with existing behavior.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest with `asyncio_mode = "auto"` |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/test_context.py tests/test_vig.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CTXT-01 | `OddsAPIPoller.fetch_nba_odds()` exists, respects budget guard, returns list[dict] | unit | `pytest tests/test_context.py -k nba_odds -x` | needs new test |
| CTXT-04 | `make_context_agent` with `state["sport"]="nba"` produces `ContextSignals` with non-None `odds_snapshot` | unit (mock) | `pytest tests/test_context.py -k nba_context -x` | needs new test |
| CTXT-04 (regression) | Existing NFL context agent tests pass unchanged | unit | `pytest tests/test_context.py -x` | existing — must stay green |
| QUANT-02 | `vig_method="pinnacle"` config flag causes `remove_vig_power` to be used; output differs from `"multiplicative"` | unit | `pytest tests/test_context.py -k pinnacle -x` or new test file | needs new test |
| QUANT-02 (regression) | Existing vig unit tests all pass | unit | `pytest tests/test_vig.py -x` | existing — must stay green |

### Sampling Rate

- **Per task commit:** `pytest tests/test_context.py tests/test_vig.py -x`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] New test(s) for `OddsAPIPoller.fetch_nba_odds()` — covers CTXT-01 NBA path (budget guard, response parsing, credit tracking). Can be added to `tests/test_context.py` alongside existing CTXT-01 tests.
- [ ] New test for `make_context_agent` NBA routing — `state["sport"]="nba"` produces `ContextSignals.odds_snapshot is not None` when `fetch_nba_odds` mocked. Add to `tests/test_context.py`.
- [ ] New test for `_extract_odds_snapshot` vig_method dispatch — `vig_method="pinnacle"` vs `vig_method="multiplicative"` on asymmetric market produces different `implied_probability`. Can be in `tests/test_context.py` or a dedicated `tests/test_vig_completion.py`.
- [ ] `state.py` needs `sport: str | None` field — update any test fixtures that build a complete GraphState dict (check for `KeyError: sport` if LangGraph validates completeness at runtime; unlikely since TypedDict is not runtime-enforced in Python but test fixtures should be kept consistent).

*(If no new framework install needed — existing pytest infrastructure covers all requirements.)*

---

## Sources

### Primary (HIGH confidence)

- `src/sportsbet/ingestion/odds_poller.py` — `fetch_nfl_odds` is the exact template for `fetch_nba_odds`; `NBA_SPORT_KEY = "basketball_nba"` already defined at line 33
- `src/sportsbet/graph/agents.py` — `make_context_agent` closure (lines 132-303), `_extract_odds_snapshot` (lines 307-367) — both change sites identified with exact line references
- `src/sportsbet/quant/vig.py` — `remove_vig_multiplicative` and `remove_vig_power` — both complete and Decimal-correct; no changes needed
- `src/sportsbet/config.py` — `Settings` class — location for `vig_method` field addition; pattern confirmed (Pydantic v2 BaseSettings)
- `src/sportsbet/graph/state.py` — `GraphState` TypedDict — location for `sport: str | None` field addition; follows Phase 14 `prop_filters` pattern
- `tests/test_context.py` — all existing context agent tests — confirmed GREEN with full test run (156 passed, 11 skipped)
- `tests/test_vig.py` — all existing vig tests — confirmed GREEN

### Secondary (MEDIUM confidence)

- `.planning/phases/14-prop-integration-gap-closure/14-RESEARCH.md` — Phase 14 research documented: "NBA prop persistence follows naturally when Phase 15 adds NBA context agent routing"
- `.planning/STATE.md` — locked decisions: Phase 4 pattern for `make_context_agent` closure factory; Phase 3 pattern for `Decimal(str(round(x,6)))` wrapping

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies, all libraries already in use and tested
- Architecture: HIGH — both change sites (`_extract_odds_snapshot`, `make_context_agent`) read directly from source; pattern for `fetch_nba_odds` is a direct copy of `fetch_nfl_odds` with one constant substitution
- Pitfalls: HIGH — all five pitfalls verified from existing test code and prior phase decisions
- Test gaps: HIGH — test suite run confirms current baseline (156 passed); gaps identified by comparing Phase 15 success criteria against existing test files

**Research date:** 2026-03-23
**Valid until:** 2026-04-23 (stable codebase, no fast-moving dependencies)
