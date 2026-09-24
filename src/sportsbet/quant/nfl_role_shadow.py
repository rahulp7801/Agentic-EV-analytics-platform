"""Frozen untraded NFL role-history shadow with an explicit receiving overlay."""
from __future__ import annotations
import csv
from datetime import date,datetime,timezone
from functools import lru_cache
import gzip
import hashlib
import io
import json
from pathlib import Path
import re

from sportsbet.ingestion.nfl_final_evidence import inspect_bundle
from sportsbet.ingestion.provenance import STAT_FIELDS
from sportsbet.quant.nfl_history_coverage import audit,SNAP_FIELDS
from sportsbet.quant.nfl_role_params import VERSION,POLICY,FROZEN_AT,SOURCE_SHA256,PRIOR_STRENGTH
from sportsbet.quant.history_shadow import _offer,offer_digest,digest

MARKETS={'nfl':{'receptions':'receptions','rec_yds':'receiving_yards'}}
ARTIFACT_SHA256=digest(dict(version=VERSION,policy=POLICY,frozen_at=FROZEN_AT,sources=SOURCE_SHA256,prior=PRIOR_STRENGTH))
PROVENANCE=('source_provider','source_sha256','source_record_sha256','source_observed_at')
REASONS=frozenset({'unsupported_market','outside_source_scope','history_read_failed','invalid_role_input',
    'incomplete_participation_history','conflicting_recovery','invalid_current_roster','no_current_role_history',
    'insufficient_history','baseline_history_mismatch','outside_prospective_quote_window','unsupported_line',
    'unsupported_baseline','invalid_exact_offer','invalid_or_late_recording','shadow_evaluation_failed'})

@lru_cache(maxsize=1)
def implementation_sha256():
    return digest({name:hashlib.sha256(Path(__file__).with_name(name).read_text(encoding='utf-8-sig').encode()).hexdigest()
        for name in ('nfl_role_shadow.py','nfl_role_params.py','nfl_history_coverage.py')})

@lru_cache(maxsize=1)
def artifact():
    raw=Path(__file__).with_name('nfl_role_sources.json.gz').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SOURCE_SHA256:raise ValueError('invalid_role_input')
    bundle=json.loads(gzip.decompress(raw));evidence=inspect_bundle(bundle)
    ids={e['player_id'] for e in evidence}
    players={r['gsis_id']:dict(player_id=r['gsis_id'],player=r['display_name'],pfr_player_id=r['pfr_id'],
        espn_player_id=r['espn_id'],current_quoted=True) for r in csv.DictReader(io.StringIO(bundle['identity']['response_text'])) if r['gsis_id'] in ids}
    if len(players)!=len(ids):raise ValueError('invalid_role_input')
    return bundle['identity'],players,evidence

async def load_inputs(pool,sport,season,cutoff,requests):
    if sport!='nfl':return {}
    _,players,_=artifact();ids=sorted(set(requests)&set(players))
    if not ids:return {}
    pfr=[players[k]['pfr_player_id'] for k in ids]
    async with pool.acquire() as conn:
        async with conn.transaction(isolation='repeatable_read',readonly=True):
            stats=await conn.fetch('''SELECT to_jsonb(ps) AS stat,g.game_id,g.game_date,g.home_team,g.away_team
                FROM player_stats ps LEFT JOIN games g ON g.season=ps.season AND g.week=ps.week
                AND ps.team IN (g.home_team,g.away_team) WHERE ps.player_id=ANY($1::text[])
                AND ps.season>=$2 AND ps.season<=$3 ORDER BY ps.player_id,ps.season,ps.week LIMIT 301''',ids,season-2,season,timeout=4)
            snaps=await conn.fetch('''SELECT to_jsonb(sc)-'id' AS snap,g.game_id,g.game_date,g.home_team,g.away_team
                FROM nfl_snap_counts sc LEFT JOIN games g ON g.game_id=sc.game_id
                WHERE sc.pfr_player_id=ANY($1::text[]) AND sc.season>=$2 AND sc.season<=$3
                ORDER BY sc.pfr_player_id,sc.season,sc.week LIMIT 301''',pfr,season-2,season,timeout=4)
    if len(stats)>300 or len(snaps)>300:raise ValueError('invalid_role_input')
    now=datetime.now(timezone.utc).isoformat();result={}
    for gsis in ids:
        value=dict(observed_at=now,cutoff=cutoff.isoformat(),season_floor=season-2,players=[players[gsis]],stats=[],snaps=[])
        for kind,records,field,fields in [('stats',stats,'stat',STAT_FIELDS['nfl']),('snaps',snaps,'snap',SNAP_FIELDS)]:
            for item in records:
                raw=item[field];row=json.loads(raw) if isinstance(raw,str) else raw
                if (row.get('player_id') if field=='stat' else row.get('pfr_player_id'))!=(gsis if field=='stat' else players[gsis]['pfr_player_id']):continue
                value[kind].append({k:str(item[k]) for k in ('game_id','game_date','home_team','away_team')}|{field:{k:row[k] for k in (*fields,*PROVENANCE)}})
        result[gsis]=value
    return result

