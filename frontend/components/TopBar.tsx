'use client';
import { useEffect, useState } from 'react';

export default function TopBar() {
  const [time, setTime] = useState('');
  const [date, setDate] = useState('');

  useEffect(() => {
    const update = () => {
      const now = new Date();
      setTime(now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }));
      setDate(now.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }));
    };
    update();
    const t = setInterval(update, 1000);
    return () => clearInterval(t);
  }, []);

  const [signals, setSignals] = useState<{ player: string; prop_type: string; line: number; ev_pct: number; direction: string; sport: string; gated?: boolean }[]>([]);
  useEffect(() => {
    fetch('/api/signals', { cache: 'no-store' }).then(r => r.json()).then(d => setSignals((d.signals || []).filter((s: {gated?: boolean}) => !s.gated))).catch(() => {});
  }, []);
  const tickerItems = [...signals, ...signals];

  return (
    <div style={{
      height: 36, minHeight: 36,
      background: 'var(--bg-surface)',
      borderBottom: '1px solid var(--border-dim)',
      display: 'flex', alignItems: 'stretch',
      overflow: 'hidden',
    }}>
      {/* Left: status */}
      <div className="topbar-item" style={{ gap: 8, minWidth: 160 }}>
        <span className="live-dot" style={{ width: 8, height: 8 }} />
        <span style={{ color: 'var(--accent-mint)', fontSize: 10, fontWeight: 600, letterSpacing: '0.1em' }}>
          MARKET ESTIMATES
        </span>
      </div>

      {/* Ticker — real signals */}
      <div className="ticker-wrap" style={{ flex: 1, borderRight: '1px solid var(--border-dim)', borderLeft: '1px solid var(--border-dim)' }}>
        <div className="ticker-inner" style={{ height: '100%', display: 'flex', alignItems: 'center', gap: 0 }}>
          {tickerItems.length === 0 ? (
            <span style={{ color: 'var(--text-dim)', fontSize: 10, padding: '0 20px' }}>Waiting for fresh market estimates</span>
          ) : tickerItems.map((item, i) => (
            <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 8, paddingRight: 32 }}>
              <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>{item.sport?.toUpperCase()}</span>
              <span style={{ color: 'var(--text-secondary)', fontSize: 10 }}>
                {item.player?.split(' ').pop()?.toUpperCase()} {item.prop_type?.toUpperCase()} {item.direction === 'under' ? 'U' : 'O'}{item.line}
              </span>
              <span style={{ color: 'var(--accent-mint)', fontSize: 10, fontWeight: 600 }}>
                +{(item.ev_pct * 100).toFixed(1)}pp
              </span>
              <span style={{ color: 'var(--border-bright)', fontSize: 10 }}>·</span>
            </span>
          ))}
        </div>
      </div>

      {/* Right: stats + time */}
      <div className="topbar-item" style={{ gap: 6 }}>
        <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>SIGNALS</span>
        <span style={{ color: 'var(--accent-mint)', fontSize: 11, fontWeight: 600 }}>
          {signals.length}
        </span>
      </div>
      <div className="topbar-item" style={{ gap: 8, borderRight: 'none' }}>
        <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>{date}</span>
        <span style={{ color: 'var(--text-primary)', fontSize: 11, fontWeight: 500, fontVariantNumeric: 'tabular-nums' }}>
          {time}
        </span>
      </div>
    </div>
  );
}
