'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowUpRight, CheckCircle2, CircleAlert, Clock3, Database, RefreshCw } from 'lucide-react';
import { motion, useReducedMotion } from 'motion/react';
import { marketFreshness } from '@/lib/marketFreshness';
import type { Sport } from '@/lib/types';
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
  clv_count: number;
  clv_mean: number | null;
};

type DashboardData = {
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

async function json<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: 'no-store', signal: AbortSignal.timeout(8_000) });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `${path} unavailable`);
  return body as T;
}

export default function Overview({ sport, onOpenMarkets }: { sport: Sport; onOpenMarkets: () => void }) {
  const reduceMotion = useReducedMotion();
  const [data, setData] = useState<DashboardData>({ errors: [], checkedAt: 0 });
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    const results = await Promise.allSettled([
      json<MarketData>(`/api/markets?sport=${sport}`),
      json<Record<Sport, Scan>>('/api/scans'),
      json<{ games: Array<unknown> }>(`/api/games?sport=${sport}`),
      json<Metrics>('/api/metrics'),
    ]);
    const errors: string[] = [];
    results.forEach((result, index) => {
      if (result.status === 'rejected') errors.push(['Markets', 'Model scan', 'Schedule', 'Evaluation'][index]);
    });
    setData({
      markets: results[0].status === 'fulfilled' ? results[0].value : undefined,
      scan: results[1].status === 'fulfilled' ? results[1].value[sport] : undefined,
      games: results[2].status === 'fulfilled' ? results[2].value.games : undefined,
      metrics: results[3].status === 'fulfilled' ? results[3].value : undefined,
      errors,
      checkedAt: Date.now(),
    });
    setLoading(false);
  }, [sport]);

  useEffect(() => {
    let active = true;
    const initial = window.setTimeout(() => { if (active) void load(); }, 0);
    const timer = window.setInterval(() => { if (active) void load(); }, 30_000);
    return () => { active = false; window.clearTimeout(initial); window.clearInterval(timer); };
  }, [load]);

  const refresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const kalshi = data.markets?.sources.kalshi;
  const linkedProps = Number(kalshi?.coverage?.prop_linked_markets ?? 0);
  const twoSided = Number(kalshi?.coverage?.prop_two_sided_quote_markets ?? 0);
  const current = marketFreshness(data.markets?.captured_at, data.checkedAt) === 'current';
  const cards = useMemo(() => [
    { label: 'Games observed', value: data.games?.length ?? null, note: `${sport.toUpperCase()} schedule window`, tone: 'blue' },
    { label: 'Kalshi player props', value: kalshi ? linkedProps : null, note: kalshi ? `${twoSided} with two-sided quotes` : 'No market capture', tone: 'violet' },
    { label: 'Model estimates', value: data.scan?.model_estimates ?? null, note: data.scan?.label ?? 'No model scan', tone: data.scan?.state === 'complete' ? 'green' : 'amber' },
    { label: 'Evaluation sample', value: data.metrics?.sample_size ?? null, note: data.metrics ? `${data.metrics.pending_count} pending · ${data.metrics.settled_count} settled` : 'No metrics snapshot', tone: 'slate' },
  ], [data, kalshi, linkedProps, sport, twoSided]);

  return (
    <motion.section className={styles.overview} initial={reduceMotion ? false : { opacity: 0 }} animate={{ opacity: 1 }}>
      <header className={styles.hero}>
        <div>
          <div className={styles.kicker}>
            <span className={`${styles.liveDot} ${current ? styles.live : ''}`} />
            {current ? 'Current market observation' : 'Last published observation'}
          </div>
          <h1>{sport.toUpperCase()} intelligence,<br /><span>with the evidence attached.</span></h1>
          <p>Current coverage, model state, and evaluation are shown separately so an unavailable source never masquerades as a zero.</p>
        </div>
        <div className={styles.heroActions}>
          <button type="button" className={styles.refresh} onClick={refresh} disabled={refreshing}>
            <RefreshCw size={16} className={refreshing ? styles.spinning : undefined} />
            Refresh
          </button>
          <button type="button" className={styles.primary} onClick={onOpenMarkets}>
            Explore markets <ArrowUpRight size={17} />
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
                  <div><span>Evidence state</span><h2>Why some metrics are blank</h2></div>
                  <CircleAlert size={20} />
                </div>
                <div className={styles.truthList}>
                  <div><span>01</span><p><strong>Outcome metrics need final results.</strong> {data.metrics?.pending_count ?? 'Recorded'} predictions are pending settlement, so ROI and hit rate are intentionally withheld.</p></div>
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
