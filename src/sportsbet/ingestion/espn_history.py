"""Archive free ESPN final box scores for research; never manufacture betting lines."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

SPORTS = {'nba': 'basketball/nba', 'nfl': 'football/nfl'}
STATS = {
    'nba': {'points': 'points', 'rebounds': 'rebounds', 'assists': 'assists'},
    'nfl': {'passingYards': 'pass_yds', 'rushingYards': 'rush_yds', 'receivingYards': 'rec_yds'},
}


def parse_boxscore(data: dict, sport: str) -> list[dict]:
    """Only final, identified, participating players with explicit numeric stats."""
    header = data['header']
    competition, = header['competitions']
    if not competition.get('status', {}).get('type', {}).get('completed'):
        return []
    start = datetime.fromisoformat(competition['date'].replace('Z', '+00:00'))
    if start.utcoffset() is None:
        raise ValueError('ESPN game time must include a timezone')
    teams = {str(t['id']): t for t in competition['competitors']}
    if len(teams) != 2:
        raise ValueError('Expected two teams')
    rows = {}
    for team in data.get('boxscore', {}).get('players', []):
        team_id = str(team['team']['id'])
        opponent, = [t for k, t in teams.items() if k != team_id]
        for group in team['statistics']:
            for entry in group.get('athletes', []):
                athlete = entry.get('athlete', {})
                if entry.get('didNotPlay') or not athlete.get('id') or not athlete.get('displayName'):
                    continue
                values = dict(zip(group['keys'], entry.get('stats', []), strict=True))
                for source, prop in STATS[sport].items():
                    value = values.get(source)
                    if value is None or value == '' or value == '--':
                        continue
                    # These six counting stats are integers; missing values are not zero.
                    actual = int(value)
                    row = dict(sport=sport, event_id=str(header['id']), player_id=str(athlete['id']),
                        player_name=athlete['displayName'], prop_type=prop, actual_value=actual,
                        game_start_time=start.isoformat(),
                        game_date=start.astimezone(ZoneInfo('America/New_York')).date().isoformat(),
                        team=teams[team_id]['team']['abbreviation'], opponent=opponent['team']['abbreviation'])
                    key = (row['event_id'], row['player_id'], prop)
                    if key in rows and rows[key] != row:
                        raise ValueError('Conflicting ESPN player stats')
                    rows[key] = row
    if not rows:
        raise ValueError('Final game has no usable box-score stats')
    return list(rows.values())


def collect(sport: str, start: date, end: date, output: Path) -> dict:
    if end < start or (end-start).days > 30:
        raise ValueError('Request between one and 31 days per archive')
    output.mkdir(parents=True, exist_ok=True)
    sources = {}
    rows = []
    games = set()
    with httpx.Client(timeout=25) as client:
        def fetch(url: str) -> dict:
            path = output / (hashlib.sha256(url.encode()).hexdigest() + '.json')
            if path.exists():
                archive = json.loads(path.read_text(encoding='utf-8'))
            else:
                response = client.get(url)
                response.raise_for_status()
                archive = dict(url=url, retrieved_at=datetime.now(timezone.utc).isoformat(), body=response.text)
                path.write_text(json.dumps(archive), encoding='utf-8')
                time.sleep(1)
            if archive['url'] != url:
                raise ValueError('Archive source mismatch')
            sources[url] = dict(url=url, retrieved_at=archive['retrieved_at'],
                sha256=hashlib.sha256(archive['body'].encode()).hexdigest())
            return json.loads(archive['body'])

        day = start
        while day <= end:
            base = f'https://site.api.espn.com/apis/site/v2/sports/{SPORTS[sport]}'
            board = fetch(f'{base}/scoreboard?dates={day:%Y%m%d}&limit=1000')
            for event in board['events']:
                if event['id'] in games or not event.get('status', {}).get('type', {}).get('completed'):
                    continue
                games.add(event['id'])
                url = f'{base}/summary?event={event["id"]}'
                for row in parse_boxscore(fetch(url), sport):
                    rows.append(row | {'source_url': url, 'source_sha256': sources[url]['sha256']})
            day += timedelta(days=1)
    dataset = dict(kind='final_player_stats', sport=sport, start=str(start), end=str(end),
        game_count=len(games), record_count=len(rows), sources=list(sources.values()), records=rows,
        limitations=['Final participating-player stats, not historical sportsbook quotes.',
            'No line, odds, quote timestamp, DNP settlement or historical injury status is inferred.',
            'Stats reflect provider corrections as retrieved; not an archive of their original publication time.'])
    (output / 'dataset.json').write_text(json.dumps(dataset, indent=2), encoding='utf-8')
    return dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sport', choices=SPORTS, required=True)
    parser.add_argument('--start', type=date.fromisoformat, required=True)
    parser.add_argument('--end', type=date.fromisoformat, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    dataset = collect(args.sport, args.start, args.end, args.output)
    print(json.dumps({k: dataset[k] for k in ('kind', 'game_count', 'record_count', 'limitations')}, indent=2))


if __name__ == '__main__':
    main()
