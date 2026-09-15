'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { ArrowDownRight, ArrowRight, ArrowUpRight, Database, Eye, Radar, ShieldCheck } from 'lucide-react';
import { LazyMotion, MotionConfig, domAnimation, m, useReducedMotion, useScroll, useTransform } from 'motion/react';
import styles from './LandingPage.module.css';

type LeagueScan = {
  state: string;
  label: string;
  updated_at: string | null;
  quotes: number;
  selections: number;
  model_requests: number;
  model_estimates: number;
  unresolved_selections: number;
  missing_estimates: number;
};

type ScanResponse = Partial<Record<'nfl' | 'nba', LeagueScan>>;

const process = [
  { number: '01', title: 'Observe', copy: 'Timestamped market snapshots enter with source and identity evidence.' },
  { number: '02', title: 'Estimate', copy: 'Sport-specific models use only history available before the event cutoff.' },
  { number: '03', title: 'Compare', copy: 'Exact lines meet across books, Kalshi, and available fantasy boards.' },
  { number: '04', title: 'Verify', copy: 'Fees, freshness, settlement rules, and uncertainty decide what survives.' },
];

const paths = [
  'M48 90 C150 90 144 212 270 212 S390 132 502 132',
  'M48 212 C164 212 156 132 270 132 S398 212 502 212',
  'M48 334 C170 334 156 252 270 252 S388 292 502 292',
];

function LiveReadout() {
  const [scans, setScans] = useState<ScanResponse | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/scans', { cache: 'no-store', signal: controller.signal })
      .then(response => response.ok ? response.json() : Promise.reject(new Error('scan unavailable')))
      .then((body: ScanResponse) => setScans(body))
      .catch(() => {
        if (!controller.signal.aborted) setScans({});
      });
    return () => controller.abort();
  }, []);

  const active = useMemo(() => {
    const rows = Object.entries(scans ?? {}) as Array<['nfl' | 'nba', LeagueScan]>;
    return rows
      .filter(([, scan]) => scan?.updated_at)
      .sort((left, right) => Date.parse(right[1].updated_at ?? '') - Date.parse(left[1].updated_at ?? ''))[0];
  }, [scans]);

  return (
    <div className={styles.readout} aria-live="polite">
      <div className={styles.readoutHeader}>
        <span className={styles.pulse} />
        <span>Latest verified pipeline state</span>
        <span>{active?.[0].toUpperCase() ?? 'SYNC'}</span>
      </div>
      {scans === null ? (
        <div className={styles.readoutLoading}>Reading the evidence ledger…</div>
      ) : active ? (
        <>
          <div className={styles.readoutStatus}>{active[1].label}</div>
          <div className={styles.readoutGrid}>
            <div><span>Quotes</span><strong>{active[1].quotes.toLocaleString()}</strong></div>
            <div><span>Selections</span><strong>{active[1].selections.toLocaleString()}</strong></div>
            <div><span>Estimates</span><strong>{active[1].model_estimates.toLocaleString()}</strong></div>
            <div><span>Unresolved</span><strong>{active[1].unresolved_selections.toLocaleString()}</strong></div>
          </div>
        </>
      ) : (
        <div className={styles.readoutLoading}>Live scan evidence is currently unavailable.</div>
      )}
    </div>
  );
}

