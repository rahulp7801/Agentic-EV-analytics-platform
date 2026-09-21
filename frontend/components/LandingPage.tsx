'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { ArrowRight, ArrowUpRight, Check, Database, Eye, Layers3, ShieldCheck, Sparkles } from 'lucide-react';
import { motion, useReducedMotion } from 'motion/react';
import { marketFreshness, type MarketFreshness } from '@/lib/marketFreshness';
import { replicatedReceptionEvidence } from '@/lib/publicBenchmarks';
import HistoricalFlowDemo from './HistoricalFlowDemo';
import ResponsibleUse from './ResponsibleUse';
import ThemeToggle from './ThemeToggle';
import styles from './LandingPage.module.css';

type Pulse = {
  games: number | null;
  props: number | null;
  twoSided: number | null;
  capturedAt: string | null;
  freshness: MarketFreshness;
  scan: string;
  sources: {
    sportsbook: { count: number | null; label: string; observed: boolean };
    kalshi: { count: number | null; label: string; observed: boolean };
    prizepicks: { count: number | null; label: string; observed: boolean };
  };
};

const emptySources: Pulse['sources'] = {
  sportsbook: { count: null, label: 'Checking', observed: false },
  kalshi: { count: null, label: 'Checking', observed: false },
  prizepicks: { count: null, label: 'Checking', observed: false },
};

const method = [
  { icon: Eye, title: 'Observe the offer', copy: 'Capture the line, price, event, player identity, and provider timestamp as one piece of evidence.' },
  { icon: Layers3, title: 'Resolve the market', copy: 'Match the exact outcome across sportsbooks, Kalshi contracts, and projection boards.' },
  { icon: Database, title: 'Estimate honestly', copy: 'Use only history available before the event and retain the model version and uncertainty.' },
  { icon: ShieldCheck, title: 'Gate the result', copy: 'Freshness, fees, liquidity, rules, and settlement coverage decide what reaches the dashboard.' },
];

const resultPeriods = [replicatedReceptionEvidence.prior, replicatedReceptionEvidence.current];

function percent(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}

