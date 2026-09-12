"""Collect bounded ESPN schedules on the worker, preserving source failures."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

SPORTS = {'nba':'basketball/nba', 'nfl':'football/nfl'}


def parse_day(data: dict, day: str, label: str) -> list[dict]:
    if not isinstance(data.get('events'),list):
        raise ValueError('Missing schedule events')
    games=[]
    for event in data['events']:
        start=datetime.fromisoformat(event['date'].replace('Z','+00:00'))
        if start.utcoffset() is None:
            raise ValueError('Schedule start must include a timezone')
        if start.astimezone(ZoneInfo('America/New_York')).strftime('%Y%m%d')!=day:
            continue  # NFL responses can contain other games from the same week.
        competition,=event['competitions']
        completed=event.get('status',{}).get('type',{}).get('completed')
        if type(completed) is not bool:
            raise ValueError('Schedule completion state is missing')
        home,=[c['team'] for c in competition['competitors'] if c['homeAway']=='home']
        away,=[c['team'] for c in competition['competitors'] if c['homeAway']=='away']
        if not event['id'] or any(not t.get(k) for t in (home,away) for k in ('abbreviation','displayName')):
            raise ValueError('Incomplete schedule identity')
        games.append(dict(provider_event_id=str(event['id']),home_abbr=home['abbreviation'],
            away_abbr=away['abbreviation'],home_name=home['displayName'],away_name=away['displayName'],
            date=day,label=label,game_time=start.isoformat(),completed=completed))
    if len({g['provider_event_id'] for g in games})!=len(games):
        raise ValueError('Duplicate schedule event')
    return games


async def collect(sport: str, now: datetime | None = None) -> dict:
    if sport not in SPORTS:
        raise ValueError('Unsupported sport')
    now=now or datetime.now(timezone.utc)
    today=now.astimezone(ZoneInfo('America/New_York')).date()
    games=[];failures=[];sources=[]
    async with httpx.AsyncClient(timeout=10,follow_redirects=False) as client:
        for offset,label in [(-1,'Yesterday'),(0,'Today'),(1,'Tomorrow')]:
            day=(today+timedelta(days=offset)).strftime('%Y%m%d')
            url=f'https://site.api.espn.com/apis/site/v2/sports/{SPORTS[sport]}/scoreboard?dates={day}&limit=1000'
            try:
                response=await client.get(url)
                response.raise_for_status()
                games.extend(parse_day(response.json(),day,label))
                sources.append(url)
            except Exception as exc:
                failures.append(dict(date=day,error_type=type(exc).__name__))
    return dict(sport=sport,captured_at=datetime.now(timezone.utc).isoformat(),as_of_date=str(today),
        status='complete' if not failures else 'unavailable' if len(failures)==3 else 'partial',
        games=games,partial=bool(failures),failures=failures,sources=sources)
