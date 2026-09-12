"""Durable prediction audit and atomic recommendation exposure budget (SQLite)."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from sportsbet.config import settings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from decimal import Decimal
from sportsbet.graph.models import EVSignal, QuantResult
from sportsbet.model_contract import MODEL_VERSION, PROP_MARKETS, QUOTE_PROVENANCE_MODEL_VERSIONS
from sportsbet.quant.backtest import BacktestSignal, BacktestEngine

DEFAULT_PATH = Path('.checkpoints/analytics.sqlite')
MAX_RECOMMENDATION_FRACTION = Decimal('0.05')
VERIFIED_SETTLEMENT_SOURCE = 'observed_final_stats'
SETTLEMENT_REF = re.compile(
    r'^espn_schedule\+(nba|espn|nflverse):([^:]{1,80}):sha256:([0-9a-f]{64})$')
STAT_COLUMNS = {
    'nba': {'points': 'points', 'rebounds': 'rebounds', 'assists': 'assists'},
    'nfl': {'pass_yds': 'passing_yards', 'rush_yds': 'rushing_yards',
            'rec_yds': 'receiving_yards', 'receptions': 'receptions'},
}


def json_object(value):
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
        return decoded if isinstance(decoded, dict) else None
    except (TypeError, ValueError):
        return None


def normalized_model_version(payload: dict) -> str:
    value=payload.get('model_version')
    if value in (None,''):
        return 'unversioned'
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,80}',value):
        raise ValueError('Model version is invalid')
    return value


def validated_selection(payload: dict) -> tuple[str,str,str,str,Decimal,str]:
    limits=(('game_id',64),('player',100),('prop_type',40),('sportsbook',50))
    if any(not isinstance(payload.get(field),str) or not payload[field].strip()
            or len(payload[field])>limit for field,limit in limits):
        raise ValueError('Selection identity is invalid')
    direction=payload.get('direction')
    if direction not in ('over','under'):
        raise ValueError('Selection direction is invalid')
    try:
        line=Decimal(str(payload['line']))
    except (ArithmeticError,KeyError,ValueError):
        raise ValueError('Selection line is invalid') from None
    if not line.is_finite() or not 0 <= line <= Decimal('99999.99'):
        raise ValueError('Selection line is invalid')
    return (payload['game_id'],payload['player'],payload['prop_type'],direction,line,
        payload['sportsbook'])


def quote_evidence_valid(payload: dict) -> bool:
    """Validate source commitments for every scanner cohort that requires them."""
    batch=payload.get('quote_source_sha256')
    record=payload.get('quote_source_record_sha256')
    shaped = (payload.get('model_version') in QUOTE_PROVENANCE_MODEL_VERSIONS
        and payload.get('quote_source_provider') == 'the_odds_api'
        and isinstance(payload.get('model_generated_at'),str)
        and isinstance(batch,str) and bool(re.fullmatch('[0-9a-f]{64}',batch))
        and isinstance(record,str) and bool(re.fullmatch('[0-9a-f]{64}',record)))
    if not shaped:
        return False
    try:
        from sportsbet.ingestion.prop_odds import PlayerPropSnapshotCreate, prop_quote_evidence_valid
        from sportsbet.quant.vig import american_to_raw_prob
        sport=payload['sport']
        markets=PROP_MARKETS[sport]
        provider_markets=[market for market,prop in markets.items() if prop==payload['prop_type']]
        if len(provider_markets)!=1:
            return False
        price=payload['american_odds']
        if type(price) is not int:
            return False
        snapshot=PlayerPropSnapshotCreate(
            sport=sport,game_id=payload['game_id'],player_name=payload['player'],
            sportsbook=payload['sportsbook'],prop_type=provider_markets[0],
            line=Decimal(str(payload['line'])),price=price,
            implied_probability=american_to_raw_prob(price),
            game_start_time=utc_timestamp(payload['game_start_time']),
            source_provider='the_odds_api',source_sha256=batch,
            source_record_sha256=record,
            snapped_at=utc_timestamp(payload['quote_time']),
            side=str(payload['direction']).title(),
        )
        return prop_quote_evidence_valid(snapshot)
    except (ArithmeticError, KeyError, TypeError, ValueError):
        return False


def verified_settlement_evidence(payload: dict, outcome, source, source_ref,
                                 observed_at, actual_value, evidence) -> bool:
    """Reproduce an automatic result from its retained schedule/stat evidence."""
    try:
        match = SETTLEMENT_REF.fullmatch(source_ref or '')
        proof = json_object(evidence)
        if source != VERIFIED_SETTLEMENT_SOURCE or not match or not isinstance(proof, dict):
            return False
        canonical = json.dumps(proof, sort_keys=True, separators=(',', ':'), allow_nan=False)
        if hashlib.sha256(canonical.encode()).hexdigest() != match.group(3):
            return False
        sport = payload['sport']
        column = STAT_COLUMNS[sport][payload['prop_type']]
        row = proof['stat_row']
        if (match.group(1) != proof['stat_provider'] or match.group(2) != proof['provider_event_id']
                or proof.get('completed') is not True or proof.get('date') != payload['game_date']
                or proof.get('home_name') != payload['home_team']
                or proof.get('away_name') != payload['away_team']
                or str(proof.get('player_id')) != str(payload['player_id'])
                or proof.get('prop_type') != payload['prop_type']
                or not isinstance(row, dict)
                or not re.fullmatch('[0-9a-f]{64}', proof.get('stat_source_sha256', ''))
                or not re.fullmatch('[0-9a-f]{64}', proof.get('stat_record_sha256', ''))):
            return False
        identity_version=proof.get('schedule_identity_version',1)
        if identity_version not in (1,2):
            return False
        if identity_version==2:
            from sportsbet.schedules import scheduled_stat_teams
            team_field='team_abbreviation' if sport=='nba' else 'team'
            if row.get(team_field) not in scheduled_stat_teams(sport,proof):
                return False
        from sportsbet.ingestion.provenance import stat_row_sha256
        if stat_row_sha256(sport, row) != proof['stat_record_sha256']:
            return False
        actual = Decimal(str(actual_value))
        if (not actual.is_finite() or actual != Decimal(str(proof['actual_value']))
                or actual != Decimal(str(row[column]))):
            return False
        line = Decimal(str(payload['line']))
        expected = 'push' if actual == line else ((actual > line) == (payload['direction'] == 'over'))
        if outcome != expected:
            return False
        game_time = utc_timestamp(proof['game_time'])
        stat_time = utc_timestamp(proof['stat_observed_at'])
        settlement_time = observed_at if isinstance(observed_at, datetime) else utc_timestamp(observed_at)
        return game_time <= stat_time <= settlement_time.astimezone(timezone.utc)
    except (ArithmeticError, KeyError, TypeError, ValueError):
        return False


def utc_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('Audit timestamps must include a timezone')
    return parsed.astimezone(timezone.utc)


class Ledger:
    def __init__(self, path: str | Path = DEFAULT_PATH, database_url: str | None = None):
        self.database_url = database_url or (settings.analytics_database_url if Path(path) == DEFAULT_PATH else None)
        if self.database_url:
            return
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS predictions (id TEXT PRIMARY KEY, scan_id TEXT NOT NULL, payload TEXT NOT NULL, outcome TEXT, outcome_source TEXT, outcome_ref TEXT, outcome_observed_at TEXT, actual_value REAL, outcome_evidence TEXT)')
            columns={row[1] for row in db.execute('PRAGMA table_info(predictions)').fetchall()}
            for name,kind in (('outcome_source','TEXT'),('outcome_ref','TEXT'),('outcome_observed_at','TEXT'),
                              ('actual_value','REAL'),('outcome_evidence','TEXT')):
                if name not in columns:
                    db.execute(f'ALTER TABLE predictions ADD COLUMN {name} {kind}')
            db.execute('CREATE TABLE IF NOT EXISTS exposure (identity TEXT PRIMARY KEY, group_key TEXT NOT NULL, risk_day TEXT NOT NULL, fraction REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS quotes (identity TEXT NOT NULL, captured_at TEXT NOT NULL, probability REAL NOT NULL, PRIMARY KEY(identity,captured_at))')
            db.execute('CREATE TABLE IF NOT EXISTS api_usage (risk_day TEXT PRIMARY KEY, credits INTEGER NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS exposure_day ON exposure(risk_day)')
            db.execute('CREATE INDEX IF NOT EXISTS exposure_group ON exposure(group_key)')

    @contextmanager
    def connect(self):
        if self.database_url:
            import psycopg
            conn = psycopg.connect(self.database_url.replace('postgresql+psycopg://','postgresql://'), connect_timeout=10)
            class Session:
                def execute(self, sql, args=()):
                    if sql == 'BEGIN IMMEDIATE':
                        return conn.execute('SELECT pg_advisory_xact_lock(739201)')
                    return conn.execute(sql.replace('?', '%s'), args)
            try:
                with conn:
                    conn.execute('SET LOCAL search_path TO analytics, public')
                    yield Session()
            finally:
                conn.close()
        else:
            conn = sqlite3.connect(self.path, timeout=15)
            try:
                with conn:
                    yield conn
            finally:
                conn.close()


    def reserve(self, signal: EVSignal, line: float | None,
                limit: float = float(MAX_RECOMMENDATION_FRACTION),
                risk_day: str | None = None) -> tuple[bool, str]:
        if not signal.game_id:
            return False, 'missing_game_identity'
        group = json.dumps([signal.game_id, signal.player_name or signal.market_type])
        identity = json.dumps([group, signal.market_type, signal.direction, line])
        day = risk_day or datetime.now(timezone.utc).date().isoformat()
        amount = float(signal.kelly_fraction)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            other = db.execute('SELECT identity FROM exposure WHERE group_key=? AND identity<>?', (group,identity)).fetchone()
            if other:
                return False, 'correlated_exposure'
            existing = db.execute('SELECT fraction, risk_day FROM exposure WHERE identity=?', (identity,)).fetchone()
            if existing and existing[1] != day:
                return False, 'previously_reserved'
            old = existing[0] if existing else 0
            delta = max(0, amount-old)
            total = db.execute('SELECT COALESCE(SUM(fraction),0) FROM exposure WHERE risk_day=?',(day,)).fetchone()[0]
            if total + delta > limit + 1e-12:
                return False, 'daily_exposure_limit'
            db.execute('INSERT INTO exposure VALUES (?,?,?,?) ON CONFLICT(identity) DO UPDATE SET fraction=CASE WHEN exposure.fraction > excluded.fraction THEN exposure.fraction ELSE excluded.fraction END',
                       (identity,group,day,amount))
        return True, 'accepted'

    def reserve_api_credits(self, cost: int, limit: int = 25) -> bool:
        if type(cost) is not int or type(limit) is not int or cost < 1 or limit < 1:
            return False
        today = datetime.now(timezone.utc).date()
        day = today.isoformat()
        window_start = (today-timedelta(days=30)).isoformat()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT credits FROM api_usage WHERE risk_day=?', (day,)).fetchone()
            if (row[0] if row else 0) + cost > limit:
                return False
            rolling = db.execute('SELECT COALESCE(SUM(credits),0) FROM api_usage WHERE risk_day>=? AND risk_day<=?',
                (window_start,day)).fetchone()[0]
            if rolling + cost > settings.odds_rolling_credit_limit:
                return False
            db.execute('INSERT INTO api_usage VALUES (?,?) ON CONFLICT(risk_day) DO UPDATE SET credits=api_usage.credits+excluded.credits', (day,cost))
        return True

    @staticmethod
    def quote_identity(payload):
        return json.dumps([payload.get(k) for k in ('game_id','player','prop_type','direction','line','sportsbook')])

    def record(self, scan_id: str, payload: dict) -> str:
        payload = dict(payload)
        if not isinstance(scan_id,str) or not scan_id.strip() or len(scan_id)>80:
            raise ValueError('Scan identity is invalid')
        validated_selection(payload)
        model_version=normalized_model_version(payload)
        if (model_version in QUOTE_PROVENANCE_MODEL_VERSIONS
                and not quote_evidence_valid(payload)):
            raise ValueError('Model prediction requires verified quote evidence')
        accepted=payload.get('accepted')
        if accepted is not None and type(accepted) is not bool:
            raise ValueError('Prediction acceptance must be boolean')
        if accepted is not None:
            try:
                stake=Decimal(str(payload.get('stake_fraction')))
            except (ArithmeticError,ValueError):
                raise ValueError('Prediction stake is invalid') from None
            if (not stake.is_finite() or stake < 0 or stake > MAX_RECOMMENDATION_FRACTION
                    or (accepted and stake == 0) or (not accepted and stake != 0)):
                raise ValueError('Prediction acceptance and stake are inconsistent')
        for field in ('captured_at','quote_time','game_start_time','model_generated_at'):
            if payload.get(field) is not None:
                payload[field] = utc_timestamp(payload[field]).isoformat()
        # Immutable per-scan, per-selection record; rescans retain separate predictions.
        identity = [scan_id, payload['game_id'], payload['player'], payload['prop_type'], payload['direction'], payload['line'], payload.get('sportsbook')]
        key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT payload FROM predictions WHERE id=?', (key,)).fetchone()
            if existing:
                if json.loads(existing[0]) != payload:
                    raise ValueError('Prediction identity already has different immutable evidence')
                return key
            if type(payload.get('american_odds')) is int and abs(payload['american_odds']) >= 100 and not payload.get('synthetic_price') and str(payload.get('sportsbook','')).lower() != 'prizepicks':
                from sportsbet.arbitrage.ev import quote_terms
                captured = payload.get('quote_time') or payload.get('captured_at')
                if captured and (not payload.get('captured_at') or utc_timestamp(captured) <= utc_timestamp(payload['captured_at'])):
                    captured = utc_timestamp(captured).isoformat()
                    probability = float(quote_terms(payload['american_odds'],Decimal(0))[0])
                    db.execute('INSERT INTO quotes VALUES (?,?,?) ON CONFLICT DO NOTHING', (self.quote_identity(payload),captured,probability))
            db.execute('INSERT INTO predictions(id,scan_id,payload) VALUES (?,?,?) ON CONFLICT DO NOTHING',
                       (key,scan_id,json.dumps(payload,allow_nan=False)))
        return key

    def settle(self, outcomes: dict, *, source: str = 'manual', source_ref: str = 'caller_supplied',
               observed_at: datetime | None = None, actual_values: dict | None = None,
               evidence: dict | None = None) -> None:
        if (not isinstance(source,str) or not source.strip() or len(source)>40
                or not isinstance(source_ref,str) or not source_ref.strip() or len(source_ref)>200):
            raise ValueError('Settlement provenance is invalid')
        stamp=observed_at or datetime.now(timezone.utc)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError('Settlement observation time requires a timezone')
        stamp=stamp.astimezone(timezone.utc)
        with self.connect() as db:
            for key, outcome in outcomes.items():
                if outcome is not None and type(outcome) is not bool and outcome not in ('push','void'):
                    raise ValueError('Settlement must be true/false/push/void/null')
                actual=(actual_values or {}).get(key)
                if actual is not None:
                    actual=Decimal(str(actual))
                    if not actual.is_finite():
                        raise ValueError('Settlement actual value is invalid')
                    actual=int(actual) if actual==actual.to_integral_value() else str(actual)
                row=db.execute('SELECT payload FROM predictions WHERE id=?',(key,)).fetchone()
                if row is None:
                    raise ValueError(f'Unknown prediction ID: {key}')
                proof=(evidence or {}).get(key)
                encoded=json.dumps(proof,sort_keys=True,separators=(',',':'),allow_nan=False) if proof is not None else None
                if source == VERIFIED_SETTLEMENT_SOURCE and not verified_settlement_evidence(
                        json.loads(row[0]),outcome,source,source_ref,stamp,actual,encoded):
                    raise ValueError('Verified settlement evidence is invalid')
                db.execute('UPDATE predictions SET outcome=?,outcome_source=?,outcome_ref=?,outcome_observed_at=?,actual_value=?,outcome_evidence=? WHERE id=?',
                    (json.dumps(outcome),source,source_ref,stamp.isoformat(),actual,encoded,key))

    def predictions(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute('SELECT id,payload,outcome,outcome_source,outcome_ref,outcome_observed_at,actual_value,outcome_evidence FROM predictions ORDER BY id').fetchall()
        result=[]
        for key,payload,outcome,source,ref,observed,actual,proof in rows:
            decoded=json_object(payload)
            if decoded is None:
                continue
            try:
                decoded_outcome=json.loads(outcome) if outcome is not None else None
            except (TypeError,ValueError):
                decoded_outcome=None
            try:
                decoded_actual=float(actual) if actual is not None else None
            except (TypeError,ValueError):
                decoded_actual=None
            result.append({'prediction_id':key,**decoded,'outcome':decoded_outcome,
                'outcome_source':source,'outcome_ref':ref,
                'outcome_observed_at':observed.isoformat() if isinstance(observed,datetime) else observed,
                'actual_value':decoded_actual,
                'outcome_evidence':json_object(proof)})
        return result

    def report(self, recommendations_only: bool = False, model_version: str | None = None) -> dict:
        from dataclasses import fields
        from sportsbet.arbitrage.ev import quote_terms
        with self.connect() as db:
            records = db.execute('SELECT id,payload,outcome,outcome_source,outcome_ref,outcome_observed_at,actual_value,outcome_evidence FROM predictions').fetchall()
        signals = []
        excluded = 0
        duplicate = 0
        invalid_closing = 0
        seen = set()
        parsed = []
        versions = set()
        unverified_settlements=0
        for prediction_id, raw, outcome, outcome_source, outcome_ref, outcome_observed, actual, proof in records:
            p = json_object(raw)
            if p is None:
                excluded += 1
                continue
            try:
                version=normalized_model_version(p)
            except ValueError:
                excluded += 1
                continue
            versions.add(version)
            if model_version is not None and version != model_version:
                continue
            if recommendations_only and p.get('accepted') is not True:
                continue
            decoded_outcome=None
            if outcome is not None:
                try:
                    decoded_outcome=json.loads(outcome)
                except (TypeError,ValueError):
                    unverified_settlements+=1
                else:
                    if not verified_settlement_evidence(
                            p,decoded_outcome,outcome_source,outcome_ref,outcome_observed,actual,proof):
                        decoded_outcome=None
                        unverified_settlements+=1
            # Without recorded actual tipoff/entry, no trustworthy historical evaluation.
            if not p.get('game_start_time') or not p.get('captured_at') or p.get('model_probability') is None:
                excluded += 1
                continue
            try:
                if (version in QUOTE_PROVENANCE_MODEL_VERSIONS
                        and not quote_evidence_valid(p)):
                    raise ValueError('Model quote evidence required')
                start = utc_timestamp(p['game_start_time'])
                entered = utc_timestamp(p['captured_at'])
                quote_time = utc_timestamp(p.get('quote_time') or p['captured_at'])
                generated = utc_timestamp(p.get('model_generated_at') or p['captured_at'])
                probability = Decimal(str(p['model_probability']))
                push = Decimal(str(p.get('push_probability',0)))
                stake = Decimal(str(p.get('stake_fraction',0))) if recommendations_only else Decimal(1)
                selection=validated_selection(p)[:5]
                if (not stake.is_finite() or stake < 0
                        or (recommendations_only
                            and not 0 < stake <= MAX_RECOMMENDATION_FRACTION)):
                    raise ValueError('Invalid recorded stake')
                if not probability.is_finite() or not push.is_finite() or not 0 <= probability <= 1 or not 0 <= push <= 1-probability:
                    raise ValueError('Invalid model probabilities')
                if type(p.get('american_odds')) is not int or abs(p['american_odds']) < 100:
                    raise ValueError('Actual American price required')
                quote_terms(p['american_odds'],Decimal(0))
            except (ValueError, TypeError, KeyError, ArithmeticError):
                excluded += 1
                continue
            if entered >= start or quote_time > entered or generated > entered or p.get('synthetic_price') or str(p.get('sportsbook','')).lower()=='prizepicks':
                excluded += 1
                continue
            parsed.append((entered,prediction_id,start,p,decoded_outcome,selection))
        # UTC chronology, not lexical ISO strings with different offsets.
        parsed.sort(key=lambda row: (row[0], row[1]))
        for entered,_,start,p,outcome,selection in parsed:
            if selection in seen:
                duplicate += 1
                continue
            seen.add(selection)
            with self.connect() as db:
                closing = db.execute('SELECT captured_at,probability FROM quotes WHERE identity=? AND captured_at>? AND captured_at<? ORDER BY captured_at DESC LIMIT 1',
                    (self.quote_identity(p), entered.astimezone(timezone.utc).isoformat(),start.astimezone(timezone.utc).isoformat())).fetchone()
            close = None
            closing_time = entered
            if closing:
                try:
                    closing_time = utc_timestamp(closing[0])
                    close = Decimal(str(closing[1]))
                    if not close.is_finite() or not 0 <= close <= 1 or not entered < closing_time < start:
                        raise ValueError('Invalid closing quote')
                except (ValueError, TypeError, ArithmeticError):
                    close, closing_time = None, entered
                    invalid_closing += 1
            signals.append(BacktestSignal(
                QuantResult(true_probability=Decimal(str(p['model_probability']))),
                close,
                outcome,
                Decimal(str(p.get('stake_fraction',0))) if recommendations_only else Decimal('1'),
                quote_terms(p['american_odds'],Decimal(0))[1]+1, start,
                closing_time, entered,
                push_probability=Decimal(str(p.get('push_probability',0))),
                game_cluster_id=p['game_id'],
            ))
        report = BacktestEngine().run(signals)
        return {**{f.name:getattr(report,f.name) for f in fields(report) if f.name!='signals_df'},
                'excluded_missing_metadata':excluded, 'duplicate_predictions':duplicate,
                'excluded_closing_quotes':invalid_closing,
                'cohort':'recommendations' if recommendations_only else 'all_predictions',
                'model_version':model_version, 'available_model_versions':sorted(versions),
                'unverified_settlements':unverified_settlements,
                'selection_policy':'Earliest eligible prediction per game/player/market/side/line within the selected cohort.',
                'profit_scope':'Hypothetical recorded-stake replay, not executed bets or realized account profit.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--path', default=str(DEFAULT_PATH))
    parser.add_argument('--settlements', help='JSON mapping prediction IDs to true/false/push/void/null')
    parser.add_argument('--list', action='store_true', help='Export prediction IDs and observations for settlement')
    parser.add_argument('--recommendations-only',action='store_true')
    parser.add_argument('--model-version',help='Report one recorded model version; use unversioned for legacy rows')
    args=parser.parse_args(); ledger=Ledger(args.path)
    if args.settlements:
        raw=Path(args.settlements).read_bytes()
        ledger.settle(json.loads(raw.decode('utf-8-sig')),
            source_ref='sha256:'+hashlib.sha256(raw).hexdigest())
    print(json.dumps(ledger.predictions() if args.list else ledger.report(args.recommendations_only,args.model_version),indent=2))

if __name__=='__main__':
    main()
