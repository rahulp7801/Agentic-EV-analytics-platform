'use client';

import Link from 'next/link';
import { ChartNoAxesCombined, ChartSpline, ClipboardList, FlaskConical, Gauge, LayoutDashboard, Network } from 'lucide-react';
import type { Sport } from '@/lib/types';
import styles from './TerminalChrome.module.css';

interface SidebarProps {
  activeView: string;
  onViewChange: (view: string) => void;
  sport: Sport;
  onSportChange: (sport: Sport) => void;
}

const NAV = [
  { id: 'dashboard', label: 'Overview', icon: LayoutDashboard },
  { id: 'props', label: 'Player props', icon: ChartSpline },
  { id: 'gamelogs', label: 'Game logs', icon: ClipboardList },
  { id: 'arbitrage', label: 'Market gaps', icon: ChartNoAxesCombined },
  { id: 'backtest', label: 'Backtest lab', icon: FlaskConical },
  { id: 'parlay', label: 'Scenario lab', icon: Network },
  { id: 'kelly', label: 'Kelly sizing', icon: Gauge },
];

export default function Sidebar({ activeView, onViewChange, sport, onSportChange }: SidebarProps) {
  return (
    <aside className={styles.sidebar}>
      <Link className={styles.terminalBrand} href="/" aria-label="Return to QUANT home">
        <span>Q</span>
        <div><strong>QUANT</strong><small>Research terminal</small></div>
      </Link>

      <section className={styles.sportSection} aria-labelledby="sport-label">
        <span className={styles.sidebarLabel} id="sport-label">League</span>
        <div className={styles.sportControl}>
          {(['nba', 'nfl'] as Sport[]).map(option => (
            <button
              key={option}
              type="button"
              aria-pressed={sport === option}
              onClick={() => onSportChange(option)}
            >
              {option.toUpperCase()}
            </button>
          ))}
        </div>
      </section>

      <nav className={styles.sideNav} aria-label="Research views">
        <span className={styles.sidebarLabel}>Workspace</span>
        {NAV.map((item, index) => {
          const Icon = item.icon;
          const active = activeView === item.id;
          return (
            <button
              key={item.id}
              type="button"
              className={active ? styles.sideNavActive : undefined}
              aria-current={active ? 'page' : undefined}
              aria-label={item.label}
              title={item.label}
              onClick={() => onViewChange(item.id)}
            >
              <Icon aria-hidden="true" />
              <span>{item.label}</span>
              <small>{String(index + 1).padStart(2, '0')}</small>
            </button>
          );
        })}
      </nav>

      <div className={styles.sidebarFoot}>
        <span>Decision support only</span>
        <p>Quotes, eligibility, and availability can change.</p>
      </div>
    </aside>
  );
}
