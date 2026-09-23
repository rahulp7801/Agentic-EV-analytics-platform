"""Frozen, untraded history/workload predictions on already-collected exact offers."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import statistics

import numpy as np
from scipy.special import expit

from sportsbet.ingestion.provenance import stat_row_sha256
from sportsbet.quant.history_features import FEATURES, history_estimates, logit
from sportsbet.quant.history_shadow_params import ARTIFACT, ARTIFACT_SHA256

VERSION = ARTIFACT['model_version']
POLICY = ARTIFACT['policy_version']
FROZEN_AT = ARTIFACT['frozen_at']
MARKETS = {'nba': {'points': ('points','minutes',10), 'rebounds': ('rebounds','minutes',10),
                   'assists': ('assists','minutes',10)},
           'nfl': {'rec_yds': ('receiving_yards','targets',2), 'receptions': ('receptions','targets',2)}}
BINDING_FIELDS = ('sport','game_id','player_id','player','game_date','game_start_time',
    'home_team','away_team','prop_type','direction','line','sportsbook','american_odds',
    'quote_time','quote_source_provider','quote_source_sha256','quote_source_record_sha256',
    'model_version','model_probability','push_probability','model_sample_size','model_mean_stat',
    'forecast_cutoff','captured_at','model_generated_at')


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),
        default=str,allow_nan=False).encode()).hexdigest()


def offer_digest(payload: dict) -> str:
    from sportsbet.ledger import utc_timestamp
    values={key:payload.get(key) for key in BINDING_FIELDS}
    for key in ('game_start_time','quote_time','captured_at','model_generated_at'):
        values[key]=utc_timestamp(values[key]).isoformat()
    return digest(values)


@lru_cache(maxsize=1)
def implementation_sha256() -> str:
    return digest({name:hashlib.sha256(Path(__file__).with_name(name).read_text(encoding='utf-8-sig').encode()).hexdigest()
        for name in ('history_shadow.py','history_features.py','history_shadow_params.py')})


def parameters(sport: str, prop: str) -> dict:
    if digest(ARTIFACT)!=ARTIFACT_SHA256:
        raise ValueError('Frozen artifact integrity failure')
    params=ARTIFACT['models'][sport+':'+prop]
    if params['feature_names']!=list(FEATURES):
        raise ValueError('Frozen feature order mismatch')
    return params


def predicted_over(features, params, *, guard=True) -> float:
    x=np.asarray(features,dtype=float)
    scales=np.asarray(params['scales'])
    if x.shape!=(7,) or not np.isfinite(x).all() or np.any(scales<=0):
        raise ValueError('invalid_features')
    z=(x-np.asarray(params['means']))/scales
    if guard and np.max(np.abs(z))>8:
        raise ValueError('outside_frozen_feature_range')
    beta=np.asarray(params['coefficients'])
    return float(np.clip(expit(x[0]+beta[0]+z@beta[1:]),1e-12,1-1e-12))


async def load_histories(pool, sport: str, season: int, cutoff: date, requests: set[tuple[str,str]]) -> dict:
    """At most forty rows per player/market, in one read-only database snapshot."""
    supported=[(player,prop) for player,prop in requests if prop in MARKETS.get(sport,{})]
    if not supported:
        return {}
    if len({p for p,_ in supported})>200:
        raise ValueError('history_batch_too_large')
    result={}
    async with pool.acquire() as conn:
        async with conn.transaction(isolation='repeatable_read',readonly=True):
            for prop in sorted({prop for _,prop in supported}):
                players=sorted({player for player,market in supported if market==prop})
                stat=MARKETS[sport][prop][0]  # Constant allowlist only, never caller SQL.
                if sport=='nba':
                    query=f'''WITH history AS (SELECT player_id::text AS player,player_id,
                        game_id AS game,game_id,game_date AS day,game_date,season,
                        team_abbreviation AS team,team_abbreviation,points,rebounds,assists,minutes,
                        source_provider,source_sha256,source_record_sha256,source_observed_at,
                        row_number() OVER (PARTITION BY player_id ORDER BY game_date DESC,game_id DESC) rn
                        FROM nba_player_gamelogs WHERE player_id=ANY($1::bigint[])
                        AND season >= $2 AND season <= $3 AND game_date < $4 AND {stat} IS NOT NULL)
                        SELECT * FROM history WHERE rn<=40 ORDER BY player,day,game'''
                    ids=[int(player) for player in players]
                else:
                    query=f'''WITH history AS (SELECT ps.player_id AS player,ps.player_id,ps.season,
                        ps.week,ps.team,g.game_date AS day,g.game_id AS game,
                        ps.passing_yards,ps.rushing_yards,ps.receiving_yards,ps.receptions,ps.targets,
                        ps.source_provider,ps.source_sha256,ps.source_record_sha256,ps.source_observed_at,
                        row_number() OVER (PARTITION BY ps.player_id ORDER BY g.game_date DESC,g.game_id DESC) rn
                        FROM player_stats ps JOIN LATERAL (
                            SELECT min(game_date) game_date,min(game_id) game_id FROM games
                            WHERE season=ps.season AND week=ps.week
                            AND (home_team=ps.team OR away_team=ps.team) HAVING count(*)=1
                        ) g ON g.game_date IS NOT NULL
                        WHERE ps.player_id=ANY($1::text[]) AND ps.season >= $2 AND ps.season <= $3
                        AND g.game_date < $4 AND ps.{stat} IS NOT NULL)
                        SELECT * FROM history WHERE rn<=40 ORDER BY player,day,game'''
                    ids=players
                rows=await conn.fetch(query,ids,season-2,season,cutoff,timeout=4)
                for row in rows:
                    record=dict(row);record.pop('rn',None)
                    if record['player'] not in players:
                        raise ValueError('history_identity_mismatch')
                    result.setdefault((record['player'],prop),[]).append(record)
    return result


def _history(rows, payload, now):
    from sportsbet.ledger import utc_timestamp
    sport,prop=payload['sport'],payload['prop_type']
    stat,workload,minimum=MARKETS[sport][prop]
    target=date.fromisoformat(payload['game_date'])
    season=target.year if target.month >= (10 if sport=='nba' else 9) else target.year-1
    if not 20<=len(rows)<=40:
        raise ValueError('insufficient_history')
    rows=sorted(rows,key=lambda r:(r['day'],str(r['game'])))
    if len({str(r['game']) for r in rows})!=len(rows):
        raise ValueError('duplicate_history_game')
    provenance=Counter()
    for row in rows:
        if (str(row['player'])!=payload['player_id'] or not row['game']
                or type(row['day']) is not date or not row['day']<target
                or not season-2<=row['season']<=season or not isinstance(row['team'],str) or not row['team'].strip()):
            raise ValueError('invalid_history_identity_or_cutoff')
        for key in (stat,workload):
            value=row.get(key)
            if isinstance(value,bool) or value is None or not math.isfinite(float(value)):
                raise ValueError('missing_or_invalid_history')
        if (not float(row[stat]).is_integer() or float(row[workload])<0
                or (sport=='nba' and float(row[stat])<0)):
            raise ValueError('invalid_history_value')
        if row.get('source_observed_at') is not None and utc_timestamp(row['source_observed_at'])>now:
            raise ValueError('future_source_observation')
        if row.get('source_record_sha256'):
            if stat_row_sha256(sport,row)!=row['source_record_sha256']:
                raise ValueError('invalid_history_commitment')
            provenance['verified_core_stat_rows']+=1
        else:
            provenance['missing_core_stat_commitment']+=1
    if statistics.fmean(float(row[workload]) for row in rows[-5:])<minimum:
        raise ValueError('low_prior_workload')
    return rows,stat,workload,target,dict(provenance)


def _offer(payload):
    from sportsbet.ledger import quote_evidence_valid,settlement_identity_valid,utc_timestamp
    now=utc_timestamp(payload['captured_at'])
    line=float(payload['line'])
    if not math.isfinite(line) or line<.5 or not (line*2).is_integer() or line.is_integer():
        raise ValueError('unsupported_line')
    if (payload['model_version']!='empirical-jeffreys-v4' or payload['direction'] not in ('over','under')
            or payload.get('forecast_cutoff')!=payload['game_date']
            or float(payload.get('push_probability',-1))!=0):
        raise ValueError('unsupported_baseline')
    if not quote_evidence_valid(payload) or not settlement_identity_valid(payload):
        raise ValueError('invalid_exact_offer')
    if (not utc_timestamp(FROZEN_AT)<=now<utc_timestamp(payload['game_start_time'])
            or not 0<=(now-utc_timestamp(payload['quote_time'])).total_seconds()<=300
            or utc_timestamp(payload['model_generated_at'])!=now):
        raise ValueError('outside_prospective_quote_window')
    return now,line


def shadow_record(payload: dict, rows: list[dict], *, unavailable: str | None = None) -> dict:
    from sportsbet.ledger import utc_timestamp
    result=dict(model_version=VERSION,policy_version=POLICY,artifact_sha256=ARTIFACT_SHA256,
        implementation_sha256=implementation_sha256(),generated_at=utc_timestamp(payload['captured_at']).isoformat(),status='unavailable')
    if payload['prop_type'] not in MARKETS.get(payload['sport'],{}):
        return result|{'reason':'unsupported_market'}
    if unavailable:
        return result|{'reason':unavailable}
    try:
        params=parameters(payload['sport'],payload['prop_type'])
        now,line=_offer(payload)
        history,stat,workload,target,provenance=_history(rows,payload,now)
        estimate=history_estimates(history,stat,workload,target,line)
        side_base=estimate['base'] if payload['direction']=='over' else 1-estimate['base']
        if (payload['model_sample_size']!=estimate['sample']
                or abs(float(payload['model_probability'])-side_base)>1e-6
                or payload.get('model_mean_stat') is None
                or abs(float(payload['model_mean_stat'])-estimate['mean'])>.005001):
            raise ValueError('baseline_history_mismatch')
        # The half-line model is a step function; checking each historical stat's
        # transition suffices, including the initial half-line and upper tail.
        knots=sorted({.5}|{max(.5,math.floor(float(row[stat]))+.5) for row in history})
        curve=[predicted_over(history_estimates(history,stat,workload,target,k)['features'],params,guard=False)
               for k in knots]
        if any(later>earlier+1e-12 for earlier,later in zip(curve,curve[1:])):
            raise ValueError('nonmonotone_candidate')
        over=predicted_over(estimate['features'],params)
        result.update(status='predicted',probability=over if payload['direction']=='over' else 1-over,
            features=list(estimate['features']),sample_size=estimate['sample'],
            history_sha256=digest(history),core_stat_provenance=provenance,
            workload_source_commitment=False,
            offer_sha256=offer_digest(payload))
        result['record_sha256']=digest(result)
        return result
    except (KeyError,TypeError,ValueError,ArithmeticError) as exc:
        reasons={'unsupported_line','unsupported_baseline','invalid_exact_offer','outside_prospective_quote_window',
            'insufficient_history','duplicate_history_game','invalid_history_identity_or_cutoff',
            'missing_or_invalid_history','invalid_history_value','future_source_observation',
            'invalid_history_commitment','low_prior_workload','baseline_history_mismatch',
            'nonmonotone_candidate','outside_frozen_feature_range'}
        return result|{'status':'unavailable','reason':str(exc) if str(exc) in reasons else 'invalid_shadow_input'}


def verified_shadow_probability(payload: dict) -> float | None:
    """Reproduce the frozen inference and its binding to the immutable exact offer."""
    from sportsbet.ledger import utc_timestamp
    try:
        row=payload['history_shadow']
        if (row['status']!='predicted' or row['model_version']!=VERSION or row['policy_version']!=POLICY
                or row['artifact_sha256']!=ARTIFACT_SHA256 or row['implementation_sha256']!=implementation_sha256()
                or row['generated_at']!=utc_timestamp(payload['captured_at']).isoformat()
                or row['record_sha256']!=digest({k:v for k,v in row.items() if k!='record_sha256'})
                or row['offer_sha256']!=offer_digest(payload)):
            return None
        _offer(payload)
        features=row.get('features')
        if (not isinstance(features,list) or len(features)!=7
                or any(type(value) not in (int,float) or not math.isfinite(value) for value in features)):
            return None
        if type(row['sample_size']) is not int or row['sample_size']!=payload['model_sample_size'] or not 20<=row['sample_size']<=40:
            return None
        base=float(payload['model_probability'])
        base=base if payload['direction']=='over' else 1-base
        if abs(logit(base)-row['features'][0])>1e-4:
            return None
        over=predicted_over(row['features'],parameters(payload['sport'],payload['prop_type']))
        p=over if payload['direction']=='over' else 1-over
        if type(row['probability']) not in (int,float) or not math.isfinite(row['probability']) or abs(p-row['probability'])>1e-12:
            return None
        return p
    except (KeyError,TypeError,ValueError,ArithmeticError):
        return None



def verified_recorded_shadow_probability(payload: dict) -> float | None:
    """Require the ledger-assigned insertion timestamp as well as inference evidence."""
    from sportsbet.ledger import utc_timestamp
    try:
        receipt=utc_timestamp(payload['history_shadow_recorded_at'])
        if (not utc_timestamp(payload['captured_at'])<=receipt<utc_timestamp(payload['game_start_time'])
                or not 0<=(receipt-utc_timestamp(payload['quote_time'])).total_seconds()<=300):
            return None
        return verified_shadow_probability(payload)
    except (KeyError,TypeError,ValueError,ArithmeticError):
        return None
