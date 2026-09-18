'use client';

import { useEffect, useState } from 'react';
import Sidebar from '@/components/Sidebar';
import TopBar from '@/components/TopBar';
import Overview from '@/components/Overview';
import PropsAnalysis from '@/components/PropsAnalysis';
import GameLogs from '@/components/GameLogs';
import MarketWatch from '@/components/MarketWatch';
import ScanStatus from '@/components/ScanStatus';
import ParlayBuilder from '@/components/ParlayBuilder';
import KellyCalc from '@/components/KellyCalc';
import BacktestLab from '@/components/BacktestLab';
import type { EVSignal, Sport } from '@/lib/types';
import { parseTerminalHash, terminalHash, type TerminalView } from '@/lib/terminalRoute';

export default function TerminalApp() {
  const [view, setView] = useState<TerminalView>('dashboard');
  const [sport, setSport] = useState<Sport>('nfl');
  const [player,setPlayer]=useState('');
  const [parlayLegs, setParlayLegs] = useState<EVSignal[]>([]);

  useEffect(() => {
    const syncLocation = () => {
      const location = parseTerminalHash(window.location.hash);
      if (location) {
        setSport(location.sport);
        setView(location.view);
      }
    };
    syncLocation();
    window.addEventListener('hashchange', syncLocation);
    return () => window.removeEventListener('hashchange', syncLocation);
  }, []);

  const changeView = (nextView: string) => {
    setPlayer('');
    const resolved = nextView as TerminalView;
    setView(resolved);
    window.location.hash = terminalHash(sport, resolved);
  };

  const changeSport = (nextSport: Sport) => {
    setPlayer('');
    setSport(nextSport);
    window.location.hash = terminalHash(nextSport, view);
  };

  return (
    <div className="terminal-shell">
      <TopBar sport={sport} onSportChange={changeSport} />
      <div className="terminal-layout">
        <Sidebar
          activeView={view}
          onViewChange={changeView}
          sport={sport}
          onSportChange={changeSport}
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
              <Overview key={sport} sport={sport} onOpenMarkets={() => changeView('arbitrage')} onOpenPlayers={name=>{changeView('props');setPlayer(name ?? '');}} />
            )}
            {view === 'props' && <PropsAnalysis key={sport+player} sport={sport} initialPlayer={player} />}
            {view === 'gamelogs' && <GameLogs key={sport} sport={sport} />}
            {view === 'arbitrage' && <MarketWatch sport={sport} />}
            {view === 'backtest' && <BacktestLab sport={sport} />}
            {view === 'parlay' && (
              <ParlayBuilder
                sport={sport}
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
