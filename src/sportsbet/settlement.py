"""Resolve recorded props only from exact final-game identity and observed stats."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import re
from zoneinfo import ZoneInfo

from sportsbet.ledger import (Ledger, VERIFIED_SETTLEMENT_SOURCE, utc_timestamp,
    verified_settlement_evidence)
from sportsbet.ingestion.provenance import (
    LEGACY_NFL_STAT_FIELDS, STAT_FIELDS, stat_row_sha256)
from sportsbet.schedules import scheduled_stat_teams

STAT_COLUMNS={
    'nba':{'points':'points','rebounds':'rebounds','assists':'assists'},
    'nfl':{'pass_yds':'passing_yards','rush_yds':'rushing_yards',
        'rec_yds':'receiving_yards','receptions':'receptions'},
}
AUTO_SOURCE=VERIFIED_SETTLEMENT_SOURCE
AUTO_SOURCES={AUTO_SOURCE,'espn_final_stats'}
MAX_CATCHUP_DAYS=30
MAX_EXTRA_SCHEDULE_DATES=7


class StatProvenanceError(ValueError):
    pass


def pending_schedule_offsets(ledger: Ledger, sport: str, now: datetime) -> tuple[int, ...]:
    """Return a bounded oldest-first set of unresolved dates beyond the normal week."""
    if sport not in STAT_COLUMNS or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Invalid settlement catch-up scope')
    today=now.astimezone(ZoneInfo('America/New_York')).date()
    offsets=set()
    for row in ledger.predictions():
        if row.get('sport')!=sport or row.get('prop_type') not in STAT_COLUMNS[sport]:
            continue
        if row.get('outcome') is not None:
            if row.get('outcome_source') not in AUTO_SOURCES:
                continue
            if row.get('outcome_source')==AUTO_SOURCE and verified_settlement_evidence(
                    row,row['outcome'],row.get('outcome_source'),row.get('outcome_ref'),
                    row.get('outcome_observed_at'),row.get('actual_value'),row.get('outcome_evidence')):
                continue
        try:
            offset=(date.fromisoformat(row['game_date'])-today).days
        except (KeyError,TypeError,ValueError):
            continue
        if -MAX_CATCHUP_DAYS <= offset < -7:
            offsets.add(offset)
    return tuple(sorted(offsets)[:MAX_EXTRA_SCHEDULE_DATES])


def _candidate(prediction: dict, sport: str, games: list[dict]):
    if prediction.get('sport') != sport or prediction.get('prop_type') not in STAT_COLUMNS[sport]:
        raise ValueError('Unsupported prediction')
    if prediction.get('direction') not in ('over','under'):
        raise ValueError('Unsupported direction')
    line=Decimal(str(prediction.get('line')))
    if not line.is_finite() or line < 0:
        raise ValueError('Invalid line')
    day=date.fromisoformat(prediction['game_date']).isoformat()
    start=utc_timestamp(prediction['game_start_time'])
    captured=utc_timestamp(prediction['captured_at'])
    if captured >= start:
        raise ValueError('Invalid prediction chronology')
    matches=[game for game in games if game.get('completed') is True
        and game.get('date')==day and game.get('home_name')==prediction.get('home_team')
        and game.get('away_name')==prediction.get('away_team')
        and isinstance(game.get('provider_event_id'),str) and game['provider_event_id'].strip()]
    if len(matches)!=1:
        return None
    utc_timestamp(matches[0]['game_time'])
    scheduled_stat_teams(sport,matches[0])
    return matches[0],day,line


def _actual(db, prediction: dict, sport: str, day: str, game: dict):
    column=STAT_COLUMNS[sport][prediction['prop_type']]
    player_id=str(prediction.get('player_id',''))
    if sport=='nba':
        if not player_id.isdigit() or int(player_id)<=0 or str(int(player_id))!=player_id:
            raise ValueError('Invalid player identity')
        fields=STAT_FIELDS['nba']
        rows=db.execute(f'''SELECT {','.join(fields)},source_provider,source_sha256,
            source_record_sha256,source_observed_at
            FROM nba_player_gamelogs WHERE player_id=? AND game_date=?''',
            (int(player_id),day)).fetchall()
    else:
        if not player_id.strip() or len(player_id)>20:
            raise ValueError('Invalid player identity')
        fields=STAT_FIELDS['nfl']
        rows=db.execute(f'''SELECT {','.join('ps.'+field for field in fields)},ps.source_provider,
            ps.source_sha256,ps.source_record_sha256,ps.source_observed_at
            FROM player_stats ps JOIN games g
            ON g.season=ps.season AND g.week=ps.week AND ps.team IN (g.home_team,g.away_team)
            WHERE ps.player_id=? AND g.game_date=?''',(player_id,day)).fetchall()
    if len(rows)!=1:
        return None
    record=dict(zip(fields,rows[0][:len(fields)],strict=True))
    team_field='team_abbreviation' if sport=='nba' else 'team'
    if record[team_field] not in scheduled_stat_teams(sport,game):
        return None
    if record[column] is None or type(record[column]) is bool:
        return None
    value=Decimal(str(record[column]))
    if not value.is_finite() or (sport=='nba' and value < 0):
        raise ValueError('Invalid observed stat')
    provider,digest,record_digest,observed=rows[0][len(fields):]
    expected={'nba':{'nba','espn'},'nfl':{'nflverse'}}[sport]
    if (provider not in expected or not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest)
            or not isinstance(record_digest,str) or not re.fullmatch('[0-9a-f]{64}',record_digest)):
        raise StatProvenanceError('Invalid stat source')
    evidence_fields=fields
    try:
        if stat_row_sha256(sport,record)!=record_digest:
            legacy_valid=(sport=='nfl' and prediction['prop_type']!='receptions'
                and stat_row_sha256(sport,record,legacy_nfl=True)==record_digest)
            if not legacy_valid:
                raise StatProvenanceError('Stat record hash does not match')
            # Do not retain an unhashed field in the settlement proof.
            evidence_fields=LEGACY_NFL_STAT_FIELDS
    except ValueError:
        raise StatProvenanceError('Stat record hash does not match') from None
    try:
        observed=observed if isinstance(observed,datetime) else datetime.fromisoformat(observed)
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError
    except (TypeError,ValueError):
        raise StatProvenanceError('Invalid stat observation time') from None
    evidence_record={key:(record[key].isoformat() if isinstance(record[key],(date,datetime)) else record[key])
        for key in evidence_fields}
    return value,dict(provider=provider,sha256=digest,record_sha256=record_digest,
        observed_at=observed,record=evidence_record)


def settle_final_props(ledger: Ledger, sport: str, schedule: dict) -> dict:
    """Settle supported props; uncertain finality, identity, or stats stay pending."""
    if sport not in STAT_COLUMNS or not isinstance(schedule.get('games'),list):
        raise ValueError('Invalid settlement scope')
    game_dates={game.get('date') for game in schedule['games']}
    candidates=[row for row in ledger.predictions() if row.get('sport')==sport
        and row.get('game_date') in game_dates
        and (row.get('outcome') is None or row.get('outcome_source') in AUTO_SOURCES)]
    reasons=Counter();resolved=[]
    with ledger.connect() as db:
        for prediction in candidates:
            try:
                matched=_candidate(prediction,sport,schedule['games'])
                if matched is None:
                    reasons['final_game_not_matched']+=1
                    continue
                game,day,line=matched
                observed=_actual(db,prediction,sport,day,game)
                if observed is None:
                    reasons['stat_not_found_or_ambiguous']+=1
                    continue
                actual,provenance=observed
                game_time=utc_timestamp(game['game_time'])
                if not game_time <= provenance['observed_at'].astimezone(timezone.utc) <= datetime.now(timezone.utc):
                    raise StatProvenanceError('Stat observation time is outside the evidence window')
                outcome='push' if actual==line else ((actual>line)==(prediction['direction']=='over'))
                resolved.append((prediction,game,outcome,actual,provenance))
            except StatProvenanceError:
                reasons['stat_provenance_invalid']+=1
            except (KeyError,TypeError,ValueError,ArithmeticError):
                reasons['invalid_prediction_or_evidence']+=1
    schedule_observed=utc_timestamp(schedule['captured_at'])
    for prediction,game,outcome,actual,provenance in resolved:
        evidence=dict(schedule_identity_version=2,
            provider_event_id=game['provider_event_id'],date=game['date'],
            home_abbr=game['home_abbr'],away_abbr=game['away_abbr'],
            home_name=game['home_name'],away_name=game['away_name'],completed=True,
            game_time=game['game_time'],player_id=prediction['player_id'],
            prop_type=prediction['prop_type'],actual_value=str(actual),
            stat_provider=provenance['provider'],stat_source_sha256=provenance['sha256'],
            stat_record_sha256=provenance['record_sha256'],
            stat_observed_at=provenance['observed_at'].isoformat(),stat_row=provenance['record'])
        digest=hashlib.sha256(json.dumps(evidence,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        reference=f"espn_schedule+{provenance['provider']}:{game['provider_event_id']}:sha256:{digest}"
        ledger.settle({prediction['prediction_id']:outcome},source=AUTO_SOURCE,source_ref=reference,
            observed_at=max(schedule_observed,provenance['observed_at']),
            actual_values={prediction['prediction_id']:actual},
            evidence={prediction['prediction_id']:evidence})
    return dict(sport=sport,status='complete' if schedule.get('status')=='complete' else 'degraded',
        candidates=len(candidates),settled=len(resolved),pending=len(candidates)-len(resolved),
        reasons=dict(sorted(reasons.items())),execution_ready=False)
