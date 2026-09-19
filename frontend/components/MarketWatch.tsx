'use client';

import { useEffect, useState } from 'react';
import type { Sport } from '@/lib/types';
import { marketFreshness } from '@/lib/marketFreshness';
import {
  marketCoverageText,
  propQuoteCoverageText,
  sourceFailureText,
  type MarketCoverage,
  type PropQuoteCoverage,
} from '@/lib/marketCoverage';
import styles from './ResearchViews.module.css';

const SOURCE_LABELS:Record<string,string>={observed:'Observed',degraded:'Limited coverage',unavailable:'Unavailable',not_requested:'Not requested',budget_exhausted:'API budget reached'};

interface Observation {
  captured_at: string;
  scope: string;
  sources: Record<string, { status: string; count: number; partial_coverage: boolean; reason?: string;
    coverage?: (MarketCoverage & Partial<PropQuoteCoverage> & { discovery_complete: boolean; omitted_markets: number;
      prop_discovery_complete?: boolean; prop_series_observed?: number; prop_series_expected?: number; prop_open_markets?: number; prop_open_events?: number; prop_linked_markets?: number; prop_linked_events?: number; prop_player_resolved_quote_markets?: number }) }>;
  comparisons: { identity: string; kind: string; title: string; gross_cost: string; gross_gap_to_one_dollar: string;
    reasons: string[]; legs: { book: string; team: string; cost: string; observed_at: string }[];
    exchange_fee_scenarios?: { combined_cost: { direct: string; non_direct: string }; scope: string; schedule_effective_date: string };
    depth_fee_scenarios?: { cases: { contracts_per_kalshi_leg: number; combined_cost: { direct: string; non_direct: string } }[]; scope: string } }[];
}

interface PropFunnel {
  kalshi_quotes: number;
  kalshi_exact_markets: number;
  kalshi_paired_sides: number;
  kalshi_missing_ask_sides: number;
  kalshi_missing_sportsbook_sides: number;
  kalshi_observation_skew_sides: number;
}

interface PropScreen { generated_at: string; status: string; coverage: Partial<PropFunnel> }
interface Slate { games: {provider_event_id:string;home_name:string;away_name:string;game_time:string;state:string}[]; partial:boolean }

function hasPropFunnel(value: Partial<PropFunnel>): value is PropFunnel {
  return ['kalshi_quotes', 'kalshi_exact_markets', 'kalshi_paired_sides', 'kalshi_missing_ask_sides',
    'kalshi_missing_sportsbook_sides', 'kalshi_observation_skew_sides'].every(
      key => typeof value[key as keyof PropFunnel] === 'number');
}

