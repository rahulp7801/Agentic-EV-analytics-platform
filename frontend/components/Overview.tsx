'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowUpRight, CheckCircle2, CircleAlert, Clock3, Database, RefreshCw } from 'lucide-react';
import { motion, useReducedMotion } from 'motion/react';
import { marketFreshness } from '@/lib/marketFreshness';
import type { EVSignal, Sport } from '@/lib/types';
import {forecastWindow} from '@/lib/signalMetrics';
import {fetchForecasts} from '@/lib/fetchForecasts';
import PlayerPortrait from './PlayerPortrait';
import {bestPicks,conservativeMargin} from '@/lib/bestPicks';
import styles from './Overview.module.css';

type Source = {
  status: string;
  count: number;
  partial_coverage: boolean;
  reason?: string;
  coverage?: Record<string, number | boolean>;
};

type MarketData = {
  captured_at: string;
  sources: Record<'sportsbook' | 'kalshi' | 'prizepicks', Source>;
  comparisons: Array<{
    identity: string;
    kind: string;
    title: string;
    gross_cost: string;
    gross_gap_to_one_dollar: string;
    legs: Array<{ book: string; team: string; observed_at: string }>;
  }>;
};

type Scan = {
  state: string;
  label: string;
  updated_at: string | null;
  quotes: number | null;
  model_estimates: number | null;
};

type Metrics = {
  sample_size: number;
  settled_count: number;
  pending_count: number;
  excluded_missing_metadata: number;
  clv_count: number;
  clv_mean: number | null;
};

type DashboardData = {
  forecasts?: EVSignal[];
  picks?: EVSignal[];
  forecastsComplete?: boolean;
  forecastTotal?: number;
  markets?: MarketData;
  scan?: Scan;
  games?: Array<unknown>;
  metrics?: Metrics;
  errors: string[];
  checkedAt: number;
};

const SOURCE_LABELS = { sportsbook: 'Sportsbooks', kalshi: 'Kalshi', prizepicks: 'PrizePicks' } as const;

function elapsed(value: string | null | undefined, now: number) {
  if (!value) return 'No capture';
  const minutes = Math.max(0, Math.floor((now - Date.parse(value)) / 60_000));
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return hours < 48 ? `${hours}h ago` : `${Math.floor(hours / 24)}d ago`;
}

function sourceCopy(source?: Source) {
  if (!source) return 'No published observation';
  if (source.status === 'observed') return source.partial_coverage ? 'Observed · partial sample' : 'Observed';
  if (source.status === 'not_requested') return 'Not collected in this run';
  if (source.reason === 'access_denied') return 'Provider denied public access';
  if (source.reason === 'rate_limited') return 'Provider rate limited';
  return 'Collection unavailable';
}

async function json<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(path, { cache: 'no-store', signal });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `${path} unavailable`);
  return body as T;
}