function MarketTopology({ reduceMotion }: { reduceMotion: boolean }) {
  return (
    <div className={styles.topology}>
      <div className={styles.topologyMeta}>
        <span>Market topology / 001</span>
        <span>Read only</span>
      </div>
      <svg viewBox="0 0 550 390" role="img" aria-label="Sportsbooks, prediction markets, and fantasy boards flow through an evidence model">
        <defs>
          <filter id="landing-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="5" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>
        {paths.map((path, index) => (
          <m.path
            key={path}
            d={path}
            className={styles.flowPath}
            initial={false}
            animate={reduceMotion
              ? { pathLength: 1, opacity: 1 }
              : { pathLength: [0, 1], opacity: [0.25, 1] }}
            transition={{ duration: 1.3, delay: 0.25 + index * 0.13, ease: [0.22, 1, 0.36, 1] }}
          />
        ))}
        <g className={styles.sourceNodes}>
          <circle cx="48" cy="90" r="6" /><circle cx="48" cy="212" r="6" /><circle cx="48" cy="334" r="6" />
        </g>
        <g className={styles.destinationNodes}>
          <circle cx="502" cy="132" r="7" /><circle cx="502" cy="212" r="7" /><circle cx="502" cy="292" r="7" />
        </g>
        <m.g
          className={styles.modelNode}
          initial={false}
          animate={reduceMotion ? { scale: 1, opacity: 1 } : { scale: [0.8, 1], opacity: [0.4, 1] }}
          transition={{ type: 'spring', stiffness: 130, damping: 18, delay: 0.6 }}
          style={{ transformOrigin: '270px 212px' }}
        >
          <circle cx="270" cy="212" r="60" />
          <circle cx="270" cy="212" r="42" />
          <circle cx="270" cy="212" r="7" filter="url(#landing-glow)" />
        </m.g>
        <g className={styles.svgLabels}>
          <text x="30" y="70">BOOKS</text><text x="30" y="192">KALSHI</text><text x="30" y="314">FANTASY</text>
          <text x="472" y="112">PRICE</text><text x="472" y="192">EDGE</text><text x="472" y="272">PROOF</text>
          <text x="239" y="216">MODEL</text>
        </g>
      </svg>
      <div className={styles.topologyFoot}>
        <span>Evidence in</span><span>Decision support out</span>
      </div>
    </div>
  );
}