@lru_cache(maxsize=64)
def validated_rows(encoded):
    data=json.loads(encoded);identity,players,evidence=artifact();data['identity']=identity
    coverage=audit(data,now=datetime.fromisoformat(data['observed_at']))
    player,=data['players'];gsis=player['player_id']
    if gsis not in players or player!=players[gsis]:raise ValueError('outside_source_scope')
    base={}
    for item in data['stats']:
        row=item['stat']
        if row['season']>=data['season_floor'] and item['game_date']<data['cutoff']:
            base[(row['season'],row['week'])]=dict(row,day=item['game_date'])
    merged=dict(base);added=0
    for e in evidence:
        row=e['stat_row'];key=(row['season'],row['week'])
        if e['player_id']!=gsis or not data['season_floor']<=row['season'] or e['game']['date']>=data['cutoff']:continue
        if datetime.fromisoformat(e['observed_at'])>datetime.fromisoformat(data['observed_at']):raise ValueError('invalid_role_input')
        if key in merged:
            if any(merged[key][k]!=row[k] for k in ('team','receptions','receiving_yards')):raise ValueError('conflicting_recovery')
        else:
            merged[key]=dict(row,day=e['game']['date'],explicit_recovery=True);added+=1
    for gap in coverage['missing_games']:
        if (gap['season'],gap['week']) not in merged:raise ValueError('incomplete_participation_history')
    # Both directions of participation coverage are required; missing snaps are unknown.
    participation={(s['snap']['season'],s['snap']['week']) for s in data['snaps'] if s['game_date']<data['cutoff']}
    if any(key not in participation for key in merged):raise ValueError('incomplete_participation_history')
    return list(base.values()),list(merged.values()),added


def probability(rows,stat,line,season,team):
    rows=sorted(rows,key=lambda r:(r['season'],r['week']))[-40:]
    if not 20<=len(rows)<=40:raise ValueError('insufficient_history')
    if any(type(r.get(stat)) not in (int,float) or not float(r[stat]).is_integer() or r[stat]<0 for r in rows):raise ValueError('invalid_role_input')
    current=[r for r in rows if r['season']==season and r['team']==team]
    older=[r for r in rows if r not in current]
    if not current:raise ValueError('no_current_role_history')
    prior=(sum(r[stat]>line for r in older)+.5)/(len(older)+1)
    p=(sum(r[stat]>line for r in current)+PRIOR_STRENGTH*prior)/(len(current)+PRIOR_STRENGTH)
    return p,dict(sample_size=len(rows),current_role_games=len(current),older_games=len(older),
        older_over_probability=prior,augmented_over_probability=(sum(r[stat]>line for r in rows)+.5)/(len(rows)+1))


