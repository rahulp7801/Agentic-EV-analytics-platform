import type { ModelSport } from './types';

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
  if (!/^\d{4}-\d{2}-\d{2}$/.test(result) || Number(result.slice(0,4))<1 || !Number.isFinite(parsed.valueOf())
      || parsed.toISOString().slice(0,10)!==result) {
    throw new Error('Invalid game log');
  }
  return result;
}

function gameLog(value: unknown, sport: ModelSport) {
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
export function publicGameLogs(value: unknown, sport: ModelSport) {
  if (!Array.isArray(value) || value.length>200) throw new Error('Invalid game logs');
  return value.map(item=>gameLog(item,sport));
}

/** Bound historical queries before constructing parameterized SQL. */
export function gameLogRequest(params:URLSearchParams) {
  const sport=params.get('sport') ?? 'nba';
  const rawPlayer=params.get('player') ?? '';
  const player=rawPlayer.trim();
  const limit=params.get('limit') ?? '40';
  const exact=params.get('exact') ?? '0';
  const before=params.get('before');
  if(!['nba','nfl'].includes(sport) || rawPlayer!==player || player.normalize('NFC')!==player
    || (player!=='' && !/^[\p{L}\p{M}.'’ -]{1,80}$/u.test(player))
    || !/^[0-9]{1,3}$/.test(limit) || Number(limit)<1 || Number(limit)>200 || !['0','1'].includes(exact)
    || (exact==='1' && !player)) throw new Error('Invalid game-log request');
  return {sport:sport as ModelSport,player,limit:Number(limit),exact:exact==='1',
    before:before===null ? null : date(before)};
}
