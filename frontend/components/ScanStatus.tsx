'use client';

import { useEffect, useState } from 'react';
import type {Sport} from '@/lib/types';
import styles from './TerminalChrome.module.css';

type Status = ReturnType<typeof import('@/lib/scanStatus').scanStatus>;

function tone(state: string) {
  if (state === 'healthy' || state === 'complete') return styles.scanGood;
  if (['degraded','stale','overdue','interrupted','failed','blocked','unknown'].includes(state)) return styles.scanWarning;
  return styles.scanQuiet;
}

export default function ScanStatus({sport}:{sport?:Sport}) {
  const [data, setData] = useState<Record<string, Status> | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const response = await fetch('/api/scans', { cache: 'no-store', signal: AbortSignal.any([controller.signal,AbortSignal.timeout(15_000)]) });
        if (!response.ok) throw new Error('Daily scan status unavailable');
        setData(await response.json());
        setError('');
      } catch {
        if (!controller.signal.aborted) {
          setData(null);
          setError('Daily scan status unavailable');
        }
      }
    }
    void load();
    const timer = setInterval(() => void load(), 60_000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, []);

  return (
    <div className={styles.scanRail} data-single-league={sport ? true : undefined} aria-live="polite" aria-label="Daily model pipeline status" tabIndex={0}>
      <span className={styles.scanRailLabel}>Pipeline</span>
      {error ? (
        <div className={`${styles.scanCard} ${styles.scanWarning}`}><strong>{error}</strong></div>
      ) : !data ? (
        <div className={`${styles.scanCard} ${styles.scanQuiet}`}><strong>Checking daily scans…</strong></div>
      ) : Object.entries(data).filter(([key])=>!sport || key===sport).map(([key, status]) => (
        <article className={`${styles.scanCard} ${tone(status.state)}`} key={key}>
          <div className={styles.scanIdentity}>
            <span>{key.toUpperCase()}</span>
            <strong>{status.label}</strong>
          </div>
          <div className={styles.scanMetrics}>
            {status.eligible !== null && status.completed !== null && (
              <span title="Game evaluations, not betting recommendations"><b>{status.completed}/{status.eligible}</b> games evaluated</span>
            )}
            {status.selections !== null && status.selections > 0 && (
              <span><b>{status.model_estimates ?? '?'}/{status.selections}</b> modeled</span>
            )}
            {status.unresolved_selections !== null && status.unresolved_selections > 0 && (
              <span><b>{status.unresolved_selections}</b> unmatched</span>
            )}
            {status.missing_estimates !== null && status.missing_estimates > 0 && (
              <span><b>{status.missing_estimates}</b> unavailable</span>
            )}
          </div>
          {status.overdue_at ? <time dateTime={status.overdue_at} title="This quote check was due, but a newer completed scan has not been recorded">Due {new Date(status.overdue_at).toLocaleString([], { month:"short", day:"numeric", hour:"2-digit", minute:"2-digit" })}</time> : status.next_refresh_at ? <time dateTime={status.next_refresh_at} title="Earliest quote check; actual collection depends on the scheduled worker and remaining credits">Due {new Date(status.next_refresh_at).toLocaleString([], { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' })}</time> : status.updated_at && <time dateTime={status.updated_at} title="Last scan check">{new Date(status.updated_at).toLocaleString([], { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' })}</time>}
        </article>
      ))}
    </div>
  );
}
