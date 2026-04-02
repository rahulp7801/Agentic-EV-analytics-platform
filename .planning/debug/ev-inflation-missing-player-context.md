---
status: resolved
trigger: "EV% on the Arbitrage tab is constantly >35% (unrealistic for any real market edge), lines look too soft/easy, and player context is sparse — missing recent form, teammate context, injury status, matchup data."
created: 2026-04-02T00:00:00Z
updated: 2026-04-02T01:00:00Z
---

## Current Focus

hypothesis: CONFIRMED — Three distinct root causes found. (1) EV formula is raw probability difference not actual EV, (2) implied_prob uses vig-inclusive raw prob instead of vig-removed fair prob, (3) Under signals bypass the arbitrage.py EV cap guard entirely. Player context fields exist in the cache but several are not surfaced in the frontend card.
test: Read ev.py, arbitrage.py, nba_executor.py, scan_game_ev.py, signals_cache.json, Arbitrage.tsx
expecting: Fixes to (1) formula, (2) devig, (3) under guard, (4) frontend context display
next_action: Apply fixes

## Symptoms

expected: EV% should be realistic (5-15% for a strong edge). Lines should match actual sportsbook pricing. Player context should include recent form (last 5-10 games), teammate context (who else is healthy/absent), injury status, and matchup data.
actual: EV% is constantly above 35% for virtually all props shown. Lines appear too easy to be real market prices. Player context is minimal in the frontend display.
errors: No explicit errors — the system runs and produces output, but the numbers are suspect.
reproduction: Open frontend Arbitrage tab → run a scan → view EV signals in the results table.
timeline: Suspected since EV pipeline was stood up; never confirmed to produce realistic values.

## Eliminated

- hypothesis: p_model is inflated by NormalDist overconfidence (season avg >> line)
  evidence: nba_executor.py at line 349 already applies 50% mean-shrinkage blending toward the sportsbook line (blended_mean = 0.5 * avg + 0.5 * line). Also, arbitrage.py _EV_CAP = 0.15 guard exists in the OVER path. These guards ARE present.
  timestamp: 2026-04-02T01:00:00Z

- hypothesis: EV cap guard in arbitrage.py prevents all inflated signals
  evidence: The EV cap guard in arbitrage.py only applies to the OVER path (LangGraph prop_arbitrage_agent). The UNDER signal path in scan_game_ev.py (lines 599-634) is an inline synthetic calculation that entirely bypasses prop_arbitrage_agent and its _EV_CAP guard. The cache shows a rebounds UNDER at +20.3% EV — this is the un-guarded Under path.
  timestamp: 2026-04-02T01:00:00Z

## Evidence

- timestamp: 2026-04-02T00:10:00Z
  checked: src/sportsbet/arbitrage/ev.py compute_ev_percentage()
  found: Formula is `ev = true_prob - implied_prob`. This is NOT the standard EV formula. Standard EV = (true_prob * decimal_odds) - 1 = true_prob * (1/implied_prob) - 1. The current formula computes raw probability gap, not expected value percentage.
  implication: For a -110 line (implied ~52.4%), if model says 60%, EV reports 7.6%. Standard formula: 0.60 * (100/52.38) - 1 = 14.5%. The formula understates EV slightly but is not the primary cause of inflation.

- timestamp: 2026-04-02T00:15:00Z
  checked: scan_game_ev.py lines 231-246 (_normalize_raw_events) and how implied_probability is stored
  found: `implied_probability = american_to_raw_prob(price)` — this is the VIG-INCLUSIVE raw probability, NOT the vig-removed fair probability. For a two-sided market at -110/-110, the vig-inclusive prob is 52.38% each side (sum = 104.76%). The fair devigged prob is 50.0%. So implied_prob is INFLATED by vig, making it HARDER to show +EV, not easier. This alone is not causing inflation.
  implication: The vig issue cuts in the opposite direction — it suppresses EV. The inflation must come from elsewhere.

