'use client';
import { useState, useEffect, useCallback } from 'react';
import type { Sport, GameLog } from '@/lib/types';
import { gameLog, overFrequency } from '@/lib/gameLogMetrics';

interface GameLogsProps { sport: Sport; }

const NBA_COLS = ['points', 'rebounds', 'assists', 'threes', 'steals', 'blocks', 'minutes'] as const;
const NFL_COLS = ['pass_yds', 'pass_tds', 'rush_yds', 'rec_yds', 'receptions'] as const;

function StatCell({ value, prop, line }: { value?: number; prop: string; line?: number }) {
  if (value === undefined) return <td style={{ color: 'var(--text-dim)' }}>—</td>;
  const beat = line !== undefined && value !== line ? value > line : undefined;
  return (
    <td style={{
      color: beat === true ? 'var(--accent-mint)' : beat === false ? 'var(--accent-red)' : 'var(--text-primary)',
      fontWeight: beat !== undefined ? 600 : 400,
      fontVariantNumeric: 'tabular-nums',
    }}>
      {value}
    </td>
  );
}

export default function GameLogs({ sport }: GameLogsProps) {
  const [playerFilter, setPlayerFilter] = useState('');
  const [activeProp, setActiveProp] = useState<string>('points');
  const [activeLine, setActiveLine] = useState<string>('30.5');
  const [selectedSport, setSelectedSport] = useState<Sport>(sport);
  const [allLogs, setAllLogs] = useState<GameLog[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(()=>{setSelectedSport(sport);},[sport]);
  useEffect(()=>{setActiveProp(selectedSport==='nba' ? 'points' : 'pass_yds');},[selectedSport]);

  const fetchLogs = useCallback(async (signal: AbortSignal) => {
    setLoading(true);
    setAllLogs([]);setError('');
    try {
      const params = new URLSearchParams({ sport: selectedSport, limit: '40' });
      if (playerFilter) params.set('player', playerFilter);
      const res = await fetch(`/api/gamelogs?${params}`, { cache: 'no-store', signal });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Game logs unavailable');
      const logs: GameLog[] = data.logs.map((row: Record<string, unknown>, i: number)=>gameLog(row,selectedSport,String(i)));
      if (signal.aborted) return;
      setAllLogs(logs);
    } catch (error) { if (!signal.aborted) {setAllLogs([]);setError(error instanceof Error ? error.message : 'Game logs unavailable');} }
    finally { if (!signal.aborted) setLoading(false); }
  }, [selectedSport, playerFilter]);

  useEffect(() => {
    const controller=new AbortController();
    const timer=setTimeout(()=>void fetchLogs(controller.signal),250);
    return ()=>{controller.abort();clearTimeout(timer);};
  }, [fetchLogs]);

  const cols = selectedSport === 'nba' ? NBA_COLS : NFL_COLS;
  const logs = allLogs;

  const numericLine=activeLine.trim()==='' ? NaN : Number(activeLine);
  const lineVal=Number.isFinite(numericLine) && numericLine>=0 ? numericLine : undefined;
  const frequency=overFrequency(logs,activeProp,lineVal);
  const hitRate=frequency?.rate ?? null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Toolbar */}
      <div style={{
        padding: '10px 14px',
        borderBottom: '1px solid var(--border-dim)',
        background: 'var(--bg-base)',
        display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0, flexWrap: 'wrap',
      }}>
        <div className="section-header">Game Log Browser</div>
        <div className="divider-v" />
        <div className="sport-toggle" style={{ width: 120 }}>
          <button className={`sport-btn ${selectedSport === 'nba' ? 'active-nba' : ''}`} onClick={() => setSelectedSport('nba')}>NBA</button>
          <button className={`sport-btn ${selectedSport === 'nfl' ? 'active-nfl' : ''}`} onClick={() => setSelectedSport('nfl')}>NFL</button>
        </div>
        <input
          className="term-input" style={{ width: 180 }}
          placeholder="Filter player..."
          value={playerFilter}
          onChange={e => setPlayerFilter(e.target.value)}
        />
        <div style={{ flex: 1 }} />

        {/* Hit rate analysis */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          background: 'var(--bg-card)', border: '1px solid var(--border-mid)',
          borderRadius: 3, padding: '5px 12px',
        }}>
          <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>ANALYZE</span>
          <select className="term-select" style={{ width: 120 }} value={activeProp} onChange={e => setActiveProp(e.target.value)}>
            {cols.map(c => <option key={c} value={c}>{c.replace('_', ' ').toUpperCase()}</option>)}
          </select>
          <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>OVER</span>
          <input
            className="term-input" style={{ width: 60 }}
            value={activeLine}
            onChange={e => setActiveLine(e.target.value)}
            placeholder="Line"
          />
          {hitRate !== null && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, paddingLeft: 8, borderLeft: '1px solid var(--border-dim)' }}>
              <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>OVER RATE</span>
              <span style={{
                fontWeight: 700, fontSize: 14,
                color: hitRate >= 0.6 ? 'var(--accent-mint)' : hitRate >= 0.5 ? 'var(--accent-amber)' : 'var(--accent-red)',
              }}>
                {(hitRate * 100).toFixed(0)}%
              </span>
              <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>({frequency?.wins}/{frequency?.decided} decided)</span>
            </div>
          )}
        </div>
      </div>

      {/* Table */}
      {error && <p role="alert" style={{padding:'0 14px'}}>{error}</p>}
      {frequency && <p style={{padding:'0 14px',fontSize:11}}>Shown rows only: {frequency.pushes} ties and {frequency.missing} missing stats excluded. This is historical frequency, not a model forecast.</p>}
      <div style={{ flex: 1, overflow: 'auto' }}>
        <table className="data-table">
          <thead>
            <tr>
              <th>Player</th>
              <th>Date</th>
              <th>Matchup</th>
              <th>H/A</th>
              <th>Result</th>
              {cols.map(c => (
                <th key={c} style={{ color: c === activeProp ? 'var(--accent-cyan)' : undefined }}>
                  {c.replace('_', ' ').toUpperCase()}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {logs.map(log => (
              <tr key={log.id}>
                <td>
                  <div style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: 12 }}>{log.player}</div>
                  <div style={{ color: 'var(--text-muted)', fontSize: 10 }}>{log.team}</div>
                </td>
                <td style={{ color: 'var(--text-secondary)', fontSize: 11 }}>{log.date}</td>
                <td style={{ color: 'var(--text-secondary)', fontSize: 11 }}>
                  {log.team} vs {log.opponent}
                </td>
                <td>
                  <span className={`badge ${log.home_away === 'home' ? 'badge-blue' : 'badge-dim'}`}>
                    {log.home_away === 'home' ? 'HOME' : log.home_away === 'away' ? 'AWAY' : '—'}
                  </span>
                </td>
                <td>
                  <span className={`badge ${log.result === 'W' ? 'badge-mint' : 'badge-red'}`}>
                    {log.result ?? '—'}
                  </span>
                </td>
                {cols.map(c => (
                  <StatCell
                    key={c}
                    value={log[c as keyof GameLog] as number | undefined}
                    prop={c}
                    line={c === activeProp ? lineVal : undefined}
                  />
                ))}
              </tr>
            ))}
            {logs.length === 0 && (
              <tr>
                <td colSpan={12} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 32 }}>
                  {loading ? 'Loading game logs…' : error ? 'Game logs unavailable' : 'No game logs found'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
