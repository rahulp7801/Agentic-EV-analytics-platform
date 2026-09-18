'use client';

import { useEffect, useState } from 'react';
import type { Sport } from '@/lib/types';
import {publicSignals} from '@/lib/signalMetrics';
import styles from './TerminalChrome.module.css';

type TickerSignal = {
  player: string;
  prop_type: string;
  line: number;
  ev_pct: number;
  direction: string;
  sport: string;
  gated?: boolean;
};

export default function TopBar({ sport, onSportChange }: {
  sport: Sport;
  onSportChange: (sport: Sport) => void;
}) {
  const [time, setTime] = useState('');
  const [date, setDate] = useState('');
  const [signals, setSignals] = useState<TickerSignal[]>([]);
  const [available, setAvailable] = useState(false);
  const [recorded,setRecorded]=useState(0);
  const [players,setPlayers]=useState(0);

  useEffect(() => {
    const update = () => {
      const now = new Date();
      setTime(now.toLocaleTimeString('en-US', {
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
      }));
      setDate(now.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }));
    };
    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const response = await fetch(`/api/signals?sport=${sport}`, { cache: 'no-store', signal: controller.signal });
        if (!response.ok) throw new Error('Unavailable');
        const data = await response.json();
        if(controller.signal.aborted) return;
        const forecasts=publicSignals(data.signals).signals;
        setSignals(forecasts.filter(signal=>!signal.gated));
        setRecorded(forecasts.length);
        setPlayers(new Set(forecasts.map(signal=>signal.player)).size);
        setAvailable(true);
      } catch {
        if (!controller.signal.aborted) {
          setSignals([]);
          setRecorded(0);
          setPlayers(0);
          setAvailable(false);
        }
      }
    }
    void load();
    const timer = setInterval(() => void load(), 30_000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [sport]);

  const ticker = (hidden: boolean) => signals.map((signal, index) => (
    <span className={styles.tickerItem} key={`${hidden ? 'copy' : 'source'}-${index}`} aria-hidden={hidden || undefined}>
      <span>{signal.sport?.toUpperCase()}</span>
      <strong>{signal.player?.split(' ').pop()?.toUpperCase()} {signal.prop_type?.replace('_', ' ').toUpperCase()}</strong>
      <span>{signal.direction === 'under' ? 'U' : 'O'} {signal.line}</span>
      <em>+{(signal.ev_pct * 100).toFixed(1)}pp</em>
    </span>
  ));

  return (
    <header className={styles.topbar}>
      <div className={styles.marketState}>
        <span className={`${styles.statusDot} ${available && signals.length ? styles.statusLive : ''}`} />
        <div className={styles.marketCopy}>
          <small>Market pulse</small>
          <strong>{available ? 'Evidence connected' : 'Awaiting estimates'}</strong>
        </div>
        <div className={styles.mobileSportControl} aria-label="League">
          {(['nfl', 'nba'] as Sport[]).map(option => (
            <button key={option} type="button" aria-pressed={sport === option}
              onClick={() => onSportChange(option)}>{option.toUpperCase()}</button>
          ))}
        </div>
      </div>
      <div className={styles.tickerViewport} aria-label="Current eligible market estimates">
        {signals.length ? (
          <div className={styles.tickerTrack}>{ticker(false)}{ticker(true)}</div>
        ) : (
          <span className={styles.tickerEmpty}>{available && recorded ? `${recorded} recorded forecasts · ${players} players · No current eligible picks` : available ? `No published ${sport.toUpperCase()} forecasts` : 'Forecast refresh unavailable'}</span>
        )}
      </div>
      <div className={styles.signalCount}>
        <small>Recorded</small>
        <strong aria-label={available ? `${recorded} recorded forecasts, ${signals.length} currently eligible` : 'Forecast count unavailable'}>{available ? recorded : '—'}</strong>
      </div>
      <time className={styles.clock} dateTime={time ? new Date().toISOString() : undefined}>
        <span>{date}</span><strong>{time}</strong>
      </time>
    </header>
  );
}