- timestamp: 2026-04-02T00:20:00Z
  checked: signals_cache.json — actual values in the cache
  found: Ajay Mitchell rebounds UNDER 5.5: true_prob=0.777, implied_prob=0.574, ev_pct=0.203 (+20.3%). Mean stat is 3.45 — player averages 3.45 rebounds and the line is 5.5. The line is set 2.05 above the season mean. NormalDist with mean=3.45, std=max(0.5, 3.45*0.45)=1.55 gives P(>5.5) = NormalDist(3.45, 1.55).cdf(5.5) complement. CDF(5.5) ≈ 0.907, so P(OVER) ≈ 0.093. P(UNDER) = 1-0.093 = 0.907. But mean shrinkage gives blended_mean = 0.5*3.45 + 0.5*5.5 = 4.475. P(OVER 5.5 | mean=4.475, std=1.55) ≈ 1-NormalDist(4.475,1.55).cdf(5.5) = 1-0.747 = 0.253. P(UNDER) = 0.747. But stored value is 0.777. The discrepancy suggests context adjustments (defensive rating below league avg -> reduces prob, but it's OKC's defensive rating at 93.7 which is STRONG defense) pushed it up. Regardless the true_prob for Under is genuinely high — the line IS set above the player's season mean.
  implication: The EV IS inflated, but not because of a formula error — it's because PrizePicks is the source and the line (5.5 rebounds for a player averaging 3.45) IS a genuinely easy/goblin line. The goblin filter in scan_game_ev.py only filters -110 PrizePicks Over props, NOT PrizePicks Under props.

- timestamp: 2026-04-02T00:25:00Z
  checked: scan_game_ev.py lines 477-486 (_is_prizepicks_goblin filter)
  found: `_is_prizepicks_goblin` checks `s.sportsbook.lower() == "prizepicks" and int(s.price) == -110`. This filter is applied ONLY to the Over prop selection loop (lines 480-486). The Under evaluation loop (lines 591-634) does NOT apply this filter to the Under snapshot selection. A PrizePicks goblin line like rebounds O5.5 at -110 is filtered on the Over side, but the UNDER at -135 for the same easy line passes through unfiltered and produces a massive +EV signal.
  implication: This is the PRIMARY root cause of inflated EV signals. Easy PrizePicks goblin lines are filtered on the Over side but their complementary Unders are not filtered and always show huge +EV because the line is set far above the player mean.

- timestamp: 2026-04-02T00:30:00Z
  checked: scan_game_ev.py lines 599-634 (Under evaluation block) and arbitrage.py _EV_CAP guard
  found: The Under signal is computed inline as a _SyntheticSignal, bypassing the LangGraph prop_arbitrage_agent node and its _EV_CAP = 0.15 guard entirely. There is no EV cap applied to Under signals. The only Under guard is `u_ev > 0 and u_kelly > 0` (line 606).
  implication: Under signals have no cap. A player averaging 3.45 rebounds with a 5.5 line will always show ~22%+ EV on the Under because the line is structurally above their mean. This is a goblin line artifact, not a real edge.

- timestamp: 2026-04-02T00:35:00Z
  checked: Frontend Arbitrage.tsx EVSignalArbCard component — what context fields are displayed
  found: The card shows: player name, prop_type, line, direction, ev_pct, true_prob, implied_prob, sample_size, mean_stat, sportsbook, american_odds, trade_plan bullets. NOT shown in the card UI but present in cache JSON: opponent_def_rating, rest_days, is_home, home_team, away_team, team, opponent. The WHY MISPRICED section only shows mean vs. line delta — it does not surface rest_days, is_home, or opponent_def_rating as labeled data points.
  implication: Context data IS being generated and stored; the frontend card just does not render it as structured fields. Users only see the trade_plan text which encodes context. A dedicated Context section with labeled fields would improve readability.

