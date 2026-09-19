"""Source-backed current roster/injury screening; never a probability boost."""
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx

from sportsbet.ingestion.archive import write_archive

BASES = {'nfl': 'https://site.api.espn.com/apis/site/v2/sports/football/nfl',
         'nba': 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba'}
NFL_PLAYER_IDS_URL = 'https://github.com/nflverse/nflverse-data/releases/download/players/players.csv'


async def nfl_player_identities(client: httpx.AsyncClient, roster_ids: set[str], now: datetime) -> tuple[dict, dict, dict]:
    """Use the published GSIS/ESPN/PFR crosswalk, never a guessed name alias."""
    url = httpx.URL(NFL_PLAYER_IDS_URL)
    for _ in range(3):
        response = await client.get(url)
        if not response.is_redirect:
            break
        url = url.join(response.headers['location'])
        if url.scheme != 'https' or url.host not in (
            'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'
        ) or url.port not in (None, 443) or url.userinfo:
            raise ValueError('Untrusted identity redirect')
    response.raise_for_status()
    if response.status_code != 200 or len(response.content) > 16_000_000:
        raise ValueError('Invalid identity response')
    reader = csv.DictReader(io.StringIO(response.content.decode('utf-8-sig')))
    if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames) or not {'gsis_id','espn_id'} <= set(reader.fieldnames):
        raise ValueError('Invalid identity columns')
    mappings, pfr_mappings, seen_gsis, seen_espn, seen_pfr = {}, {}, set(), set(), set()
    for count, row in enumerate(reader, 1):
        if count > 50_000 or None in row:
            raise ValueError('Invalid identity rows')
        gsis, espn = row['gsis_id'], row['espn_id']
        if not isinstance(gsis, str) or not re.fullmatch(r'00-[0-9]{7}', gsis) or not isinstance(espn, str) or not re.fullmatch(r'[1-9][0-9]{0,19}', espn):
            continue
        if gsis in seen_gsis or espn in seen_espn:
            raise ValueError('Ambiguous player identities')
        seen_gsis.add(gsis)
        seen_espn.add(espn)
        if espn in roster_ids:
            mappings[gsis] = espn
            pfr = row.get('pfr_id')
            if isinstance(pfr,str) and re.fullmatch(r'[A-Za-z0-9]{1,20}',pfr):
                if pfr in seen_pfr:
                    raise ValueError('Ambiguous player identities')
                seen_pfr.add(pfr)
                pfr_mappings[espn] = pfr
    return mappings, pfr_mappings, dict(url=NFL_PLAYER_IDS_URL,
        source_sha256=hashlib.sha256(response.content).hexdigest(),
        retrieved_at=now.isoformat(), response_text=response.content.decode('utf-8'))


def fresh_timestamp(value: str, now: datetime) -> str:
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or not -60 <= (now - parsed).total_seconds() <= 3600:
        raise ValueError('Availability source timestamp is missing or stale')
    return parsed.isoformat()


def injury_report(player: str, position: str, report: dict, now: datetime) -> dict:
    reported = datetime.fromisoformat(report['date'].replace('Z', '+00:00'))
    if reported.tzinfo is None or reported > now or any(
        not isinstance(value, str) or not value.strip() or len(value) > limit
        or any(ord(character) < 32 for character in value)
        for value, limit in ((player, 100), (position, 10), (report['status'], 100))
    ):
        raise ValueError('Invalid injury report')
    return dict(player=player, status=report['status'], position=position,
                reported_at=reported.isoformat())


