"""Descriptive recorded participation evidence for current availability risks."""
from __future__ import annotations

from datetime import date

import asyncpg

from sportsbet.prop.nba_query_builder import NBA_GAMELOG_COLUMN_MAP
from sportsbet.prop.nba_context_producer import nba_team_abbreviation
from sportsbet.prop.query_builder import PROP_COLUMN_MAP
from sportsbet.schedules import STAT_TEAM_ALIASES

OFFENSE = frozenset({'QB','RB','FB','WR','TE','C','G','OG','OT','T','OL'})
DEFENSE = frozenset({'DE','DT','DL','NT','LB','ILB','OLB','CB','DB','S','FS','SS'})
BASKETBALL = frozenset({'PG','SG','SF','PF','C','G','F','G-F','F-G','F-C','C-F'})
RISK = frozenset({'out','inactive','injured reserve','doubtful','questionable'})


def relevant_availability_reports(context: dict | None, subject_team: str,
                                  subject_player: str, sport: str) -> list[dict]:
    """Return reported offensive teammates and opposing defenders that can affect the subject."""
    if not context or context.get('status') not in ('observed','partial'):
        return []
    candidates = []
    for team in context.get('teams', []):
        relation = 'teammate' if team.get('abbreviation') == subject_team else 'opponent'
        for report in team.get('reports', []):
            if relation == 'teammate' and report.get('player') == subject_player:
                continue
            position = str(report.get('position','')).upper()
            unit = (('offense' if relation=='teammate' else 'defense') if sport=='nba' and position in BASKETBALL
                    else 'offense' if position in OFFENSE else 'defense' if position in DEFENSE else None)
            if str(report.get('status','')).strip().lower() not in RISK:
                continue
            if (relation,unit) not in (('teammate','offense'),('opponent','defense')):
                continue
            row = dict(player=report['player'],status=report['status'],position=position,
                       team=team['abbreviation'],relationship=relation,unit=unit,
                       reported_at=report.get('reported_at'),source_url=team.get('injury_source_url'),
                       source_sha256=team.get('injury_source_sha256'))
            candidates.append(row)
    priority = {'out':0,'inactive':0,'injured reserve':0,'doubtful':1,'questionable':2}
    return sorted(candidates,key=lambda row:(priority.get(row['status'].lower(),3),row['relationship'],row['player']))[:8]


def current_contexts(context: dict | None, subject_team: str, subject_player: str, sport: str) -> list[dict]:
    """Return relevant injury-report participants with exact identities for historical splits."""
    candidates = []
    pfr = context.get('pfr_player_identities', {}) if context else {}
    teams = context.get('teams', []) if context else []
    for row in relevant_availability_reports(context,subject_team,subject_player,sport):
        team=next((team for team in teams if team.get('abbreviation')==row['team']),None)
        if not team:
            continue
        row=dict(row)
        if sport == 'nfl':
            roster_ids = {name: identity for identity,name in team.get('roster_ids', {}).items()}
            espn_id = roster_ids.get(row['player'])
            player_id = pfr.get(espn_id) if espn_id else None
            if not player_id:
                continue
            row['participant_id'] = player_id
            row['stat_team'] = STAT_TEAM_ALIASES['nfl'].get(row['team'],row['team'])
        else:
            try:
                row['stat_team'] = nba_team_abbreviation(team['name'])
            except ValueError:
                continue
        candidates.append(row)
    return candidates


def _summary(games: int, mean: object, hits: int) -> dict:
    return dict(games=games, mean=round(float(mean),2) if mean is not None else None,
                hit_rate=round(hits/games,4) if games else None)