def shadow_record(payload,inputs,*,unavailable=None):
    from sportsbet.ledger import utc_timestamp
    result=dict(model_version=VERSION,policy_version=POLICY,artifact_sha256=ARTIFACT_SHA256,
        implementation_sha256=implementation_sha256(),generated_at=payload.get('captured_at'),status='unavailable')
    try:
        if payload.get('sport')!='nfl' or payload.get('prop_type') not in MARKETS['nfl']:raise ValueError('unsupported_market')
        if payload['player_id'] not in artifact()[1]:raise ValueError('outside_source_scope')
        if unavailable:raise ValueError(unavailable)
        now,line=_offer(payload)
        result['generated_at']=now.isoformat()
        if len(inputs['players'])!=1 or inputs['players'][0]['player_id']!=payload['player_id'] or len(inputs['stats'])>80 or len(inputs['snaps'])>80:raise ValueError('invalid_role_input')
        if now<utc_timestamp(FROZEN_AT) or not 0<=(now-utc_timestamp(inputs['observed_at'])).total_seconds()<=300:raise ValueError('outside_prospective_quote_window')
        if inputs['cutoff']!=payload['game_date']:raise ValueError('invalid_role_input')
        target=date.fromisoformat(payload['game_date']);season=target.year if target.month>=9 else target.year-1
        if inputs['season_floor']!=season-2:raise ValueError('invalid_role_input')
        a=payload.get('availability',{});binding=artifact()[1][payload['player_id']]
        if (a.get('status')!='observed' or a.get('roster_confirmed') is not True
                or a.get('player_id')!=binding['espn_player_id'] or not re.fullmatch('[A-Z]{2,3}',a.get('team',''))
                or not 0<=(now-utc_timestamp(a['captured_at'])).total_seconds()<=3600
                or not re.fullmatch('[0-9a-f]{64}',a.get('roster_source_sha256',''))
                or not re.fullmatch(r'https://site\.api\.espn\.com/apis/site/v2/sports/football/nfl/teams/[1-9][0-9]*/roster',a.get('roster_source_url',''))):raise ValueError('invalid_current_roster')
        base,merged,added=validated_rows(json.dumps(inputs,sort_keys=True,separators=(',',':')))
        stat=MARKETS['nfl'][payload['prop_type']];baseline=sorted([r for r in base if r.get(stat) is not None],key=lambda r:(r['season'],r['week']))[-40:]
        p_base=(sum(r[stat]>line for r in baseline)+.5)/(len(baseline)+1)
        if not baseline or payload.get('model_mean_stat') is None or abs(float(payload['model_mean_stat'])-sum(r[stat] for r in baseline)/len(baseline))>.005001:raise ValueError('baseline_history_mismatch')
        if payload['model_sample_size']!=len(baseline) or abs(float(payload['model_probability'])-(p_base if payload['direction']=='over' else 1-p_base))>1e-6:raise ValueError('baseline_history_mismatch')
        p,counts=probability(merged,stat,line,season,{'LAR':'LA','WSH':'WAS'}.get(a['team'],a['team']))
        result.update(status='predicted',probability=p if payload['direction']=='over' else 1-p,
            counts=counts,recovered_games=added,inputs=inputs,offer_sha256=offer_digest(payload),availability_sha256=digest(a))
        result['record_sha256']=digest(result)
    except (KeyError,TypeError,ValueError,ArithmeticError) as exc:
        result.update(status='unavailable',reason=str(exc) if str(exc) in REASONS else 'invalid_role_input')
    return result


def verified_shadow_probability(payload):
    try:
        record=payload['role_history_shadow']
        if record.get('status')!='predicted':return None
        expected=shadow_record(payload,record['inputs'])
        return record['probability'] if digest(expected)==digest(record) else None
    except Exception:return None


def verified_recorded_shadow_probability(payload):
    from sportsbet.ledger import utc_timestamp
    try:
        receipt=utc_timestamp(payload['role_history_shadow_recorded_at'])
        if not utc_timestamp(payload['captured_at'])<=receipt<utc_timestamp(payload['game_start_time']) or not 0<=(receipt-utc_timestamp(payload['quote_time'])).total_seconds()<=300:return None
        return verified_shadow_probability(payload)
    except Exception:return None