async def fetch_event_availability(event: dict, sport: str, *, player_names: set[str] | None = None) -> dict:
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
            directory, injuries = await asyncio.gather(
                read(base+'/teams'), read(base+'/injuries'), return_exceptions=True)
            if isinstance(directory, Exception):
                raise ValueError('Team directory unavailable')
            teams = [entry['team'] for entry in directory['sports'][0]['leagues'][0]['teams']]
            selected = []
            for name in (event['home_team'], event['away_team']):
                if sport=='nba' and name=='Los Angeles Clippers':
                    name='LA Clippers'  # Explicit provider alias, not fuzzy identity matching.
                matches = [team for team in teams if team['displayName'] == name]
                if len(matches) != 1 or not str(matches[0]['id']).isdigit():
                    raise ValueError('Ambiguous availability team identity')
                selected.append(matches[0])
            rosters = await asyncio.gather(*(read(base+'/teams/'+str(team['id'])+'/roster') for team in selected))
            result = []
            for team, roster in zip(selected, rosters, strict=True):
                if str(roster['team']['id']) != str(team['id']):
                    raise ValueError('Roster team identity mismatch')
                groups = [] if isinstance(injuries, Exception) else [
                    group for group in injuries['injuries'] if str(group['id']) == str(team['id'])
                    and group['displayName'] == team['displayName']]
                if len(groups) > 1:
                    raise ValueError('Ambiguous injury team coverage')
                athletes = roster['athletes']
                if sport == 'nfl':
                    athletes = [athlete for group in athletes for athlete in group['items']]
                names = [athlete['displayName'] for athlete in athletes]
                if not names or len(names) != len(set(names)):
                    raise ValueError('Incomplete or ambiguous roster')
                roster_ids = {str(athlete['id']): athlete['displayName'] for athlete in athletes
                              if str(athlete.get('id','')).isdigit()}
                if len(roster_ids) != sum(str(athlete.get('id','')).isdigit() for athlete in athletes):
                    raise ValueError('Ambiguous roster athlete IDs')
                flags = []
                for injury in groups[0]['injuries'] if groups else []:
                    athlete = injury['athlete']
                    if str(athlete['team']['id']) != str(team['id']):
                        raise ValueError('Injury team identity mismatch')
                    flags.append(injury_report(athlete['displayName'],
                        athlete['position']['abbreviation'], injury, now))
                if len(flags) > 64 or len({flag['player'] for flag in flags}) != len(flags):
                    raise ValueError('Ambiguous injury reports')
                # A team omitted from the league feed is not an empty injury report.
                # Its roster is a fallback only when EVERY athlete explicitly carries
                # an injuries array in this fresh, exact-team response.
                roster_complete = all(isinstance(athlete.get('injuries'), list) for athlete in athletes)
                if any('injuries' in athlete for athlete in athletes):
                    reports = {flag['player']: flag for flag in flags}
                    for athlete in athletes:
                        entries = athlete.get('injuries', [])
                        if not isinstance(entries, list) or len(entries) > 1:
                            raise ValueError('Ambiguous roster injury reports')
                        for injury in entries:
                            flag = injury_report(athlete['displayName'],
                                athlete['position']['abbreviation'], injury, now)
                            previous = reports.get(flag['player'])
                            if previous and previous['status'] != flag['status']:
                                raise ValueError('Conflicting injury source statuses')
                            if not previous or datetime.fromisoformat(flag['reported_at']) > datetime.fromisoformat(previous['reported_at']):
                                reports[flag['player']] = flag
                    flags = list(reports.values())
                if len(flags) > 64 or len({flag['player'] for flag in flags}) != len(flags):
                    raise ValueError('Ambiguous injury reports')
                roster_url = base+'/teams/'+str(team['id'])+'/roster'
                injury_url = base+'/injuries' if groups else roster_url
                result.append(dict(name=team['displayName'], abbreviation=team['abbreviation'],
                                   portraits={athlete['displayName']:dict(player_id=str(athlete.get('id','')),
                                       jersey=str(athlete.get('jersey','')),position=athlete.get('position',{}).get('abbreviation',''),
                                       player_image_url=athlete.get('headshot',{}).get('href','')) for athlete in athletes
                                       if str(athlete.get('id','')).isdigit() and athlete.get('headshot',{}).get('href')==
                                       f"https://a.espncdn.com/i/headshots/{sport}/players/full/{athlete['id']}.png"},
                                   roster_names=names, roster_statuses={athlete['displayName']:
                                       athlete.get('status',{}).get('name','Unknown') for athlete in athletes},reports=flags,
                                   roster_ids=roster_ids,
                                   injury_coverage='observed' if groups or roster_complete else 'unavailable',
                                   injury_source_url=injury_url,
                                   injury_source_sha256=next(source['source_sha256'] for source in sources
                                       if source['url']==injury_url),
                                   roster_source_url=roster_url,
                                   roster_source_sha256=next(source['source_sha256'] for source in sources
                                       if source['url']==base+'/teams/'+str(team['id'])+'/roster')))
            identities = {}
            pfr_identities = {}
            identity_source = None
            unmatched = bool(player_names and not player_names <= {
                name for team in result for name in team['roster_names']})
            # Injury-context evidence also needs exact PFR IDs for reported
            # offensive and defensive participants, even when display names match.
            has_reports = any(team['reports'] for team in result)
            if sport=='nfl' and (unmatched or has_reports):
                try:
                    identities, pfr_identities, identity_source = await nfl_player_identities(client,
                        {identity for team in result for identity in team['roster_ids']}, now)
                    sources.append(identity_source)
                    identity_source = {key: identity_source[key] for key in ('url','source_sha256','retrieved_at')}
                except (httpx.HTTPError, httpx.InvalidURL, ValueError, KeyError, csv.Error):
                    pass  # Missing identity evidence cannot make an unmatched player eligible.
            write_archive(dict(sport=sport, game_id=event['id'], sources=sources),
                          directory=Path('.local/availability'))
            return dict(status='observed' if all(team['injury_coverage']=='observed' for team in result)
                        else 'partial', captured_at=now.isoformat(),
                        source_url=base+'/injuries', source_sha256=next((
                            source['source_sha256'] for source in sources if source['url']==base+'/injuries'), None),
                        teams=result, player_identities=identities,
                        pfr_player_identities=pfr_identities,
                        identity_source=identity_source)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError, AttributeError, OSError):
            return dict(status='unavailable', captured_at=now.isoformat())


