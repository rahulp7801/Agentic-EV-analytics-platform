"""Current roster presentation metadata, separate from immutable forecasts."""
import argparse
import asyncio
import json
from datetime import datetime, timezone
from sportsbet.db.connection import create_async_pool
from sportsbet.dashboard import publish_snapshot
from sportsbet.prop.availability import fetch_event_availability, player_availability


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
                rows = await conn.fetch('SELECT payload FROM dashboard_snapshots WHERE snapshot_key LIKE $1 '
                    'AND updated_at > NOW() - INTERVAL \'14 days\' ORDER BY updated_at DESC LIMIT 6', f'signals:{sport}:%')
            profiles = {}
            failures = 0
            for row in rows:
                payload = row['payload']
                if isinstance(payload,str): payload=json.loads(payload)
                signals = payload.get('signals',[])
                if not signals: continue
                players = {s['player'] for s in signals}
                event = dict(id=signals[0]['game_id'],home_team=signals[0]['home_team'],away_team=signals[0]['away_team'])
                context = await fetch_event_availability(event,sport,player_names=players)
                for player in sorted(players):
                    player_id = None
                    if sport=='nfl':
                        async with pool.acquire() as conn:
                            ids=await conn.fetch('SELECT DISTINCT player_id FROM player_stats WHERE LOWER(player_name)=LOWER($1)',player)
                        if len(ids)==1: player_id=str(ids[0]['player_id'])
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
