"""Source-backed current roster/injury screening; never a probability boost."""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import httpx

from sportsbet.ingestion.archive import write_archive

BASES = {'nfl': 'https://site.api.espn.com/apis/site/v2/sports/football/nfl',
         'nba': 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba'}


def fresh_timestamp(value: str, now: datetime) -> str:
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or not -60 <= (now - parsed).total_seconds() <= 3600:
        raise ValueError('Availability source timestamp is missing or stale')
    return parsed.isoformat()


async def fetch_event_availability(event: dict, sport: str) -> dict:
    """Fetch both exact teams and rosters, preserving raw source commitments."""
    now = datetime.now(timezone.utc)
    base = BASES[sport]
    sources = []
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        async def read(url):
            response = await client.get(url)
            response.raise_for_status()
            if len(response.content) > 16_000_000:
                raise ValueError('Availability response exceeds limit')
            data = response.json()
            # The team directory has no status/timestamp envelope. Injury and
            # roster feeds must have recent provider timestamps, not just HTTP 200.
            if url != base+'/teams':
                if data.get('status') != 'success':
                    raise ValueError('Availability source failed')
                fresh_timestamp(data['timestamp'], now)
            sources.append(dict(url=url, source_sha256=hashlib.sha256(response.content).hexdigest(),
                                retrieved_at=now.isoformat(), response_text=response.text))
            return data
        try:
            directory, injuries = await asyncio.gather(read(base+'/teams'), read(base+'/injuries'))
            teams = [entry['team'] for entry in directory['sports'][0]['leagues'][0]['teams']]
            selected = []
            for name in (event['home_team'], event['away_team']):
                matches = [team for team in teams if team['displayName'] == name]
                if len(matches) != 1 or not str(matches[0]['id']).isdigit():
                    raise ValueError('Ambiguous availability team identity')
                selected.append(matches[0])
            rosters = await asyncio.gather(*(read(base+'/teams/'+str(team['id'])+'/roster') for team in selected))
            result = []
            for team, roster in zip(selected, rosters, strict=True):
                if str(roster['team']['id']) != str(team['id']):
                    raise ValueError('Roster team identity mismatch')
                groups = [group for group in injuries['injuries'] if str(group['id']) == str(team['id'])
                          and group['displayName'] == team['displayName']]
                if len(groups) != 1:
                    raise ValueError('Missing or ambiguous injury team coverage')
                athletes = roster['athletes']
                if sport == 'nfl':
                    athletes = [athlete for group in athletes for athlete in group['items']]
                names = [athlete['displayName'] for athlete in athletes]
                if not names or len(names) != len(set(names)):
                    raise ValueError('Incomplete or ambiguous roster')
                flags = []
                for injury in groups[0]['injuries']:
                    athlete = injury['athlete']
                    if str(athlete['team']['id']) != str(team['id']):
                        raise ValueError('Injury team identity mismatch')
                    reported = datetime.fromisoformat(injury['date'].replace('Z', '+00:00'))
                    if reported.tzinfo is None or reported > now:
                        raise ValueError('Invalid injury report date')
                    flags.append(dict(player=athlete['displayName'], status=injury['status'],
                                      position=athlete['position']['abbreviation'], reported_at=reported.isoformat()))
                if len(flags) > 64 or len({flag['player'] for flag in flags}) != len(flags):
                    raise ValueError('Ambiguous injury reports')
                result.append(dict(name=team['displayName'], abbreviation=team['abbreviation'],
                                   roster_names=names, roster_statuses={athlete['displayName']:
                                       athlete.get('status',{}).get('name','Unknown') for athlete in athletes},reports=flags,
                                   roster_source_url=base+'/teams/'+str(team['id'])+'/roster',
                                   roster_source_sha256=next(source['source_sha256'] for source in sources
                                       if source['url']==base+'/teams/'+str(team['id'])+'/roster')))
            write_archive(dict(sport=sport, game_id=event['id'], sources=sources),
                          directory=Path('.local/availability'))
            return dict(status='observed', captured_at=now.isoformat(),
                        source_url=base+'/injuries', source_sha256=next(
                            source['source_sha256'] for source in sources if source['url']==base+'/injuries'),
                        teams=result)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError, AttributeError, OSError):
            return dict(status='unavailable', captured_at=now.isoformat())


def player_availability(context: dict | None, player: str, now: datetime) -> tuple[dict, str | None]:
    """Never equate an unlisted injury with a confirmed active game-day lineup."""
    unavailable = dict(status='unavailable', roster_confirmed=False, subject_status='Unknown',
                       teammates=[], probability_adjusted=False)
    if not context or context.get('status') != 'observed':
        return unavailable, 'availability_unavailable'
    try:
        fresh_timestamp(context['captured_at'], now)
        matches = [team for team in context['teams'] if player in team['roster_names']]
        if len(matches) != 1:
            return unavailable, 'roster_unconfirmed'
        team, = matches
        subject = [row for row in team['reports'] if row['player'] == player]
        teammates = [row for row in team['reports'] if row['player'] != player]
        roster_status=team.get('roster_statuses',{}).get(player,'Unknown')
        status = subject[0]['status'] if subject else ('Not listed on injury report'
            if roster_status=='Active' else 'Roster status: '+roster_status)
        evidence = dict(status='observed', captured_at=context['captured_at'],
                        source_url=context['source_url'], source_sha256=context['source_sha256'],
                        roster_confirmed=True, team=team['abbreviation'], subject_status=status,
                        roster_source_url=team['roster_source_url'],roster_source_sha256=team['roster_source_sha256'],
                        teammates=teammates, probability_adjusted=False)
        reason = 'player_availability_risk' if (subject and status != 'Active') or roster_status!='Active' else (
            'teammate_availability_unmodeled' if any(row['status'] != 'Active' for row in teammates) else None)
        return evidence, reason
    except (ValueError, KeyError, TypeError, AttributeError):
        return unavailable, 'availability_unavailable'
