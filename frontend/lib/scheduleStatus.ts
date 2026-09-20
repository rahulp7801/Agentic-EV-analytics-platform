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

function dateLabels(asOfDate:string,lookahead:number) {
  const base=new Date(`${asOfDate}T00:00:00Z`),labels=new Map<number,string>();
  for (const [offset,label] of [[-1,'Yesterday'],[0,'Today'],[1,'Tomorrow']] as const) {
    const day=new Date(base);day.setUTCDate(day.getUTCDate()+offset);
    labels.set(Number(day.toISOString().slice(0,10).replaceAll('-','')),label);
  }
  for(let offset=2;offset<=lookahead;offset++) {
    const day=new Date(base);day.setUTCDate(day.getUTCDate()+offset);
    labels.set(Number(day.toISOString().slice(0,10).replaceAll('-','')),day.toISOString().slice(0,10));
  }
  return labels;
}

function publicGames(value:unknown, asOfDate:string,lookahead:number,sourceDate=asOfDate) {
  if (!Array.isArray(value) || value.length>100) throw new Error('Invalid schedule');
  const labels=dateLabels(asOfDate,lookahead),sourceLabels=dateLabels(sourceDate,lookahead);
  const ids=new Set<string>();
  return value.map(item=>{
    if (!item || typeof item!=='object' || Array.isArray(item)) throw new Error('Invalid schedule');
    const game=item as Row, id=text(game.provider_event_id,64), date=calendar(game.date,true);
    const expectedLabel=labels.get(Number(date)),sourceLabel=sourceLabels.get(Number(date)),start=timestamp(game.game_time);
    if (ids.has(id) || !sourceLabel || game.label!==sourceLabel || typeof game.completed!=='boolean'
        || easternDay(Date.parse(start))!==date) throw new Error('Invalid schedule');
    ids.add(id);
    if(!expectedLabel) return null;
    return {home_abbr:text(game.home_abbr,10),away_abbr:text(game.away_abbr,10),
      home_name:text(game.home_name,100),away_name:text(game.away_name,100),date,
      label:expectedLabel,game_time:start,
      ...(lookahead>1 ? {provider_event_id:id,completed:game.completed} : {})};
  }).filter(item=>item!==null);
}

export function scheduleSnapshot(data: Row | null, sport:Sport, now=Date.now(),lookahead=1) {
  const today=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',
    month:'2-digit',day:'2-digit'}).format(now);
  try {
    if(lookahead!==1 && lookahead!==6) throw new Error('Invalid schedule window');
    if (!data || data.sport!==sport || (data.status!=='complete' && data.status!=='partial')
        || data.partial!==(data.status==='partial')) {
      throw new Error('Invalid schedule');
    }
    const sourceDate=calendar(data.as_of_date),previous=new Date(`${today}T00:00:00Z`);
    previous.setUTCDate(previous.getUTCDate()-1);
    const rollover=sourceDate!==today;
    const rolloverWindow=4*60*60000;
    if(rollover && (sourceDate!==previous.toISOString().slice(0,10)
        || easternDay(now-rolloverWindow)!==sourceDate.replaceAll('-',''))) throw new Error('Invalid schedule');
    const captured=timestamp(data.captured_at), age=now-Date.parse(captured);
    // Schedules change far less often than prices. Keep a same-day snapshot usable
    // across ordinary GitHub Actions scheduling delays while prices retain tighter gates.
    const maximumAge=sport==='cfb' ? 24*60*60000 : 4*60*60000;
    if (!Number.isFinite(age) || age<0 || age>maximumAge) throw new Error('Invalid schedule');
    return {status:200,body:{games:publicGames(data.games,today,lookahead,sourceDate),partial:data.status==='partial'||rollover,
      captured_at:captured}};
  } catch {
    return {status:503,body:{games:[],partial:true,error:'Schedules are temporarily unavailable.'}};
  }
}