export default function MarketWatch({ sport }: { sport: Sport }) {
  const [data, setData] = useState<Observation | null>(null);
  const [error, setError] = useState('');
  const [propScreen, setPropScreen] = useState<PropScreen | null>(null);
  const [propError, setPropError] = useState('');
  const [slate,setSlate]=useState<Slate|null>(null);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError('');
    setPropScreen(null);
    setPropError('');
    setSlate(null);

    async function load() {
      try {
        const response = await fetch(`/api/markets?sport=${sport}`, { signal: controller.signal, cache: 'no-store' });
        const body = await response.json();
        if (!response.ok) throw new Error(body.error || 'Market observations unavailable.');
        if(controller.signal.aborted) return;
        setData(body);
        setError('');
        setNow(Date.now());
      } catch (loadError) {
        if (!controller.signal.aborted) {
          setError(loadError instanceof Error ? loadError.message : 'Market observations unavailable.');
          setNow(Date.now());
        }
      }
    }

    async function loadProps() {
      if(sport==='cfb') return;
      try {
        const response = await fetch(`/api/prop-screens?sport=${sport}`, { signal: controller.signal, cache: 'no-store' });
        const body = await response.json();
        if (!response.ok) throw new Error(body.error || 'Cross-venue prop scan unavailable.');
        if(controller.signal.aborted) return;
        setPropScreen(body);
        setPropError('');
      } catch (loadError) {
        if (!controller.signal.aborted) {
          setPropScreen(null);
          setPropError(loadError instanceof Error ? loadError.message : 'Cross-venue prop scan unavailable.');
        }
      }
    }

    async function loadSlate() {
      if(sport!=='cfb') return;
      try {
        const response=await fetch('/api/slate?sport=cfb',{signal:controller.signal,cache:'no-store'});
        const body=await response.json();
        if(!response.ok) throw new Error('Schedule unavailable');
        if(!controller.signal.aborted) setSlate(body);
      } catch { if(!controller.signal.aborted) setSlate(null); }
    }

    void load();
    void loadProps();
    void loadSlate();
    const timer = setInterval(() => { void load(); void loadProps(); void loadSlate(); }, 30_000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [sport]);

  const funnel = propScreen && hasPropFunnel(propScreen.coverage) ? propScreen.coverage : null;
  const freshness = marketFreshness(data?.captured_at, now);
  const propScreenCurrent = propScreen?.status !== 'stale';

  return (
    <section className={styles.view} aria-labelledby="market-watch-title" tabIndex={0}>
      <header className={styles.viewHeader}>
        <div>
          <small>Cross-venue observation · {sport.toUpperCase()}</small>
          <h2 id="market-watch-title">Market gaps</h2>
        </div>
        <p>{sport==='cfb' ? 'Upcoming FBS games and captured sportsbook moneylines. College player models, Kalshi links, and PrizePicks comparisons remain unavailable until their identities and settlement contracts are verified.' : 'Sportsbooks, Kalshi, and PrizePicks are compared from captured quotes. Every displayed lead stays unverified until timing, settlement, fees, and executable depth align.'}</p>
      </header>

      {sport==='cfb' && <div className={styles.notice}>CFB market-only beta. The existing credit ledger permits at most one bounded game-market request per capture; no player pick is inferred from an NFL model.</div>}
      {sport==='cfb' && slate && <div className={styles.sourceGrid} aria-label="Upcoming CFB schedule">
        {slate.games.slice(0,12).map(game=><article className={styles.sourceCard} key={game.provider_event_id}>
          <div className={styles.sourceCardHeader}><span>{game.away_name} at {game.home_name}</span><span>{new Date(game.game_time).toLocaleString(undefined,{weekday:'short',hour:'numeric',minute:'2-digit'})}</span></div>
          <p>{game.state}</p>
        </article>)}
      </div>}
      {sport==='cfb' && slate && slate.games.length>12 && <details className={styles.marketDetails}>
        <summary>Show {slate.games.length-12} more upcoming games</summary>
        <div className={styles.sourceGrid}>{slate.games.slice(12).map(game=><article className={styles.sourceCard} key={game.provider_event_id}>
          <div className={styles.sourceCardHeader}><span>{game.away_name} at {game.home_name}</span><span>{new Date(game.game_time).toLocaleString(undefined,{weekday:'short',hour:'numeric',minute:'2-digit'})}</span></div>
          <p>{game.state}</p>
        </article>)}</div>
      </details>}
      {sport==='cfb' && slate && !slate.games.length && <div className={styles.emptyInline}>No upcoming FBS games were returned for the seven-day schedule window.</div>}

      {error && <div className={styles.notice} role="alert">{error}</div>}
      {!data && !error && <div className={styles.notice}>Loading current observations…</div>}

      {data && (
        <>
          <div className={styles.sourceGrid}>
            {Object.entries(data.sources).map(([name, source]) => (
              <article className={styles.sourceCard} key={name}>
                <div className={styles.sourceCardHeader}><span>{name}</span><span>{source.reason==='collection_cadence' ? 'Waiting for capture' : SOURCE_LABELS[source.status] ?? 'Unavailable'}</span></div>
                <p>{source.count} source records{source.partial_coverage ? ' · partial coverage' : ''}
                  {sourceFailureText(source.reason) && ` · ${sourceFailureText(source.reason)}`}
                </p>
                {source.coverage && <details className={styles.marketDetails}><summary>Coverage details</summary><p>
                  {source.coverage && ` · ${marketCoverageText(source.coverage)}`}
                  {source.coverage && !source.coverage.discovery_complete && ' · discovery incomplete'}
                  {source.coverage && source.coverage.omitted_markets > 0 && ` · ${source.coverage.omitted_markets} markets omitted`}
                  {source.coverage?.prop_series_expected !== undefined && ` · ${source.coverage.prop_linked_markets} player props linked across ${source.coverage.prop_linked_events} events`}
                  {source.coverage?.prop_structured_quote_markets !== undefined && ` · ${propQuoteCoverageText(source.coverage as PropQuoteCoverage)}`}
                  {source.coverage?.prop_player_resolved_quote_markets !== undefined && ` · ${source.coverage.prop_player_resolved_quote_markets} player identities resolved`}
                </p></details>}
              </article>
            ))}
          </div>

          <div className={styles.notice}>
            {freshness === 'current' ? 'Current capture' : 'Historical capture'} from {new Date(data.captured_at).toLocaleString()} · {data.scope} Positive gross gaps are screening leads, not profit. PrizePicks projection lines require a complete entry payout before arbitrage can be established.
          </div>

          {funnel && propScreen && (
            <>
              <div className={styles.notice}>
                {propScreenCurrent ? 'Current' : 'Historical'} paid prop scan from {new Date(propScreen.generated_at).toLocaleString()}
                {' · '}{propScreenCurrent
                  ? 'Captured coverage is current evidence, not an executable opportunity count.'
                  : 'Captured coverage is retained for audit and is not a current opportunity count.'}
              </div>
              <div className={styles.funnel} aria-label={`Cross-venue prop pairing ${propScreen.status}`}>
                <div><span>Captured Kalshi quotes</span><strong>{funnel.kalshi_quotes}</strong></div>
                <div><span>Captured exact markets</span><strong>{funnel.kalshi_exact_markets}</strong></div>
                <div><span>Captured paired sides</span><strong>{funnel.kalshi_paired_sides}/{2 * funnel.kalshi_exact_markets}</strong></div>
                <div><span>Captured exclusions</span><strong>{funnel.kalshi_missing_ask_sides + funnel.kalshi_missing_sportsbook_sides + funnel.kalshi_observation_skew_sides}</strong></div>
              </div>
            </>
          )}
          {sport!=='cfb' && propError && <div className={styles.notice}>Cross-venue prop scan: {propError}</div>}

          {data.comparisons.length === 0 ? (
            <div className={styles.emptyInline}>No comparisons could be built from this capture.</div>
          ) : (
            <div className={styles.comparisonList}>
              {data.comparisons.map(row => {
                const age = now - Math.min(...row.legs.map(leg => Date.parse(leg.observed_at)));
                const recent = Number.isFinite(age) && age >= 0 && age <= 30_000;
                return (
                  <article className={`card ${styles.comparison}`} key={row.kind + row.identity}>
                    <header className={styles.comparisonHeader}>
                      <strong>{row.title}</strong>
                      <span>{row.kind.replaceAll('_', ' ')} · {recent ? 'recent' : 'stale'}</span>
                    </header>
                    <div className={styles.comparisonCost}>
                      <div><span>Gross cost / $1</span><strong>${Number(row.gross_cost).toFixed(4)}</strong></div>
                      <div><span>Gross gap</span><strong>${Number(row.gross_gap_to_one_dollar).toFixed(4)}</strong></div>
                    </div>
                    <ul className={styles.legList}>
                      {row.legs.map((leg, index) => (
                        <li key={index}>
                          <span>{leg.book} · {leg.team} · ${Number(leg.cost).toFixed(4)}</span>
                          <time dateTime={leg.observed_at}>{new Date(leg.observed_at).toLocaleTimeString()}</time>
                        </li>
                      ))}
                    </ul>
                    <div className={styles.comparisonBody}>
                      {(row.exchange_fee_scenarios || row.depth_fee_scenarios) && <details className={styles.marketDetails}><summary>Fee scenarios and limits</summary>
                      {row.exchange_fee_scenarios && (
                        <p>Modeled with exchange fees: ${Number(row.exchange_fee_scenarios.combined_cost.direct).toFixed(4)} direct · ${Number(row.exchange_fee_scenarios.combined_cost.non_direct).toFixed(4)} non-direct. {row.exchange_fee_scenarios.scope}</p>
                      )}
                      {row.depth_fee_scenarios && (
                        <p>{row.depth_fee_scenarios.cases.length
                          ? row.depth_fee_scenarios.cases.map(scenario => `${scenario.contracts_per_kalshi_leg} contracts: $${Number(scenario.combined_cost.direct).toFixed(4)} direct / $${Number(scenario.combined_cost.non_direct).toFixed(4)} non-direct`).join(' · ')
                          : 'Insufficient displayed depth for the requested sizes.'} {row.depth_fee_scenarios.scope}</p>
                      )}
                      </details>}
                      <p>{row.reasons.join(' ')}</p>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </>
      )}
    </section>
  );
}
