import type { Sport } from './types';

type Row = Record<string,unknown>;

function text(value:unknown, maximum:number) {
  if (typeof value!=='string' || !value.trim() || value.length>maximum
      || /[\u0000-\u001f]/.test(value)) throw new Error('Invalid schedule');
  return value;
}

function timestamp(value:unknown) {
  const result=text(value,64);
  if (!/([zZ]|[+-]\d\d:\d\d)$/.test(result) || !Number.isFinite(Date.parse(result))) {
    throw new Error('Invalid schedule');
  }
  return result;
}

function calendar(value:unknown, compact=false) {
  const result=text(value,compact ? 8 : 10);
  const match=compact ? /^\d{8}$/.test(result) : /^\d{4}-\d{2}-\d{2}$/.test(result);
  const expanded=compact ? `${result.slice(0,4)}-${result.slice(4,6)}-${result.slice(6,8)}` : result;
  const parsed=new Date(`${expanded}T00:00:00Z`);
  if (!match || !Number.isFinite(parsed.valueOf()) || parsed.toISOString().slice(0,10)!==expanded) {
    throw new Error('Invalid schedule');
  }
  return result;
}

function easternDay(value:number) {
  const parts=new Intl.DateTimeFormat('en',{timeZone:'America/New_York',year:'numeric',
    month:'2-digit',day:'2-digit'}).formatToParts(value);
  return ['year','month','day'].map(type=>parts.find(part=>part.type===type)?.value).join('');
}

function publicGames(value:unknown, asOfDate:string) {
  if (!Array.isArray(value) || value.length>100) throw new Error('Invalid schedule');
  const base=new Date(`${asOfDate}T00:00:00Z`);
  const labels=new Map<number,string>();
  for (const [offset,label] of [[-1,'Yesterday'],[0,'Today'],[1,'Tomorrow']] as const) {
    const day=new Date(base);day.setUTCDate(day.getUTCDate()+offset);
    labels.set(Number(day.toISOString().slice(0,10).replaceAll('-','')),label);
  }
  const ids=new Set<string>();
  return value.map(item=>{
    if (!item || typeof item!=='object' || Array.isArray(item)) throw new Error('Invalid schedule');
    const game=item as Row, id=text(game.provider_event_id,64), date=calendar(game.date,true);
    const expectedLabel=labels.get(Number(date)), start=timestamp(game.game_time);
    if (ids.has(id) || !expectedLabel || game.label!==expectedLabel || typeof game.completed!=='boolean'
        || easternDay(Date.parse(start))!==date) throw new Error('Invalid schedule');
    ids.add(id);
    return {home_abbr:text(game.home_abbr,10),away_abbr:text(game.away_abbr,10),
      home_name:text(game.home_name,100),away_name:text(game.away_name,100),date,
      label:expectedLabel,game_time:start};
  });
}

export function scheduleSnapshot(data: Row | null, sport:Sport, now=Date.now()) {
  const today=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',
    month:'2-digit',day:'2-digit'}).format(now);
  try {
    if (!data || data.sport!==sport || (data.status!=='complete' && data.status!=='partial')
        || data.partial!==(data.status==='partial') || calendar(data.as_of_date)!==today) {
      throw new Error('Invalid schedule');
    }
    const captured=timestamp(data.captured_at), age=now-Date.parse(captured);
    if (!Number.isFinite(age) || age<0 || age>90*60000) throw new Error('Invalid schedule');
    return {status:200,body:{games:publicGames(data.games,today),partial:data.status==='partial',
      captured_at:captured}};
  } catch {
    return {status:503,body:{games:[],partial:true,error:'Schedules are temporarily unavailable.'}};
  }
}
