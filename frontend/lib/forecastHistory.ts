import type {EVSignal} from './types';
import {publicGameLogs} from './publicGameLogs.ts';

/** Descriptive outcomes at this line, never a betting replay or a new forecast. */
export function forecastHistory(value:unknown,signal:EVSignal,count=20) {
  if(!Number.isSafeInteger(count) || count<1 || count>200) throw new Error('Invalid history window');
  const cutoff=signal.forecast_cutoff;
  if(!cutoff || !/^\d{4}-\d{2}-\d{2}$/.test(cutoff) || !Number.isFinite(Date.parse(cutoff))
    || new Date(`${cutoff}T00:00:00Z`).toISOString().slice(0,10)!==cutoff) throw new Error('Forecast cutoff unavailable');
  const logs=publicGameLogs(value,signal.sport)
    .filter(row=>String(row.player).toLowerCase()===signal.player.toLowerCase() && String(row.date)<cutoff)
    .sort((a,b)=>String(b.date).localeCompare(String(a.date))).slice(0,count);
  let wins=0,losses=0,ties=0,missing=0,sum=0;
  const seen=new Set<string>();
  const rows=logs.map(row=>{
    const key=`${row.date}:${row.team}:${row.opponent}`;
    if(seen.has(key)) throw new Error('Duplicate historical game');
    seen.add(key);
    const keys=signal.prop_type==='pra' ? ['points','rebounds','assists'] : [signal.prop_type];
    const values=keys.map(key=>row[key]);
    const stat=values.every(v=>typeof v==='number' && Number.isFinite(v)) ? (values as number[]).reduce((a,b)=>a+b,0) : null;
    let outcome='Missing stat';
    if(stat===null) missing++;
    else {
      sum+=stat;
      if(stat===signal.line) {ties++;outcome='Tie';}
      else if((stat>signal.line)===(signal.direction==='over')) {wins++;outcome='Matched direction';}
      else {losses++;outcome='Opposite direction';}
    }
    return {date:String(row.date),team:String(row.team),opponent:String(row.opponent),stat,outcome};
  });
  return {rows,wins,losses,ties,missing,decided:wins+losses,rate:wins+losses ? wins/(wins+losses) : null,
    mean:logs.length-missing ? sum/(logs.length-missing) : null};
}
