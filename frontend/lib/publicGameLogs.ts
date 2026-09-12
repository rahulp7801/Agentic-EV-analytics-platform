import type { Sport } from './types';

type Row = Record<string, unknown>;
const STATS = {
  nba: ['points','rebounds','assists','threes','steals','blocks','minutes'],
  nfl: ['pass_yds','pass_tds','rush_yds','rec_yds','receptions'],
} as const;
const NONNEGATIVE = new Set(['points','rebounds','assists','threes','steals','blocks','minutes',
  'pass_tds','receptions']);

function row(value: unknown): Row {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid game log');
  return value as Row;
}

function text(value: unknown, maximum: number) {
  if (typeof value !== 'string' || !value.trim() || value.length > maximum
      || /[\u0000-\u001f]/.test(value)) throw new Error('Invalid game log');
  return value;
}

function date(value: unknown) {
  const result=text(value,10);
  const parsed=new Date(`${result}T00:00:00Z`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(result) || !Number.isFinite(parsed.valueOf())
      || parsed.toISOString().slice(0,10)!==result) {
    throw new Error('Invalid game log');
  }
  return result;
}

function gameLog(value: unknown, sport: Sport) {
  const source=row(value);
  if (source.is_home !== null && source.is_home !== undefined && typeof source.is_home !== 'boolean') {
    throw new Error('Invalid game log');
  }
  const result:Row={date:date(source.date),player:text(source.player,100),team:text(source.team,20),
    opponent:text(source.opponent,20)};
  if (typeof source.is_home === 'boolean') result.is_home=source.is_home;
  for (const key of STATS[sport]) {
    const value=source[key];
    if (value === null || value === undefined) continue;
    if (typeof value !== 'number' || !Number.isFinite(value) || Math.abs(value)>10000
        || (NONNEGATIVE.has(key) && value<0)) throw new Error('Invalid game log');
    result[key]=value;
  }
  return result;
}

/** Validate and project public historical stats without exposing future view fields. */
export function publicGameLogs(value: unknown, sport: Sport) {
  if (!Array.isArray(value) || value.length>200) throw new Error('Invalid game logs');
  return value.map(item=>gameLog(item,sport));
}
