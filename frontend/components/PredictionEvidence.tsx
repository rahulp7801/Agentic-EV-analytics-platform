import type {EVSignal} from '@/lib/types';
import {useEffect,useRef} from 'react';
import styles from './ResearchViews.module.css';
import PlayerPortrait from './PlayerPortrait';
import PlayerHistory from './PlayerHistory';

export const REASONS:Record<string,string>={
  availability_unavailable:'Current injury and roster evidence is unavailable or stale.',
  roster_unconfirmed:'The player could not be confirmed on either current roster.',
  player_availability_risk:'The player has a reported availability risk.',
  teammate_availability_unmodeled:'Reported teammate risks are not covered by a validated probability adjustment.',
  stale_quote:'The observed price is more than five minutes old.',
  missing_or_started_game:'The game has started or its start time is unavailable.',
  game_started:'The game has started.',
  insufficient_sample:'There are fewer than 20 historical observations.',
  no_positive_edge:'The estimate did not pass the model edge and uncertainty gates.',
};

function time(value?:string) {
  return value ? new Date(value).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'}) : 'Unavailable';
}

export default function PredictionEvidence({signal,onClose}:{signal:EVSignal;onClose:()=>void}) {
  const availability=signal.availability;
  const panel=useRef<HTMLElement>(null);
  useEffect(()=>{panel.current?.focus();},[signal.id]);
  return <section ref={panel} tabIndex={-1} className={styles.predictionEvidence} aria-label={`Why ${signal.player} was forecast`}>
    <header>
      <PlayerPortrait signal={signal} />
      <div><small>Forecast evidence</small><h2>{signal.player}</h2><p>{signal.direction} {signal.line} {signal.prop_type.replaceAll('_',' ')} · {signal.home_team} vs {signal.away_team}</p></div>
      <button type="button" className={styles.evidenceClose} onClick={onClose}>Close explanation</button>
    </header>
    <div className={styles.evidenceMetrics}>
      <div><span>Model probability</span><strong>{(signal.true_prob*100).toFixed(1)}%</strong><small>{signal.confidence_interval ? `95% interval ${(signal.confidence_interval[0]*100).toFixed(1)}–${(signal.confidence_interval[1]*100).toFixed(1)}%` : 'Uncertainty unavailable'}</small></div>
      <div><span>Price break-even</span><strong>{(signal.implied_prob*100).toFixed(1)}%</strong><small>{signal.sportsbook} · {signal.american_odds>0?'+':''}{signal.american_odds}</small></div>
      <div><span>Historical sample</span><strong>{signal.sample_size ?? '—'} games</strong><small>Mean {signal.mean_stat?.toFixed(1) ?? 'unavailable'} · before {signal.forecast_cutoff ?? 'recorded target game'}</small></div>
    </div>
    <div className={styles.evidenceColumns}>
      <div><h3>Why this estimate</h3>
        {signal.trade_plan.length ? <ul>{signal.trade_plan.map((bullet,index)=><li key={index}>{bullet}</li>)}</ul>
          : <p>This older forecast has no retained model explanation. Its sample and observed price remain visible above.</p>}
        <p><strong>{signal.gated ? 'Not recommended. ' : 'Passed current research gates. '}</strong>{signal.gated ? REASONS[signal.gate_reason ?? ''] ?? 'A model or portfolio risk gate blocked this pick.' : 'A model estimate is uncertain and is not a guarantee of an outcome.'}</p>
        <dl><div><dt>Game starts</dt><dd>{time(signal.game_start_time)}</dd></div><div><dt>Price observed</dt><dd>{time(signal.snapped_at)}</dd></div></dl>
      </div>
      <div><h3>Injuries & teammates</h3>
        {signal.player_profile && <p>Player profile: <strong>{signal.player_profile.name} · {signal.player_profile.team}{signal.player_profile.jersey ? ` · #${signal.player_profile.jersey}` : ''}{signal.player_profile.position ? ` · ${signal.player_profile.position}` : ''}</strong>. <a href={signal.player_profile.source_url} target="_blank" rel="noreferrer">Profile roster source</a> · Captured {time(signal.player_profile.captured_at)}. This presentation metadata does not update the original forecast’s availability evidence.</p>}
        <p><strong>{availability?.status==='observed' ? availability.subject_status : 'Current availability unavailable'}</strong></p>
        <p>{availability?.roster_confirmed ? `Matched to the captured ${availability.team} roster. ` : 'Roster identity is not confirmed. '}An unlisted injury does not confirm game-day participation. Final starters, minutes and snap counts are not verified here.</p>
        {availability?.status==='observed' && <>
          {availability.roster_player_name && <p>Roster name: <strong>{availability.roster_player_name}</strong>. Matched through verified player IDs. <a href={availability.identity_source_url} target="_blank" rel="noreferrer">Player ID source</a></p>}
          <p><a href={availability.source_url} target="_blank" rel="noreferrer">{availability.source_url===availability.roster_source_url ? 'Roster injury report' : 'ESPN injury report'}</a> · <a href={availability.roster_source_url} target="_blank" rel="noreferrer">Roster source</a><br />Captured {time(availability.captured_at)}</p>
          {availability.teammates.length ? <ul tabIndex={0} aria-label="Reported teammate availability" className={styles.teammateReports}>{[...availability.teammates].sort((a,b)=>Number(a.status==='Active')-Number(b.status==='Active')).map(row=><li key={row.player}><strong>{row.player}</strong><span>{row.position} · {row.status}</span><small>Reported {time(row.reported_at)}</small></li>)}</ul> : <p>No teammates listed in this captured injury report.</p>}
        </>}
        <p className={styles.evidenceLimitation}>The probability is a historical baseline. Injury and teammate reports screen recommendations; no unvalidated injury, usage or rotation boost is added.</p>
      </div>
    </div>
    <PlayerHistory key={signal.id} signal={signal} />
  </section>;
}