export default function LandingPage() {
  const reduceMotion = Boolean(useReducedMotion());
  const { scrollYProgress } = useScroll();
  const drift = useTransform(scrollYProgress, [0, 0.45], [0, reduceMotion ? 0 : 110]);

  return (
    <MotionConfig reducedMotion="user" transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}>
      <LazyMotion features={domAnimation} strict>
        <div className={styles.page}>
          <header className={styles.nav}>
            <Link className={styles.brand} href="/" aria-label="QUANT home">
              <span>Q</span>
              <strong>QUANT</strong>
              <small>Market intelligence</small>
            </Link>
            <nav aria-label="Landing navigation">
              <a href="#method">Method</a>
              <a href="#integrity">Integrity</a>
              <Link className={styles.navCta} href="/terminal">Open terminal <ArrowUpRight size={15} aria-hidden="true" /></Link>
            </nav>
          </header>

          <main>
            <section className={styles.hero}>
              <div className={styles.heroIndex}>
                <span>01—04</span>
                <span>NBA / NFL</span>
                <span>Pacific time</span>
              </div>
              <m.div className={styles.heroCopy} style={{ y: drift }}>
                <m.p
                  className={styles.eyebrow}
                  initial={false}
                  animate={reduceMotion ? undefined : { opacity: [0.45, 1], y: [16, 0] }}
                >
                  A research instrument for fragmented sports markets
                </m.p>
                <h1>
                  <m.span initial={false} animate={reduceMotion ? undefined : { y: ['105%', '0%'] }} transition={{ delay: 0.05 }}>Markets</m.span>
                  <m.span className={styles.titleAccent} initial={false} animate={reduceMotion ? undefined : { y: ['105%', '0%'] }} transition={{ delay: 0.13 }}>disagree.</m.span>
                </h1>
                <m.div
                  className={styles.heroBottom}
                  initial={false}
                  animate={reduceMotion ? undefined : { opacity: [0, 1] }}
                  transition={{ delay: 0.45 }}
                >
                  <p>QUANT maps where sportsbook prices, prediction markets, and player projections diverge—then shows the evidence that made the comparison possible.</p>
                  <Link className={styles.primaryCta} href="/terminal">
                    Enter the live terminal <ArrowRight size={18} />
                  </Link>
                </m.div>
              </m.div>
              <m.div
                className={styles.heroVisual}
                initial={false}
                animate={reduceMotion ? undefined : { opacity: [0, 1], x: [40, 0] }}
                transition={{ delay: 0.2, duration: 0.8 }}
              >
                <MarketTopology reduceMotion={reduceMotion} />
                <LiveReadout />
              </m.div>
              <a className={styles.scrollCue} href="#method">
                Follow the signal <ArrowDownRight size={16} />
              </a>
            </section>

            <section className={styles.statement} id="method">
              <div className={styles.statementRail} aria-hidden="true">
                <span>Observe</span><span>Price</span><span>Test</span><span>Verify</span>
              </div>
              <m.div
                className={styles.statementCopy}
                initial={false}
                whileInView={reduceMotion ? undefined : { opacity: [0.62, 1], y: [36, 0] }}
                viewport={{ once: true, amount: 0.45 }}
              >
                <span className={styles.sectionNumber}>02</span>
                <h2>One surface.<br />Every disagreement.</h2>
                <p>The useful signal is rarely a single number. It is the relationship between price, probability, time, rules, and what the market actually offered.</p>
              </m.div>
            </section>

            <section className={styles.processSection} aria-labelledby="process-title">
              <div className={styles.sectionHeader}>
                <span id="process-title">Signal path</span>
                <span>Four gates / zero invented inputs</span>
              </div>
              <div className={styles.processGrid}>
                {process.map((step, index) => (
                  <m.article
                    key={step.number}
                    className={styles.processCard}
                    initial={false}
                    whileInView={reduceMotion ? undefined : { opacity: [0.55, 1], y: [24, 0] }}
                    viewport={{ once: true, amount: 0.5 }}
                    transition={{ delay: index * 0.08 }}
                  >
                    <span>{step.number}</span>
                    <h3>{step.title}</h3>
                    <p>{step.copy}</p>
                    <ArrowDownRight aria-hidden="true" />
                  </m.article>
                ))}
              </div>
            </section>

            <section className={styles.integrity} id="integrity">
              <div className={styles.integrityIntro}>
                <span className={styles.sectionNumber}>03</span>
                <p className={styles.kicker}>Built for the moment before a decision</p>
                <h2>Make uncertainty visible.</h2>
                <p className={styles.integrityLead}>A polished number can still be wrong. QUANT keeps source health, sample depth, fee assumptions, freshness, and settlement uncertainty attached to every result.</p>
              </div>
              <div className={styles.integrityGrid}>
                <article className={styles.integrityCard}>
                  <Eye />
                  <span>01</span>
                  <h3>Observable</h3>
                  <p>Every public result carries enough context to understand what was seen and when.</p>
                </article>
                <article className={`${styles.integrityCard} ${styles.cardDark}`}>
                  <Database />
                  <span>02</span>
                  <h3>Reproducible</h3>
                  <p>Immutable quote evidence and model lineage make later evaluation possible.</p>
                </article>
                <article className={`${styles.integrityCard} ${styles.cardSignal}`}>
                  <Radar />
                  <span>03</span>
                  <h3>Current</h3>
                  <p>Stale observations leave the opportunity surface instead of lingering as leads.</p>
                </article>
                <article className={styles.integrityCard}>
                  <ShieldCheck />
                  <span>04</span>
                  <h3>Read only</h3>
                  <p>The system analyzes and backtests. It does not place orders.</p>
                </article>
              </div>
            </section>

            <section className={styles.finalCta}>
              <div className={styles.finalMark} aria-hidden="true">Q</div>
              <div>
                <span className={styles.sectionNumber}>04</span>
                <h2>Read the market<br />between the lines.</h2>
              </div>
              <Link className={styles.finalButton} href="/terminal">
                <span>Launch QUANT</span>
                <ArrowRight />
              </Link>
            </section>
          </main>

          <footer className={styles.footer}>
            <div><strong>QUANT</strong><span>Evidence before edge.</span></div>
            <div><span>Sportsbooks</span><span>Kalshi</span><span>PrizePicks</span></div>
            <div><span>Research only</span><span>© {new Date().getFullYear()}</span></div>
          </footer>
        </div>
      </LazyMotion>
    </MotionConfig>
  );
}
