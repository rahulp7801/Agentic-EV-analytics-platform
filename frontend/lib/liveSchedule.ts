import {scheduleSnapshot} from './scheduleStatus.ts';
import type {Sport} from './types';

const SPORTS={nfl:'nfl',nba:'nba',cfb:'college-football'};
function row(value:unknown):Record<string,unknown> {
  if(!value || typeof value!=='object' || Array.isArray(value)) throw new Error('Invalid scoreboard');
  return value as Record<string,unknown>;
}

function scoreboardEvents(value:unknown) {
  const root=row(value);
  const events=root.events ?? row(row(root.content).sbData).events;
  if(!Array.isArray(events) || events.length>100) throw new Error('Invalid scoreboard');
  return events;
}

/** Free read-only recovery for a stale worker schedule; never supplies prices or picks. */
export async function liveSchedule(sport:Sport,now=Date.now(),lookahead:1|6=1) {
  const today=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
  const captured_at=new Date(now).toISOString();
  const days:Array<[number,string]>=[[-1,'Yesterday'],[0,'Today'],[1,'Tomorrow']];
  for(let offset=2;offset<=lookahead;offset++) {
    const day=new Date(today+'T00:00:00Z');day.setUTCDate(day.getUTCDate()+offset);
    days.push([offset,day.toISOString().slice(0,10)]);
  }
  const results=await Promise.allSettled(days.map(async ([offset,label])=>{
    const day=new Date(today+'T00:00:00Z');day.setUTCDate(day.getUTCDate()+offset);
    const date=day.toISOString().slice(0,10).replaceAll('-','');
    const response=await fetch(`https://cdn.espn.com/core/${SPORTS[sport]}/scoreboard?xhr=1&limit=100&dates=${date}`,{
      headers:{'User-Agent':'LineworkSports/1.0'},signal:AbortSignal.timeout(5000),redirect:'error',next:{revalidate:60}});
    if(!response.ok || Number(response.headers.get('content-length'))>2*1024*1024) throw new Error('Scoreboard unavailable');
    const text=await response.text();if(text.length>2*1024*1024) throw new Error('Scoreboard too large');
    const events=scoreboardEvents(JSON.parse(text));
    // NFL scoreboards may include the entire week; only retain this requested Eastern day.
    const games=events.filter(value=>{
      const event=row(value),start=Date.parse(String(event.date));
      if(typeof event.date!=='string' || !/(?:Z|[+-]\d\d:\d\d)$/.test(event.date) || !Number.isFinite(start)) throw new Error('Invalid event date');
      return new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(start).replaceAll('-','')===date;
    }).map(value=>{
      const event=row(value);
      if(!Array.isArray(event.competitions) || event.competitions.length!==1) throw new Error('Invalid competition');
      const competition=row(event.competitions[0]);
      if(!Array.isArray(competition.competitors) || competition.competitors.length!==2) throw new Error('Invalid teams');
      const teams=competition.competitors.map(row);
      const home=teams.filter(team=>team.homeAway==='home'),away=teams.filter(team=>team.homeAway==='away');
      if(home.length!==1 || away.length!==1) throw new Error('Ambiguous teams');
      const h=row(home[0].team),a=row(away[0].team);
      return {provider_event_id:event.id,home_abbr:h.abbreviation,away_abbr:a.abbreviation,
        home_name:h.displayName,away_name:a.displayName,date,label,game_time:event.date,
        completed:row(row(competition.status).type).completed};
    });
    const validated=scheduleSnapshot({sport,status:'complete',partial:false,as_of_date:today,captured_at,games},sport,now,lookahead);
    if(validated.status!==200) throw new Error('Invalid schedule');
    return games;
  }));
  const available=results.filter(result=>result.status==='fulfilled');
  if(!available.length) return scheduleSnapshot(null,sport,now,lookahead);
  const partial=available.length!==days.length;
  return scheduleSnapshot({sport,status:partial?'partial':'complete',partial,as_of_date:today,captured_at,
    games:available.flatMap(result=>result.value)},sport,now,lookahead);
}
