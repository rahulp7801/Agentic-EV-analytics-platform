"""Resolve recorded props only from exact final-game identity and observed stats."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json

from sportsbet.ledger import Ledger, utc_timestamp

STAT_COLUMNS={
    'nba':{'points':'points','rebounds':'rebounds','assists':'assists'},
    'nfl':{'pass_yds':'passing_yards','rush_yds':'rushing_yards','rec_yds':'receiving_yards'},
}
AUTO_SOURCE='espn_final_stats'


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
    return matches[0],day,line


def _actual(db, prediction: dict, sport: str, day: str):
    column=STAT_COLUMNS[sport][prediction['prop_type']]
    player_id=str(prediction.get('player_id',''))
    if sport=='nba':
        if not player_id.isdigit() or int(player_id)<=0 or str(int(player_id))!=player_id:
            raise ValueError('Invalid player identity')
        rows=db.execute(f'SELECT {column} FROM nba_player_gamelogs WHERE player_id=? AND game_date=?',
            (int(player_id),day)).fetchall()
    else:
        if not player_id.strip() or len(player_id)>20:
            raise ValueError('Invalid player identity')
        rows=db.execute(f'''SELECT ps.{column} FROM player_stats ps JOIN games g
            ON g.season=ps.season AND g.week=ps.week AND ps.team IN (g.home_team,g.away_team)
            WHERE ps.player_id=? AND g.game_date=?''',(player_id,day)).fetchall()
    if len(rows)!=1 or rows[0][0] is None or type(rows[0][0]) is bool:
        return None
    value=Decimal(str(rows[0][0]))
    if not value.is_finite() or value < 0:
        raise ValueError('Invalid observed stat')
    return value


def settle_final_props(ledger: Ledger, sport: str, schedule: dict) -> dict:
    """Settle supported props; uncertain finality, identity, or stats stay pending."""
    if sport not in STAT_COLUMNS or not isinstance(schedule.get('games'),list):
        raise ValueError('Invalid settlement scope')
    candidates=[row for row in ledger.predictions() if row.get('sport')==sport
        and (row.get('outcome') is None or row.get('outcome_source')==AUTO_SOURCE)]
    reasons=Counter();resolved=[]
    with ledger.connect() as db:
        for prediction in candidates:
            try:
                matched=_candidate(prediction,sport,schedule['games'])
                if matched is None:
                    reasons['final_game_not_matched']+=1
                    continue
                game,day,line=matched
                actual=_actual(db,prediction,sport,day)
                if actual is None:
                    reasons['stat_not_found_or_ambiguous']+=1
                    continue
                outcome='push' if actual==line else ((actual>line)==(prediction['direction']=='over'))
                resolved.append((prediction,game,outcome,actual))
            except (KeyError,TypeError,ValueError,ArithmeticError):
                reasons['invalid_prediction_or_evidence']+=1
    observed=utc_timestamp(schedule['captured_at'])
    for prediction,game,outcome,actual in resolved:
        evidence=dict(provider_event_id=game['provider_event_id'],date=game['date'],
            home_name=game['home_name'],away_name=game['away_name'],completed=True,
            game_time=game['game_time'],player_id=prediction['player_id'],
            prop_type=prediction['prop_type'],actual_value=str(actual))
        digest=hashlib.sha256(json.dumps(evidence,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        reference=f"espn:{game['provider_event_id']}:sha256:{digest}"
        ledger.settle({prediction['prediction_id']:outcome},source=AUTO_SOURCE,source_ref=reference,
            observed_at=observed,actual_values={prediction['prediction_id']:actual})
    return dict(sport=sport,status='complete' if schedule.get('status')=='complete' else 'degraded',
        candidates=len(candidates),settled=len(resolved),pending=len(candidates)-len(resolved),
        reasons=dict(sorted(reasons.items())),execution_ready=False)
