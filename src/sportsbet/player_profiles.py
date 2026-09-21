"""Current roster presentation metadata, separate from immutable forecasts."""
import argparse
import asyncio
import json
from datetime import datetime, timezone
from sportsbet.db.connection import create_async_pool
from sportsbet.dashboard import publish_snapshot
from sportsbet.prop.availability import fetch_event_availability, player_availability

SIGNAL_IDENTITIES_QUERY = '''WITH latest AS MATERIALIZED (
    SELECT payload FROM dashboard_snapshots
    WHERE snapshot_key LIKE $1 AND updated_at > NOW() - INTERVAL '14 days'
    ORDER BY updated_at DESC LIMIT 6
), bounded AS MATERIALIZED (
    SELECT payload->'signals' AS signals FROM latest
    WHERE jsonb_typeof(payload->'signals')='array'
      AND jsonb_array_length(payload->'signals')<=500
)
SELECT DISTINCT signal->>'player' AS player,signal->>'game_id' AS game_id,
    signal->>'home_team' AS home_team,signal->>'away_team' AS away_team
FROM bounded CROSS JOIN LATERAL jsonb_array_elements(signals) AS signal
WHERE jsonb_typeof(signal)='object'
  AND signal->>'player' IS NOT NULL AND signal->>'game_id' IS NOT NULL
  AND signal->>'home_team' IS NOT NULL AND signal->>'away_team' IS NOT NULL
ORDER BY game_id,player LIMIT 1000'''


def profile(context, player, player_id, now):
    evidence, _ = player_availability(context, player, now, player_id=player_id)
    if evidence['status'] != 'observed' or not evidence.get('player_id'):
        return None
    return dict(player=player, name=evidence.get('roster_player_name', player),
        team=evidence['team'], player_id=evidence['player_id'],
        image_url=evidence['player_image_url'], captured_at=evidence['captured_at'],
        source_url=evidence['roster_source_url'], source_sha256=evidence['roster_source_sha256'],
        **{key:evidence[key] for key in ('jersey','position') if evidence.get(key)},
        **{key:evidence[key] for key in ('identity_source_url','identity_source_sha256') if key in evidence})


async def run(sports):
    pool = await create_async_pool()
    results = {}
    try:
        for sport in sports:
            async with pool.acquire() as conn:
                rows = await conn.fetch(SIGNAL_IDENTITIES_QUERY, f'signals:{sport}:%')
                player_ids = {}
                if sport == 'nfl' and rows:
                    names=sorted({row['player'].lower() for row in rows})
                    ids=await conn.fetch('SELECT lower(player_name) AS player_name,'
                        'array_agg(DISTINCT player_id::text) AS player_ids FROM player_stats '
                        'WHERE lower(player_name)=ANY($1::text[]) GROUP BY lower(player_name)',names)
                    player_ids={row['player_name']:row['player_ids'] for row in ids}
            profiles = {}
            failures = 0
            events={}
            for row in rows:
                identity=(row['game_id'],row['home_team'],row['away_team'])
                events.setdefault(identity,set()).add(row['player'])
            for (game_id,home_team,away_team),players in events.items():
                event=dict(id=game_id,home_team=home_team,away_team=away_team)
                context = await fetch_event_availability(event,sport,player_names=players)
                for player in sorted(players):
                    player_id = None
                    if sport=='nfl':
                        matches=player_ids.get(player.lower(),[])
                        if len(matches)==1: player_id=matches[0]
                    value=profile(context,player,player_id,datetime.now(timezone.utc))
                    if value: profiles.setdefault(player,value)
                    else: failures+=1
            # A provider failure must not erase the last successful metadata capture.
            if profiles or not rows:
                publish_snapshot('player-profiles:'+sport,dict(sport=sport,
                    captured_at=datetime.now(timezone.utc).isoformat(),profiles=list(profiles.values())))
            results[sport]=dict(profiles=len(profiles),unavailable=failures)
        return results
    finally:
        await pool.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sport',choices=['nfl','nba','both'],default='both')
    args=parser.parse_args()
    try:
        print(json.dumps(asyncio.run(run(['nfl','nba'] if args.sport=='both' else [args.sport]))))
    except Exception as exc:
        raise SystemExit(f'Player metadata update unavailable ({type(exc).__name__})') from None


if __name__=='__main__': main()