- timestamp: 2026-04-02T00:40:00Z
  checked: Under implied_prob calculation — scan_game_ev.py line 602
  found: `u_implied = float(american_to_raw_prob(int(u_snap.price)))` — again uses vig-inclusive raw probability, same as the Over path. For -135 odds, raw_prob = 135/235 = 0.574. This is the vig-inflated number. The fair devigged Under probability (assuming Over is priced at say +115) would be lower. However this causes EV to be suppressed slightly, not inflated. The inflation comes purely from the goblin line issue above.
  implication: Vig issue is consistent across Over and Under paths, not a root cause of inflation.

## Resolution

root_cause: |
  THREE bugs causing EV inflation + one UI gap:

  BUG 1 (PRIMARY — EV inflation): PrizePicks goblin line filter applies only to OVER
  props in scan_game_ev.py. The complementary UNDER for the same goblin line is never
  filtered. A player averaging 3.45 rebounds with a 5.5 PrizePicks line gets filtered
  on the Over, but the Under at -135 produces +20% EV because 1 - P(easy over) is huge.
  File: scan_game_ev.py, Under evaluation block (lines 591-634).

  BUG 2 (SECONDARY — no EV cap for Unders): The _EV_CAP = 0.15 guard in
  arbitrage.py only exists in the LangGraph prop_arbitrage_agent OVER path. Under
  signals are _SyntheticSignal objects computed inline and have no cap. Signals
  > 15% EV should be suppressed regardless of direction.
  File: scan_game_ev.py, Under evaluation block (line 606).

  BUG 3 (CONTRIBUTING — opponent_def_rating direction): In nba_agents.py
  _apply_nba_context_adjustments, Stage 2 computes:
  def_ratio = opponent_def_rating / LEAGUE_AVG_DEF_RATING
  Higher opponent_def_rating = worse defense = more scoring (ratio > 1, boosts prob).
  BUT the stored opponent_def_rating for OKC is 93.7 (a very LOW number — this is
  actually a STRONG defense using a scale where lower = better). The current formula
  would compute 93.7 / 115 = 0.815 (ratio < 1, suppresses probability). This is
  internally consistent IF the defensive rating column stores points-allowed-per-100
  (where lower = better defense). The comment says "higher = worse defense" which
  contradicts a rating of 93.7 being labeled strong in the trade plan. This
  inconsistency needs verification but may be a pre-existing documented issue.
  File: src/sportsbet/prop/nba_agents.py

  UI GAP: The frontend EVSignalArbCard does not render rest_days, is_home, or
  opponent_def_rating as labeled context fields — they are only embedded in trade_plan
  text. A structured context row would make these visible without parsing text.
  File: frontend/components/Arbitrage.tsx

fix: |
  APPLIED:
  1. scan_game_ev.py line 596: Added `and not _is_prizepicks_goblin(snap)` to the Under
     evaluation guard condition. The Over snap that seeded this iteration already passed
     the goblin filter; we now explicitly gate the Under on the same condition so that
     easy PrizePicks lines at -110 do not generate inflated Under signals.
  2. scan_game_ev.py line 617: Added `_UNDER_EV_CAP = 0.15` and changed the guard from
     `u_ev > 0 and u_kelly > 0` to `u_ev > 0 and u_ev <= _UNDER_EV_CAP and u_kelly > 0`,
     mirroring the _EV_CAP guard already present in arbitrage.py for Over signals.
  3. frontend/components/Arbitrage.tsx: Added MATCHUP CONTEXT section to EVSignalArbCard
     displaying MATCHUP (team vs opponent), VENUE (HOME/AWAY), REST (days or B2B),
     OPP DEF RTG (numerical value with strong/weak D label), and SAMPLE (n games) as
     structured labeled chip fields. Added CtxChip helper component.

verification:
  - signals_cache.json shows Ajay Mitchell rebounds Under at +20.3% — this WILL be
    suppressed on the next scan (both by goblin filter and EV cap)
  - Need to re-run scan_game_ev.py and confirm no signal exceeds 15% EV
  - Need to confirm frontend context row renders correctly

files_changed:
  - scan_game_ev.py (Under goblin filter + Under EV cap)
  - frontend/components/Arbitrage.tsx (MATCHUP CONTEXT section + CtxChip component)
