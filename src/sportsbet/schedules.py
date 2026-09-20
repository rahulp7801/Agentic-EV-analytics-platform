"""Collect and publish bounded ESPN schedules, preserving source failures."""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo

import httpx

SPORTS = {'nba':'basketball/nba', 'nfl':'football/nfl', 'cfb':'football/college-football'}
STAT_TEAM_ALIASES = {'nba':{}, 'nfl':{'LAR':'LA', 'WSH':'WAS'}, 'cfb':{}}


def scheduled_stat_teams(sport: str, game: dict) -> frozenset[str]:
    """Translate exact ESPN abbreviations to the stat provider's identities."""
    if sport not in STAT_TEAM_ALIASES:
        raise ValueError('Unsupported sport')
    values=[]
    for field in ('home_abbr','away_abbr'):
        value=game.get(field)
        if not isinstance(value,str) or not re.fullmatch('[A-Z]{2,3}',value):
            raise ValueError('Invalid schedule team identity')
        values.append(STAT_TEAM_ALIASES[sport].get(value,value))
    if len(set(values))!=2:
        raise ValueError('Schedule teams must be distinct')
    return frozenset(values)


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


async def collect(sport: str, now: datetime | None = None, *, offsets: tuple[int, ...] = (-1,0,1)) -> dict:
    if sport not in SPORTS:
        raise ValueError('Unsupported sport')
    if (not offsets or len(set(offsets))!=len(offsets)
            or any(type(offset) is not int or not -30 <= offset <= 6 for offset in offsets)):
        raise ValueError('Schedule offsets must be unique integer days from -30 through 6')
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Schedule time requires a timezone')
    today=now.astimezone(ZoneInfo('America/New_York')).date()
    games=[];failures=[];sources=[]
    labels={-1:'Yesterday',0:'Today',1:'Tomorrow'}
    async with httpx.AsyncClient(timeout=10,follow_redirects=False) as client:
        for offset in offsets:
            day=(today+timedelta(days=offset)).strftime('%Y%m%d')
            label=labels.get(offset,(today+timedelta(days=offset)).isoformat())
            url=f'https://site.api.espn.com/apis/site/v2/sports/{SPORTS[sport]}/scoreboard?dates={day}&limit=1000'
            try:
                response=await client.get(url)
                response.raise_for_status()
                games.extend(parse_day(response.json(),day,label))
                sources.append(url)
            except Exception as exc:
                failures.append(dict(date=day,error_type=type(exc).__name__))
    return dict(sport=sport,captured_at=datetime.now(timezone.utc).isoformat(),as_of_date=str(today),
        status='complete' if not failures else 'unavailable' if len(failures)==len(offsets) else 'partial',
        games=games,partial=bool(failures),failures=failures,sources=sources)


async def publish_slate(sport: str, now: datetime | None = None) -> str:
    """Publish current and upcoming games; started games remain visibly locked."""
    if sport not in SPORTS:
        raise ValueError('Unsupported sport')
    from sportsbet.dashboard import load_snapshot, publish_snapshot
    now=now or datetime.now(timezone.utc)
    today=str(now.astimezone(ZoneInfo('America/New_York')).date())
    previous=load_snapshot('slate:'+sport) or {}
    try:
        age=now-datetime.fromisoformat(previous['captured_at'].replace('Z','+00:00'))
        if (previous.get('as_of_date')==today and previous.get('status') in ('complete','partial')
                and timedelta(0)<=age<=timedelta(minutes=10)):
            return 'cached'
    except (KeyError,ValueError,TypeError,AttributeError):
        pass
    slate=await collect(sport,now,offsets=tuple(range(7)))
    games=sorted((game for game in slate.get('games',[]) if game.get('completed') is False),
        key=lambda game:(datetime.fromisoformat(game['game_time']),game['provider_event_id']))
    truncated=len(games)>100
    status=slate['status']
    if status=='complete' and truncated:
        status='partial'
    bounded={**slate,'games':games[:100],'partial':status=='partial','status':status}
    if status in ('complete','partial'):
        publish_snapshot('slate:'+sport,bounded)
    return status


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sport',choices=sorted(SPORTS),required=True)
    args=parser.parse_args()
    try:
        print(asyncio.run(publish_slate(args.sport)))
    except Exception as exc:
        raise SystemExit(f'Schedule publication unavailable ({type(exc).__name__})') from None


if __name__=='__main__':
    main()