export default function Overview({ sport, onOpenMarkets,onOpenPlayers }: { sport: Sport; onOpenMarkets: () => void;onOpenPlayers:(player?:string)=>void }) {
  const reduceMotion = useReducedMotion();
  const [data, setData] = useState<DashboardData>({ errors: [], checkedAt: 0 });
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const request = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), 12_000);
    const results = await Promise.allSettled([
      json<MarketData>(`/api/markets?sport=${sport}`, controller.signal),
      json<Record<Sport, Scan>>('/api/scans', controller.signal),
      json<{ games: Array<unknown> }>(`/api/games?sport=${sport}`, controller.signal),
      json<Metrics>(`/api/metrics?sport=${sport}`, controller.signal),
      fetchForecasts(sport,controller.signal),
      fetchForecasts(sport,controller.signal,'qualified').then(body=>{
        if(!body.complete) throw new Error('Incomplete candidate coverage');
        return body;
      }),
    ]);
    window.clearTimeout(timeout);
    if (request.current !== controller) return;
    const errors: string[] = [];
    results.forEach((result, index) => {
      if (result.status === 'rejected') errors.push(['Markets', 'Model scan', 'Schedule', 'Evaluation','Player forecasts','Qualified picks'][index]);
    });
    setData({
      markets: results[0].status === 'fulfilled' ? results[0].value : undefined,
      scan: results[1].status === 'fulfilled' ? results[1].value[sport] : undefined,
      games: results[2].status === 'fulfilled' ? results[2].value.games : undefined,
      metrics: results[3].status === 'fulfilled' ? results[3].value : undefined,
      forecasts: results[4].status==='fulfilled' ? results[4].value.signals : undefined,
      forecastsComplete: results[4].status==='fulfilled' ? results[4].value.complete : undefined,
      forecastTotal: results[4].status==='fulfilled' ? results[4].value.total_count : undefined,
      picks: results[5].status==='fulfilled' ? results[5].value.signals : undefined,
      errors,
      checkedAt: Date.now(),
    });
    setLoading(false);
    setRefreshing(false);
  }, [sport]);

  useEffect(() => {
    const initial = window.setTimeout(() => void load(), 0);
    const timer = window.setInterval(() => void load(), 30_000);
    return () => {
      request.current?.abort();
      window.clearTimeout(initial);
      window.clearInterval(timer);
    };
  }, [load]);

  const refresh = async () => {
    setRefreshing(true);
    await load();
    if (request.current && !request.current.signal.aborted) setRefreshing(false);
  };

  const kalshi = data.markets?.sources.kalshi;
  const linkedProps = Number(kalshi?.coverage?.prop_linked_markets ?? 0);
  const twoSided = Number(kalshi?.coverage?.prop_two_sided_quote_markets ?? 0);
  const current = marketFreshness(data.markets?.captured_at, data.checkedAt) === 'current';
  const players=[...new Map((data.forecasts ?? []).map(signal=>[signal.player,signal])).values()];
  const upcoming=(data.forecasts ?? []).filter(signal=>forecastWindow(signal,data.checkedAt)==='upcoming').length;
  const picks=bestPicks(data.picks ?? []);
  const cards = useMemo(() => [
    { label: 'Games observed', value: data.games?.length ?? null, note: `${sport.toUpperCase()} schedule window`, tone: 'blue' },
    { label: 'Kalshi player props', value: kalshi ? linkedProps : null, note: kalshi ? `${twoSided} with two-sided quotes` : 'No market capture', tone: 'violet' },
    { label: data.forecastsComplete===false ? 'Loaded forecasts' : 'Recorded forecasts', value: data.forecasts?.length ?? null, note: data.forecastsComplete===false ? `Research window · ${data.forecastTotal} recent records available` : `${players.length} players · ${upcoming} upcoming forecasts`, tone: 'green' },
    { label: 'Evaluation sample', value: data.metrics?.sample_size ?? null, note: data.metrics ? `${data.metrics.pending_count} pending · ${data.metrics.settled_count} settled · ${data.metrics.excluded_missing_metadata} excluded` : 'No metrics snapshot', tone: 'slate' },
  ], [data, kalshi, linkedProps, sport, twoSided,players.length,upcoming]);

  return (
    <motion.section className={styles.overview} initial={reduceMotion ? false : { opacity: 0 }} animate={{ opacity: 1 }}>
      <header className={styles.hero}>
        <div>
          <div className={styles.kicker}>
            <span className={`${styles.liveDot} ${current ? styles.live : ''}`} />
            {current ? 'Current market observation' : 'Last published observation'}
          </div>
          <h1>{sport.toUpperCase()} research desk</h1>
          <p>Explore real forecasts, player history, and the price behind each estimate.</p>
        </div>
        <div className={styles.heroActions}>
          <button type="button" className={styles.refresh} onClick={refresh} disabled={refreshing}>
            <RefreshCw size={16} className={refreshing ? styles.spinning : undefined} />
            Refresh
          </button>
          <button type="button" className={styles.primary} onClick={()=>onOpenPlayers()}>
            Explore players <ArrowUpRight size={17} />
          </button>
          <span>{data.markets ? `Captured ${elapsed(data.markets.captured_at, data.checkedAt)}` : 'Awaiting market capture'}</span>
        </div>
      </header>

      {loading && <div className={styles.loading}><span /> Reading published evidence</div>}
      <motion.div key={sport} initial={reduceMotion ? false : { opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
            {data.errors.length > 0 && (
              <div className={styles.partialNotice}><CircleAlert size={16} /> {data.errors.join(', ')} unavailable. Other panels remain live.</div>
            )}

            <div className={styles.metricGrid}>
              {cards.map(card => (
                <article className={styles.metricCard} key={card.label} data-tone={card.tone}>
                  <span>{card.label}</span>
                  <strong>{card.value === null ? '—' : card.value.toLocaleString()}</strong>
                  <small>{card.note}</small>
                </article>
              ))}
            </div>

            <section className={styles.shortlist} aria-label="Qualified picks">
              <div><h2>Strongest qualified picks <span>{picks.length}</span></h2><p>{data.errors.includes('Qualified picks') ? 'The shortlist could not be fully checked. Refresh to try again; recorded forecasts remain available.' : picks.length ? 'Ranked by the margin that remains at the reported 95% lower probability bound.' : 'No picks clear every current check. Explore the recorded forecasts below.'}</p></div>
              <details><summary>How picks qualify</summary><p>Fresh prices, at least 20 prior games, verified roster and injury screening, a positive lower-bound margin above the price’s break-even probability, and approved risk limits. At most three distinct player/game choices; the list can stay empty. Ranking measures model evidence, not guaranteed profit or proven future performance.</p></details>
              {picks.length>0 && <div className={styles.pickRows}>{picks.map(pick=><button key={pick.id} type="button" onClick={()=>onOpenPlayers(pick.player)}><PlayerPortrait signal={pick} /><div><strong>{pick.player}</strong><small>{pick.direction} {pick.line} {pick.prop_type.replaceAll('_',' ')} · {pick.sportsbook}</small></div><span>+{(conservativeMargin(pick)!*100).toFixed(1)}pp<small>Lower-bound margin</small></span></button>)}</div>}
            </section>

            <section className={styles.playersPanel} aria-label="Recorded player forecasts">
              <div className={styles.comparisonHeading}><div><span>Your research starts here</span><h2>Players in your forecast library</h2></div><button type="button" onClick={()=>onOpenPlayers()}>All players <ArrowUpRight size={15} /></button></div>
              {players.length ? <><div className={styles.playersGrid}>{players.slice(0,8).map(signal=><button type="button" key={signal.player} onClick={()=>onOpenPlayers(signal.player)}><PlayerPortrait signal={signal} /><strong>{signal.player}</strong><small>{signal.player_profile?.team ?? signal.availability?.team ?? sport.toUpperCase()}{signal.player_profile?.jersey ? ` · #${signal.player_profile.jersey}` : ''}{signal.player_profile?.position ? ` · ${signal.player_profile.position}` : ''}</small><span>{data.forecasts?.filter(s=>s.player===signal.player).length} forecasts <ArrowUpRight size={12} /></span></button>)}</div><p>{upcoming ? 'Upcoming records still require fresh quotes and all model risk checks.' : 'Recorded forecasts remain available after kickoff. Historical prices are expired; these are research records, not current picks.'} Player profiles show separately captured roster metadata.</p></> : <div className={styles.emptyComparisons}>{loading ? 'Loading your players…' : data.errors.includes('Player forecasts') ? 'Player records could not be loaded. Refresh to try again.' : `No ${sport.toUpperCase()} player forecasts are published. Switch leagues to explore available records.`}</div>}
            </section>

            <div className={styles.contentGrid}>
              <section className={styles.panel}>
                <div className={styles.panelHeader}>
                  <div><span>Venue health</span><h2>What is available now</h2></div>
                  <Database size={20} />
                </div>
                <div className={styles.sourceList}>
                  {(Object.keys(SOURCE_LABELS) as Array<keyof typeof SOURCE_LABELS>).map(name => {
                    const source = data.markets?.sources[name];
                    const observed = source?.status === 'observed';
                    return (
                      <div className={styles.sourceRow} key={name}>
                        <span className={`${styles.sourceIcon} ${observed ? styles.sourceLive : ''}`}>{observed ? <CheckCircle2 /> : <Clock3 />}</span>
                        <div><strong>{SOURCE_LABELS[name]}</strong><small>{sourceCopy(source)}</small></div>
                        <b>{source?.count?.toLocaleString() ?? '—'}</b>
                      </div>
                    );
                  })}
                </div>
              </section>

              <section className={`${styles.panel} ${styles.truthPanel}`}>
                <div className={styles.panelHeader}>
                  <div><span>Evidence state</span><h2>What the numbers mean</h2></div>
                  <CircleAlert size={20} />
                </div>
                <div className={styles.truthList}>
                  <div><span>01</span><p><strong>Outcome metrics need final results.</strong> {data.metrics?.pending_count ?? 'Recorded'} predictions are pending settlement and {data.metrics?.excluded_missing_metadata ?? 'some'} incomplete records are excluded, so ROI and hit rate are intentionally withheld.</p></div>
                  <div><span>02</span><p><strong>League schedules are seasonal.</strong> An empty NBA slate in September is valid coverage, not a fabricated zero.</p></div>
                  <div><span>03</span><p><strong>Paid provider scans are independent.</strong> A stale model scan does not erase current public Kalshi observations.</p></div>
                </div>
              </section>
            </div>

            <section className={styles.comparisons}>
              <div className={styles.comparisonHeading}>
                <div><span>Latest comparison set</span><h2>Observed price relationships</h2></div>
                <button type="button" onClick={onOpenMarkets}>View all <ArrowUpRight size={15} /></button>
              </div>
              {!data.markets?.comparisons.length ? (
                <div className={styles.emptyComparisons}>No comparable two-leg prices were published for this capture.</div>
              ) : (
                <div className={styles.comparisonRows}>
                  {data.markets.comparisons.slice(0, 5).map(item => (
                    <article key={`${item.kind}-${item.identity}`}>
                      <div><span>{item.kind.replaceAll('_', ' ')}</span><strong>{item.title}</strong></div>
                      <div><span>Combined cost</span><strong>${Number(item.gross_cost).toFixed(3)}</strong></div>
                      <div><span>Gross gap</span><strong className={Number(item.gross_gap_to_one_dollar) > 0 ? styles.positive : ''}>${Number(item.gross_gap_to_one_dollar).toFixed(3)}</strong></div>
                      <ArrowUpRight size={16} />
                    </article>
                  ))}
                </div>
              )}
              <p className={styles.disclosure}>Observed price gaps exclude complete execution, funding, limit, and settlement risk. They are research leads, not realized profit.</p>
            </section>
      </motion.div>
    </motion.section>
  );
}
