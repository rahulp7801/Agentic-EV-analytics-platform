'use client';
import { useState } from 'react';
import type { Sport } from '@/lib/types';

interface SidebarProps {
  activeView: string;
  onViewChange: (v: string) => void;
  sport: Sport;
  onSportChange: (s: Sport) => void;
}

const NAV = [
  {
    id: 'dashboard',
    label: 'EV Dashboard',
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>
        <rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>
      </svg>
    ),
  },
  {
    id: 'props',
    label: 'Prop Analysis',
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
      </svg>
    ),
  },
  {
    id: 'gamelogs',
    label: 'Game Logs',
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/>
        <line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/>
      </svg>
    ),
  },
  {
    id: 'arbitrage',
    label: 'Arbitrage',
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
      </svg>
    ),
  },
  {
    id: 'parlay',
    label: 'Parlay Builder',
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <line x1="12" y1="2" x2="12" y2="6"/><line x1="12" y1="18" x2="12" y2="22"/>
        <line x1="4.93" y1="4.93" x2="7.76" y2="7.76"/><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"/>
        <line x1="2" y1="12" x2="6" y2="12"/><line x1="18" y1="12" x2="22" y2="12"/>
        <line x1="4.93" y1="19.07" x2="7.76" y2="16.24"/><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"/>
      </svg>
    ),
  },
  {
    id: 'kelly',
    label: 'Kelly Sizer',
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
      </svg>
    ),
  },
];

export default function Sidebar({ activeView, onViewChange, sport, onSportChange }: SidebarProps) {
  return (
    <aside style={{
      width: 188, minWidth: 188,
      background: 'var(--bg-base)',
      borderRight: '1px solid var(--border-dim)',
      display: 'flex', flexDirection: 'column',
      padding: '0',
      userSelect: 'none',
    }}>
      {/* Logo */}
      <div style={{
        padding: '18px 16px 16px',
        borderBottom: '1px solid var(--border-dim)',
      }}>
        <div style={{
          fontFamily: "'Syne', sans-serif",
          fontWeight: 800, fontSize: 18,
          color: 'var(--accent-mint)',
          letterSpacing: '0.05em',
          lineHeight: 1,
        }}>
          QUANT
        </div>
        <div style={{
          fontSize: 9, color: 'var(--text-muted)',
          letterSpacing: '0.2em', textTransform: 'uppercase',
          marginTop: 3,
        }}>
          Analytics Terminal v2
        </div>
      </div>

      {/* Sport toggle */}
      <div style={{ padding: '12px 10px 10px' }}>
        <div className="section-header" style={{ marginBottom: 7 }}>Market</div>
        <div className="sport-toggle">
          <button
            className={`sport-btn ${sport === 'nba' ? 'active-nba' : ''}`}
            onClick={() => onSportChange('nba')}
          >NBA</button>
          <button
            className={`sport-btn ${sport === 'nfl' ? 'active-nfl' : ''}`}
            onClick={() => onSportChange('nfl')}
          >NFL</button>
        </div>
      </div>

      <div className="divider" style={{ margin: '0 10px' }} />

      {/* Navigation */}
      <nav style={{ padding: '10px 8px', flex: 1 }}>
        <div className="section-header" style={{ padding: '0 4px', marginBottom: 6 }}>Views</div>
        {NAV.map(item => (
          <button
            key={item.id}
            className={`nav-item ${activeView === item.id ? 'active' : ''}`}
            onClick={() => onViewChange(item.id)}
            style={{ width: '100%', marginBottom: 2 }}
          >
            {item.icon}
            <span>{item.label}</span>
          </button>
        ))}
      </nav>

      <div className="divider" style={{ margin: '0 10px' }} />

      <div style={{ padding: '10px 12px 14px', fontSize: 10, color: 'var(--text-muted)' }}>
        Estimates reflect observed quotes. Availability and eligibility can change.
      </div>
    </aside>
  );
}

