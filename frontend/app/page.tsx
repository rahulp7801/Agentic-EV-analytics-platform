'use client';
import { useState } from 'react';
import Sidebar from '@/components/Sidebar';
import TopBar from '@/components/TopBar';
import EVDashboard from '@/components/EVDashboard';
import PropsAnalysis from '@/components/PropsAnalysis';
import GameLogs from '@/components/GameLogs';
import MarketWatch from '@/components/MarketWatch';
import ScanStatus from '@/components/ScanStatus';
import ParlayBuilder from '@/components/ParlayBuilder';
import KellyCalc from '@/components/KellyCalc';
import type { Sport } from '@/lib/types';

export default function Home() {
  const [view, setView] = useState('dashboard');
  const [sport, setSport] = useState<Sport>('nba');
  const [parlayLegs, setParlayLegs] = useState<import('@/lib/types').EVSignal[]>([]);

  const addToParlay = (s: import('@/lib/types').EVSignal) =>
    setParlayLegs(prev => prev.some(x => x.id === s.id) ? prev : [...prev, s]);

  return (
    <div className="grid-bg" style={{
      display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden',
    }}>
      {/* Top ticker bar */}
      <TopBar />

      {/* Main layout */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <Sidebar
          activeView={view}
          onViewChange={setView}
          sport={sport}
          onSportChange={setSport}
        />

        {/* Content area */}
        <main style={{
          flex: 1,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          background: 'var(--bg-base)',
        }}>
          {/* Breadcrumb */}
          <div style={{
            padding: '6px 14px',
            borderBottom: '1px solid var(--border-dim)',
            display: 'flex', alignItems: 'center', gap: 8,
            background: 'var(--bg-void)',
            flexShrink: 0,
          }}>
            <span style={{ color: 'var(--text-dim)', fontSize: 10 }}>QUANT</span>
            <span style={{ color: 'var(--text-dim)', fontSize: 10 }}>›</span>
            <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>{sport.toUpperCase()}</span>
            <span style={{ color: 'var(--text-dim)', fontSize: 10 }}>›</span>
            <span style={{ color: 'var(--accent-mint)', fontSize: 10, fontWeight: 600, letterSpacing: '0.06em' }}>
              {view.toUpperCase().replace('_', ' ')}
            </span>
          </div>

          {/* View content */}
          <ScanStatus />
          <div style={{ flex: 1, overflow: 'hidden' }}>
            {view === 'dashboard' && <EVDashboard sport={sport} onAddToParlay={addToParlay} parlayIds={new Set(parlayLegs.map(s => s.id))} />}
            {view === 'props'     && <PropsAnalysis sport={sport} />}
            {view === 'gamelogs' && <GameLogs sport={sport} />}
            {view === 'arbitrage' && <MarketWatch sport={sport} />}
            {view === 'parlay'    && <ParlayBuilder externalLegs={parlayLegs} onRemoveExternal={(id) => setParlayLegs(p => p.filter(s => s.id !== id))} />}
            {view === 'kelly'     && <KellyCalc />}
          </div>
        </main>
      </div>
    </div>
  );
}
