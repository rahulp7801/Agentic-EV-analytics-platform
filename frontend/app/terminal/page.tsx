'use client';

import { useState } from 'react';
import Sidebar from '@/components/Sidebar';
import TopBar from '@/components/TopBar';
import Overview from '@/components/Overview';
import PropsAnalysis from '@/components/PropsAnalysis';
import GameLogs from '@/components/GameLogs';
import MarketWatch from '@/components/MarketWatch';
import ScanStatus from '@/components/ScanStatus';
import ParlayBuilder from '@/components/ParlayBuilder';
import KellyCalc from '@/components/KellyCalc';
import type { EVSignal, Sport } from '@/lib/types';

export default function Terminal() {
  const [view, setView] = useState('dashboard');
  const [sport, setSport] = useState<Sport>('nfl');
  const [parlayLegs, setParlayLegs] = useState<EVSignal[]>([]);

  return (
    <div className="terminal-shell">
      <TopBar />
      <div className="terminal-layout">
        <Sidebar
          activeView={view}
          onViewChange={setView}
          sport={sport}
          onSportChange={setSport}
        />
        <main className="terminal-main">
          <div className="terminal-breadcrumb" aria-label="Current workspace">
            <span>Research desk</span>
            <span aria-hidden="true">/</span>
            <span>{sport.toUpperCase()}</span>
            <span aria-hidden="true">/</span>
            <strong>{view.replace('_', ' ')}</strong>
          </div>
          <ScanStatus />
          <div className="terminal-view">
            {view === 'dashboard' && (
              <Overview sport={sport} onOpenMarkets={() => setView('arbitrage')} />
            )}
            {view === 'props' && <PropsAnalysis sport={sport} />}
            {view === 'gamelogs' && <GameLogs sport={sport} />}
            {view === 'arbitrage' && <MarketWatch sport={sport} />}
            {view === 'parlay' && (
              <ParlayBuilder
                externalLegs={parlayLegs}
                onRemoveExternal={id => setParlayLegs(previous => previous.filter(signal => signal.id !== id))}
              />
            )}
            {view === 'kelly' && <KellyCalc />}
          </div>
        </main>
      </div>
    </div>
  );
}
