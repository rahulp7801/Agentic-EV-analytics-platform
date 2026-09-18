'use client';
import Link from 'next/link';
import type {Sport} from '@/lib/types';
import styles from './TerminalChrome.module.css';
export default function TopBar({sport,onSportChange}:{sport:Sport;onSportChange:(sport:Sport)=>void}) {
  return <header className={styles.deskHeader}><Link href="/" aria-label="Quant home">Quant<span>Decision desk</span></Link><div className={styles.leagueSwitch} aria-label="League">{(['nfl','nba'] as Sport[]).map(option=><button key={option} type="button" aria-pressed={sport===option} onClick={()=>onSportChange(option)}>{option.toUpperCase()}</button>)}</div><span className={styles.deskMode}>Read-only research</span></header>;
}