async def _nfl_split(conn, player_id: str, season: int, cutoff: date, prop_type: str,
                     line: float, direction: str, candidate: dict) -> dict | None:
    column = PROP_COLUMN_MAP[prop_type]
    operator = '>' if direction == 'over' else '<'
    relation = 'team' if candidate['relationship'] == 'teammate' else 'opponent_team'
    # Legacy ingestion filled missing NFL snap values with zero. Only positive
    # counts establish participation; neither zero nor a missing row proves absence.
    snap_column = 'offense_snaps' if candidate['unit'] == 'offense' else 'defense_snaps'
    stat_team=candidate['stat_team']
    row = await conn.fetchrow(f'''WITH tenure AS (
        SELECT MIN(season*100+week) AS first_week FROM nfl_snap_counts
        WHERE pfr_player_id=$6 AND team=$5 AND {snap_column}>0
          AND source_provider='nflverse'
          AND source_sha256 ~ '^[0-9a-f]{{64}}$'
          AND source_record_sha256 ~ '^[0-9a-f]{{64}}$'
    ), target AS (
        SELECT ps.season,ps.week,ps.{column}::float AS value
        FROM player_stats ps
        WHERE ps.player_id=$1 AND ps.season >= $2 AND ps.{column} IS NOT NULL
          AND ps.{relation}=$5
          AND ps.source_provider='nflverse'
          AND ps.source_sha256 ~ '^[0-9a-f]{{64}}$'
          AND ps.source_record_sha256 ~ '^[0-9a-f]{{64}}$'
          AND ps.season*100+ps.week >= (SELECT first_week FROM tenure)
          AND EXISTS (SELECT 1 FROM games g WHERE g.season=ps.season AND g.week=ps.week
            AND (g.home_team=ps.team OR g.away_team=ps.team) AND g.game_date < $4)
        ORDER BY ps.season DESC,ps.week DESC LIMIT 40
    ), labeled AS (
        SELECT value,(SELECT CASE WHEN COUNT(*)=1 AND BOOL_AND(
            sc.source_provider='nflverse'
            AND sc.source_sha256 ~ '^[0-9a-f]{{64}}$'
            AND sc.source_record_sha256 ~ '^[0-9a-f]{{64}}$'
            AND sc.{snap_column}>0) THEN TRUE END
          FROM nfl_snap_counts sc
          WHERE sc.season=target.season AND sc.week=target.week AND sc.team=$5
            AND sc.pfr_player_id=$6) AS active FROM target
    ) SELECT COUNT(*) FILTER (WHERE active) active_games,
        AVG(value) FILTER (WHERE active) active_mean,
        COUNT(*) FILTER (WHERE active AND value {operator} $3::double precision) active_hits,
        COUNT(*) FILTER (WHERE NOT active) absent_games,
        AVG(value) FILTER (WHERE NOT active) absent_mean,
        COUNT(*) FILTER (WHERE NOT active AND value {operator} $3::double precision) absent_hits,
        COUNT(*) FILTER (WHERE active IS NULL) unknown_games
      FROM labeled''',player_id,season,line,cutoff,stat_team,candidate['participant_id'])
    if not row or sum(int(row[key] or 0) for key in ('active_games','absent_games','unknown_games'))==0:
        return None
    active_games, absent_games = int(row['active_games'] or 0), int(row['absent_games'] or 0)
    evidence={key:candidate[key] for key in ('player','status','position','team','relationship','unit')}
    return evidence | dict(active=_summary(active_games,row['active_mean'],int(row['active_hits'] or 0)),
        absent=_summary(absent_games,row['absent_mean'],int(row['absent_hits'] or 0)),
        unknown_games=int(row['unknown_games'] or 0),evidence_version='recorded-participation-v2',
        source='nflverse_snap_counts',participation='recorded unit snaps')


