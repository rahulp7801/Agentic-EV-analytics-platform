import type { GameLog, Sport } from './types';

export function gameLog(row: Record<string, unknown>, sport: Sport, id: string): GameLog {
  const result: GameLog = {id, sport, player:String(row.player ?? ''), team:String(row.team ?? ''),
    opponent:String(row.opponent ?? ''), date:String(row.date ?? ''),
    home_away:row.is_home === true ? 'home' : row.is_home === false ? 'away' : undefined};
  for (const key of ['points','rebounds','assists','threes','steals','blocks','minutes',
    'pass_yds','pass_tds','rush_yds','rec_yds','receptions'] as const) {
    const raw=row[key];
    const value=(typeof raw==='number' || (typeof raw==='string' && raw.trim()!=='')) ? Number(raw) : NaN;
    if (Number.isFinite(value)) result[key]=value;
  }
  if (row.result==='W' || row.result==='L') result.result=row.result;
  return result;
}

export function overFrequency(logs: GameLog[], prop: string, line: number | undefined) {
  let wins=0,losses=0,pushes=0,missing=0;
  if (line===undefined || !Number.isFinite(line) || line<0) return null;
  for (const log of logs) {
    const value=log[prop as keyof GameLog];
    if (typeof value!=='number' || !Number.isFinite(value)) missing++;
    else if (value>line) wins++;
    else if (value<line) losses++;
    else pushes++;
  }
  return {wins,losses,pushes,missing,decided:wins+losses,rate:wins+losses ? wins/(wins+losses) : null};
}