def player_availability(context: dict | None, player: str, now: datetime, *, player_id: str | None = None) -> tuple[dict, str | None]:
    """Never equate an unlisted injury with a confirmed active game-day lineup."""
    unavailable = dict(status='unavailable', roster_confirmed=False, subject_status='Unknown',
                       teammates=[], probability_adjusted=False)
    if not context or context.get('status') not in ('observed','partial'):
        return unavailable, 'availability_unavailable'
    try:
        fresh_timestamp(context['captured_at'], now)
        identity_source = context.get('identity_source') if player_id else None
        if identity_source:
            fresh_timestamp(identity_source['retrieved_at'], now)
            if identity_source['url'] != NFL_PLAYER_IDS_URL or not re.fullmatch(r'[a-f0-9]{64}',identity_source['source_sha256']):
                raise ValueError('Invalid identity commitment')
            espn_id = context['player_identities'].get(player_id)
            if espn_id:
                matches = [(team, team['roster_ids'][espn_id]) for team in context['teams']
                           if espn_id in team['roster_ids']]
            else:
                # Loading the crosswalk for an injured teammate must not erase
                # an exact subject-name roster match when that subject has no ID row.
                identity_source = None
                matches = [(team, player) for team in context['teams'] if player in team['roster_names']]
        else:
            matches = [(team, player) for team in context['teams'] if player in team['roster_names']]
        if len(matches) != 1:
            return unavailable, 'roster_unconfirmed'
        team, roster_name = matches[0]
        if team.get('injury_coverage','observed') != 'observed':
            return unavailable, 'availability_unavailable'
        subject = [row for row in team['reports'] if row['player'] == roster_name]
        teammates = [row for row in team['reports'] if row['player'] != roster_name]
        roster_status=team.get('roster_statuses',{}).get(roster_name,'Unknown')
        status = subject[0]['status'] if subject else ('Not listed on injury report'
            if roster_status=='Active' else 'Roster status: '+roster_status)
        evidence = dict(status='observed', captured_at=context['captured_at'],
                        source_url=team.get('injury_source_url',context['source_url']),
                        source_sha256=team.get('injury_source_sha256',context['source_sha256']),
                        roster_confirmed=True, team=team['abbreviation'], subject_status=status,
                        roster_source_url=team['roster_source_url'],roster_source_sha256=team['roster_source_sha256'],
                        teammates=teammates, probability_adjusted=False)
        evidence.update(team.get('portraits',{}).get(roster_name,{}))
        if roster_name != player:
            evidence.update(roster_player_name=roster_name,
                identity_source_url=identity_source['url'],
                identity_source_sha256=identity_source['source_sha256'])
        reason = 'player_availability_risk' if (subject and status != 'Active') or roster_status!='Active' else (
            'teammate_availability_unmodeled' if any(row['status'] != 'Active' for row in teammates) else None)
        return evidence, reason
    except (ValueError, KeyError, TypeError, AttributeError):
        return unavailable, 'availability_unavailable'
