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
import type { EVSignal, Sport } from '@/lib/types';

export default function Terminal() {
  const [view, setView] = useState('dashboard');
  const [sport, setSport] = useState<Sport>('nba');
  const [parlayLegs, setParlayLegs] = useState<EVSignal[]>([]);

  const addToParlay = (signal: EVSignal) =>
    setParlayLegs(previous => previous.some(item => item.id === signal.id)
      ? previous
      : [...previous, signal]);

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
              <EVDashboard
                sport={sport}
                onAddToParlay={addToParlay}
                parlayIds={new Set(parlayLegs.map(signal => signal.id))}
              />
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