function count(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function sourceState(value: unknown) {
  const source = value && typeof value === 'object' ? value as Record<string, unknown> : {};
  const status = typeof source.status === 'string' ? source.status : 'unavailable';
  const reason = typeof source.reason === 'string' ? source.reason : null;
  const labels: Record<string, string> = {
    observed: 'Observed',
    not_requested: 'Not requested',
    unavailable: reason === 'access_denied' ? 'Access denied' : 'Unavailable',
  };
  return { count: count(source.count), label: labels[status] ?? 'Unavailable', observed: status === 'observed' };
}

function useMarketPulse() {
  const [pulse, setPulse] = useState<Pulse>({ games: null, props: null, twoSided: null, capturedAt: null, freshness: 'unavailable', scan: 'Checking model scan', sources: emptySources });

  useEffect(() => {
    const controller = new AbortController();
    const load = () => {
      Promise.allSettled([
        fetch('/api/markets?sport=nfl', { cache: 'no-store', signal: controller.signal }).then(async response => response.ok ? response.json() : Promise.reject()),
        fetch('/api/games?sport=nfl', { cache: 'no-store', signal: controller.signal }).then(async response => response.ok ? response.json() : Promise.reject()),
        fetch('/api/scans', { cache: 'no-store', signal: controller.signal }).then(async response => response.ok ? response.json() : Promise.reject()),
      ]).then(([markets, games, scans]) => {
        if (controller.signal.aborted) return;
        const market = markets.status === 'fulfilled' ? markets.value : null;
        const coverage = market?.sources?.kalshi?.coverage;
        const capturedAt = typeof market?.captured_at === 'string' ? market.captured_at : null;
        setPulse({
          games: games.status === 'fulfilled' && Array.isArray(games.value.games) ? games.value.games.length : null,
          props: count(coverage?.prop_linked_markets),
          twoSided: count(coverage?.prop_two_sided_quote_markets),
          capturedAt,
          freshness: marketFreshness(capturedAt),
          scan: scans.status === 'fulfilled' ? scans.value?.nfl?.label ?? 'Model state unavailable' : 'Model state unavailable',
          sources: {
            sportsbook: sourceState(market?.sources?.sportsbook),
            kalshi: sourceState(market?.sources?.kalshi),
            prizepicks: sourceState(market?.sources?.prizepicks),
          },
        });
      });
    };
    load();
    const timer = window.setInterval(load, 120_000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, []);

  return pulse;
}

function MarketPulse({ pulse }: { pulse: Pulse }) {
  const evidenceLabel = pulse.freshness === 'current' ? 'Current evidence'
    : pulse.freshness === 'stale' ? 'Last published evidence' : 'Evidence unavailable';
  return (
    <div className={styles.pulseCard}>
      <div className={styles.pulseHeader}><span><i data-current={pulse.freshness === 'current'} /> {evidenceLabel}</span><span>NFL</span></div>
      <div className={styles.pulseStats}>
        <div><strong>{pulse.games ?? '—'}</strong><span>games in view</span></div>
        <div><strong>{pulse.props ?? '—'}</strong><span>linked Kalshi props</span></div>
        <div><strong>{pulse.twoSided ?? '—'}</strong><span>two-sided markets</span></div>
      </div>
      <div className={styles.pulseFoot}>
        <span>{pulse.scan}</span>
        <span>{pulse.capturedAt ? new Date(pulse.capturedAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : 'Awaiting capture'}</span>
      </div>
    </div>
  );
}

function ProductFrame({ pulse }: { pulse: Pulse }) {
  const venueRows = [
    ['Kalshi', pulse.sources.kalshi],
    ['Sportsbooks', pulse.sources.sportsbook],
    ['PrizePicks', pulse.sources.prizepicks],
  ] as const;

  return (
    <div className={styles.productFrame}>
      <div className={styles.frameBar}><span /><span /><span /><b>linework / live markets</b></div>
      <div className={styles.frameBody}>
        <div className={styles.frameSide}>
          <div className={styles.miniBrand}>L</div>
          <span className={styles.activeNav} /><span /><span /><span /><span />
        </div>
        <div className={styles.frameMain}>
          <div className={styles.frameTitle}><span>{pulse.freshness === 'current' ? 'Current NFL coverage' : 'Last published NFL coverage'}</span><strong>Every state has a reason.</strong></div>
          <div className={styles.frameMetrics}><div><span>Games</span><b>{pulse.games ?? '—'}</b></div><div><span>Markets</span><b>{pulse.props ?? '—'}</b></div><div><span>Two-sided</span><b>{pulse.twoSided ?? '—'}</b></div></div>
          <div className={styles.frameGrid}>
            <div className={styles.frameList}><span>VENUE STATUS</span>{venueRows.map(([name, source]) => <p key={name}><i className={source.observed ? styles.green : undefined} />{name} <b>{source.label}{source.count === null ? '' : ` · ${source.count}`}</b></p>)}</div>
            <div className={styles.frameDark}><span>EVIDENCE POLICY</span><strong>No price without provenance.</strong><p>Source, time, identity, fees, and settlement logic stay attached.</p></div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function LandingPage() {
  const root = useRef<HTMLDivElement>(null);
  const reduceMotion = Boolean(useReducedMotion());
  const pulse = useMarketPulse();

  useEffect(() => {
    if (reduceMotion || !root.current) return;
    let context: { revert: () => void } | undefined;
    let cancelled = false;
    Promise.all([import('gsap'), import('gsap/ScrollTrigger')]).then(([gsapModule, triggerModule]) => {
      if (cancelled || !root.current) return;
      const gsap = gsapModule.gsap;
      const ScrollTrigger = triggerModule.ScrollTrigger;
      gsap.registerPlugin(ScrollTrigger);
      context = gsap.context(() => {
        // Motion owns the hero copy entrance; scrubbing it can cache opacity zero.
        gsap.to(`.${styles.heroOrb}`, { scrollTrigger: { trigger: `.${styles.hero}`, start: 'top top', end: 'bottom top', scrub: 0.7 }, yPercent: 30, scale: 1.22, opacity: .15, ease: 'none' });

        const story = gsap.timeline({ scrollTrigger: { trigger: `.${styles.story}`, start: 'top top', end: '+=240%', scrub: 0.65, pin: true, anticipatePin: 1 } });
        story.fromTo(`.${styles.productFrame}`, { scale: .78, rotateX: 7, y: 80 }, { scale: 1, rotateX: 0, y: 0, ease: 'power2.out' })
          .to(`.${styles.storyWord}:nth-child(1)`, { opacity: .2, y: -30 }, .65)
          .fromTo(`.${styles.storyWord}:nth-child(2)`, { opacity: .15, y: 36 }, { opacity: 1, y: 0 }, .65)
          .to(`.${styles.frameMetrics} > div`, { y: -5, stagger: .08, boxShadow: '0 16px 40px rgba(50,50,75,.12)' }, .8)
          .to(`.${styles.storyWord}:nth-child(2)`, { opacity: .2, y: -30 }, 1.45)
          .fromTo(`.${styles.storyWord}:nth-child(3)`, { opacity: .15, y: 36 }, { opacity: 1, y: 0 }, 1.45)
          .to(`.${styles.frameDark}`, { scale: 1.025, backgroundColor: '#2c2b38' }, 1.55);

        gsap.from(`.${styles.methodCard}`, { scrollTrigger: { trigger: `.${styles.methodGrid}`, start: 'top 76%' }, opacity: 0, y: 42, stagger: .1, duration: .8, ease: 'power3.out' });
        gsap.from(`.${styles.backtestDemoFrame}`, { scrollTrigger: { trigger: `.${styles.backtestDemo}`, start: 'top 72%' }, opacity: 0, duration: .7, ease: 'power3.out' });
      }, root);
    });
    return () => { cancelled = true; context?.revert(); };
  }, [reduceMotion]);

  return (
    <div className={styles.page} ref={root}>
      <header className={styles.nav}>
        <Link className={styles.brand} href="/"><span>L</span><strong>Linework</strong></Link>
            <nav aria-label="Landing navigation"><a href="#results">Results</a><a href="#platform">Platform</a><a href="#demo">Demo</a><a href="#method">Method</a><ThemeToggle /><Link href="/terminal" className={styles.navButton} aria-label="Open dashboard"><span>Open dashboard</span><ArrowUpRight size={15} /></Link></nav>
      </header>

      <main>
        <section className={styles.hero}>
          <div className={styles.heroOrb} aria-hidden="true" />
          <motion.div className={styles.heroCopy} initial={reduceMotion ? false : { opacity: 0, y: 28 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .9, ease: [.2, .8, .2, 1] }}>
            <div className={styles.eyebrow}><Sparkles size={14} /> Evidence-first sports intelligence</div>
            <h1>An edge you<br />can <span>inspect.</span></h1>
            <p>One clear view of sportsbook prices, prediction markets, player projections, and model evidence—built to show what is live, what is stale, and what is still unknown.</p>
            <div className={styles.heroActions}><a href="#demo" aria-label="Try the Week 1 demo"><span aria-hidden="true">▶</span> Try the demo <ArrowRight size={17} /></a><Link href="/terminal">Open dashboard <ArrowUpRight size={17} /></Link></div>
          </motion.div>
          <motion.div className={styles.heroPulse} initial={reduceMotion ? false : { opacity: 0, y: 35 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: .28, duration: .8 }}><MarketPulse pulse={pulse} /></motion.div>
          <div className={styles.heroFine}><span>NBA + NFL + CFB</span><span>Sportsbooks · Kalshi · PrizePicks</span><span>Pregame research only</span></div>
        </section>

        <section className={styles.results} id="results" aria-labelledby="results-title">
          <div className={styles.resultsIntro}>
            <div>
              <span>Verified retrospective performance</span>
              <h2 id="results-title">{percent(replicatedReceptionEvidence.prior.hit_rate)}.<br />Then {percent(replicatedReceptionEvidence.current.hit_rate)}.</h2>
            </div>
            <div className={styles.resultsSummary}>
              <div><ShieldCheck size={18} /><strong>Above 60% in both periods</strong></div>
              <p>The same fixed reception rule was evaluated on two separate NFL periods. Every win and loss remains in the denominator.</p>
            </div>
          </div>

          <div className={styles.resultsGrid}>
            {resultPeriods.map(period => (
              <article className={styles.resultCard} key={period.label}>
                <span>{period.label}</span>
                <strong>{percent(period.hit_rate)}</strong>
                <p>{period.correct} correct <i>/</i> {period.sample} forecasts</p>
                <dl>
                  <div><dt>Games</dt><dd>{period.game_count}</dd></div>
                  <div><dt>95% game-cluster interval</dt><dd>{percent(period.game_cluster_interval[0])}–{percent(period.game_cluster_interval[1])}</dd></div>
                </dl>
              </article>
            ))}
          </div>

          <div className={styles.resultsFoot}>
            <p><strong>Rule:</strong> at least {percent(replicatedReceptionEvidence.called_side_minimum)} probability on the called side of a fixed {replicatedReceptionEvidence.research_threshold} reception threshold, using only prior games.</p>
            <p>Retrospective directional forecasts without archived sportsbook prices. These results establish repeatable accuracy, not betting profit.</p>
            <Link href="/terminal#nfl/backtest">Inspect every forecast <ArrowUpRight size={16} /></Link>
          </div>
        </section>

        <section className={styles.story} id="platform">
          <div className={styles.storyCopy}>
            <p className={`${styles.storyWord} ${styles.wordActive}`}>See the market.</p>
            <p className={styles.storyWord}>Understand the gap.</p>
            <p className={styles.storyWord}>Keep the proof.</p>
          </div>
          <div className={styles.productWrap}><ProductFrame pulse={pulse} /></div>
        </section>

        <section className={styles.backtestDemo} id="backtest-demo">
          <div className={styles.backtestDemoIntro}><span>Try a real past-game replay</span><h2>A clear forecast.<br />A result you can check.</h2><p>See the player, direction, model evidence and verified final stat together. Compare Week 1 replays, including a miss, without leaving the card.</p></div>
          <div className={styles.backtestDemoFrame}><HistoricalFlowDemo /></div>
        </section>

        <section className={styles.method} id="method">
          <div className={styles.methodIntro}><span>How it works</span><h2>Signal without the theatre.</h2><p>The interface stays calm because the system underneath is strict. Each stage can block a result instead of filling the screen with false certainty.</p></div>
          <div className={styles.methodGrid}>
            {method.map((item, index) => {
              const Icon = item.icon;
              return <article className={styles.methodCard} key={item.title}><div><span>0{index + 1}</span><Icon /></div><h3>{item.title}</h3><p>{item.copy}</p></article>;
            })}
          </div>
        </section>

        <section className={styles.integrity}>
          <div className={styles.integrityGlow} aria-hidden="true" />
          <span>Designed for evidence</span>
          <h2>Unknown is a valid answer.</h2>
          <p>Linework does not turn missing outcomes into performance, stale quotes into opportunities, or public projections into invented payouts.</p>
          <div className={styles.checks}><span><Check /> No order execution</span><span><Check /> Immutable evidence</span><span><Check /> Explicit provider health</span></div>
        </section>

        <section className={styles.finalCta}>
          <div><span>Ready when the data is.</span><h2>Read the market<br />with context.</h2></div>
          <Link href="/terminal">Open the dashboard <ArrowUpRight /></Link>
        </section>
      </main>

      <ResponsibleUse />
      <footer className={styles.footer}><Link href="/" className={styles.brand}><span>L</span><strong>Linework</strong></Link><p>Sports market intelligence with source, time, and uncertainty attached.</p><span>Research only · {new Date().getFullYear()}</span></footer>
    </div>
  );
}
