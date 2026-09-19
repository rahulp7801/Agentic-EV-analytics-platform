'use client';
import Link from 'next/link';
import {ChartNoAxesCombined,ChartSpline,ClipboardList,FlaskConical,Gauge,LayoutDashboard,Network} from 'lucide-react';
import type {Sport} from '@/lib/types';
import styles from './TerminalChrome.module.css';
interface SidebarProps {activeView:string;onViewChange:(view:string)=>void;sport:Sport;onSportChange:(sport:Sport)=>void;}
const NAV=[{id:'dashboard',label:'Picks',icon:LayoutDashboard},{id:'props',label:'Players',icon:ChartSpline},{id:'arbitrage',label:'Markets',icon:ChartNoAxesCombined},{id:'backtest',label:'Backtesting',icon:FlaskConical}];
const TOOLS=[{id:'gamelogs',label:'Game logs',icon:ClipboardList},{id:'parlay',label:'Scenario lab',icon:Network},{id:'kelly',label:'Stake calculator',icon:Gauge}];
export default function Sidebar({activeView,onViewChange,sport}:SidebarProps) {
  const button=(item:typeof NAV[number])=>{const Icon=item.icon;return <button key={item.id} type="button" className={activeView===item.id ? styles.sideNavActive : undefined} aria-current={activeView===item.id ? 'page' : undefined} onClick={event=>{onViewChange(item.id);event.currentTarget.closest('details')?.removeAttribute('open');}}><Icon aria-hidden="true" /><span>{item.label}</span></button>;};
  return <aside className={styles.sidebar}><Link className={styles.terminalBrand} href="/" aria-label="Return to Linework home"><span>L</span><div><strong>Linework</strong><small>Player prop desk</small></div></Link>
    <nav className={styles.sideNav} aria-label="Research views">{(sport==='cfb' ? NAV.filter(item=>['dashboard','props','arbitrage'].includes(item.id)) : NAV).map(button)}{sport!=='cfb' && <details className={styles.advancedNav}><summary>More tools</summary><div>{TOOLS.map(button)}</div></details>}</nav>
    <div className={styles.sidebarFoot}><span>Evidence before action</span><p>Recheck the exact line and price with the book. No orders are placed here.</p></div></aside>;
}