async def _nba_split(conn, player_id: str, season: int, cutoff: date, prop_type: str,
                     line: float, direction: str, candidate: dict) -> dict | None:
    column = NBA_GAMELOG_COLUMN_MAP[prop_type]
    value = '(points+rebounds+assists)' if prop_type == 'pra' else column
    operator = '>' if direction == 'over' else '<'
    relation = 'team_abbreviation' if candidate['relationship'] == 'teammate' else 'opponent_team'
    stat_team = candidate['stat_team']
    identities = await conn.fetch('''SELECT DISTINCT player_id FROM nba_player_gamelogs
        WHERE LOWER(player_name)=LOWER($1) AND team_abbreviation=$2''',candidate['player'],stat_team)
    if len(identities) != 1:
        return None
    participant_id = identities[0]['player_id']
    row = await conn.fetchrow(f'''WITH tenure AS (
        SELECT MIN(game_date) first_game FROM nba_player_gamelogs
        WHERE player_id=$6 AND team_abbreviation=$5 AND minutes>0
          AND source_provider IN ('nba','espn')
          AND source_sha256 ~ '^[0-9a-f]{{64}}$'
          AND source_record_sha256 ~ '^[0-9a-f]{{64}}$'
    ), target AS (
        SELECT game_id,{value}::float AS value
        FROM nba_player_gamelogs
        WHERE player_id=$1 AND season >= $2 AND game_date < $4 AND {relation}=$5
          AND game_date >= (SELECT first_game FROM tenure)
          AND source_provider IN ('nba','espn')
          AND source_sha256 ~ '^[0-9a-f]{{64}}$'
          AND source_record_sha256 ~ '^[0-9a-f]{{64}}$'
          AND {value} IS NOT NULL
        ORDER BY game_date DESC LIMIT 40
    ), labeled AS (
        SELECT value,(SELECT CASE WHEN COUNT(*)=1 AND BOOL_AND(
            gl.source_provider IN ('nba','espn')
            AND gl.source_sha256 ~ '^[0-9a-f]{{64}}$'
            AND gl.source_record_sha256 ~ '^[0-9a-f]{{64}}$'
            AND gl.minutes IS NOT NULL AND gl.minutes BETWEEN 0 AND 999.9)
            THEN BOOL_AND(gl.minutes>0) END
          FROM nba_player_gamelogs gl
          WHERE gl.game_id=target.game_id AND gl.player_id=$6 AND gl.team_abbreviation=$5
        ) AS active FROM target
    ) SELECT COUNT(*) FILTER (WHERE active) active_games,
        AVG(value) FILTER (WHERE active) active_mean,
        COUNT(*) FILTER (WHERE active AND value {operator} $3::double precision) active_hits,
        COUNT(*) FILTER (WHERE NOT active) absent_games,
        AVG(value) FILTER (WHERE NOT active) absent_mean,
        COUNT(*) FILTER (WHERE NOT active AND value {operator} $3::double precision) absent_hits,
        COUNT(*) FILTER (WHERE active IS NULL) unknown_games
      FROM labeled''',int(player_id),season,line,cutoff,stat_team,participant_id)
    if not row or sum(int(row[key] or 0) for key in ('active_games','absent_games','unknown_games'))==0:
        return None
    active_games, absent_games = int(row['active_games'] or 0), int(row['absent_games'] or 0)
    evidence={key:candidate[key] for key in ('player','status','position','team','relationship','unit')}
    return evidence | dict(active=_summary(active_games,row['active_mean'],int(row['active_hits'] or 0)),
        absent=_summary(absent_games,row['absent_mean'],int(row['absent_hits'] or 0)),
        unknown_games=int(row['unknown_games'] or 0),evidence_version='recorded-participation-v2',
        source='nba_final_box_scores',participation='recorded minutes')


async def historical_availability_splits(pool, *, context: dict | None, subject_team: str,
        subject_player: str, sport: str, player_id: str, season: int, cutoff: date, prop_type: str,
        line: float, direction: str) -> list[dict]:
    """Describe recorded participation cohorts; never mutate the model probability."""
    candidates = current_contexts(context,subject_team,subject_player,sport)
    if not candidates or direction not in ('over','under'):
        return []
    rows = []
    try:
        async with pool.acquire() as conn:
            for candidate in candidates:
                result = await (_nfl_split(conn,player_id,season,cutoff,prop_type,line,direction,candidate)
                    if sport == 'nfl' else
                    _nba_split(conn,player_id,season,cutoff,prop_type,line,direction,candidate))
                if result:
                    rows.append(result)
    except asyncpg.UndefinedTableError:
        return []
    return rows
