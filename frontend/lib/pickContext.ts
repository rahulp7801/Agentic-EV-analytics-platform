import type {EVSignal} from './types';

/** A compact summary of captured context; it never changes a probability. */
export function pickContext(signal:EVSignal) {
  const availability=signal.availability;
  if(availability?.status!=='observed' || !availability.roster_confirmed) return {
    player:'Roster and injury evidence unavailable',
    reports:'Relevant reports could not be verified',
    detail:'Open the evidence panel for the recorded source status.',
  };
  const flagged=availability.teammates.filter(row=>row.status!=='Active');
  const shown=flagged.slice(0,2).map(row=>`${row.player} (${row.status})`);
  const extra=flagged.length>shown.length ? ` and ${flagged.length-shown.length} more` : '';
  const reports=flagged.length
    ? `Reported context: ${shown.join(', ')}${extra}`
    : availability.teammates.length
      ? `${availability.teammates.length} relevant report${availability.teammates.length===1?'':'s'} checked; none flagged inactive`
      : 'No relevant teammate or opposing defender report in the capture';
  const splits=availability.context_splits?.length ?? 0;
  const tracking=signal.next_gen_stats?.sample_weeks ?? 0;
  const parts=[`${splits} historical participation comparison${splits===1?'':'s'}`];
  if(tracking) parts.push(`${tracking} prior tracking week${tracking===1?'':'s'}`);
  return {
    player:`${availability.subject_status} · ${availability.team} roster confirmed`,
    reports,
    detail:`${parts.join(' · ')}. Injury and tracking context do not add a probability boost.`,
  };
}
