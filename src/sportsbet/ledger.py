"""Durable prediction audit and atomic recommendation exposure budget (SQLite)."""
from __future__ import annotations
import argparse
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from sportsbet.config import settings
from datetime import datetime, timezone
from pathlib import Path
from decimal import Decimal
from sportsbet.graph.models import EVSignal, QuantResult
from sportsbet.quant.backtest import BacktestSignal, BacktestEngine

DEFAULT_PATH = Path('.checkpoints/analytics.sqlite')


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
            db.execute('CREATE TABLE IF NOT EXISTS predictions (id TEXT PRIMARY KEY, scan_id TEXT NOT NULL, payload TEXT NOT NULL, outcome TEXT)')
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


    def reserve(self, signal: EVSignal, line: float | None, limit: float = 0.05, risk_day: str | None = None) -> tuple[bool, str]:
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
        if cost < 1 or limit < 1:
            return False
        day = datetime.now(timezone.utc).date().isoformat()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT credits FROM api_usage WHERE risk_day=?', (day,)).fetchone()
            if (row[0] if row else 0) + cost > limit:
                return False
            db.execute('INSERT INTO api_usage VALUES (?,?) ON CONFLICT(risk_day) DO UPDATE SET credits=api_usage.credits+excluded.credits', (day,cost))
        return True

    @staticmethod
    def quote_identity(payload):
        return json.dumps([payload.get(k) for k in ('game_id','player','prop_type','direction','line','sportsbook')])

    def record(self, scan_id: str, payload: dict) -> str:
        payload = dict(payload)
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

    def settle(self, outcomes: dict) -> None:
        with self.connect() as db:
            for key, outcome in outcomes.items():
                if outcome is not None and type(outcome) is not bool and outcome not in ('push','void'):
                    raise ValueError('Settlement must be true/false/push/void/null')
                if db.execute('UPDATE predictions SET outcome=? WHERE id=?', (json.dumps(outcome), key)).rowcount != 1:
                    raise ValueError(f'Unknown prediction ID: {key}')

    def predictions(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute('SELECT id,payload,outcome FROM predictions ORDER BY id').fetchall()
        return [{'prediction_id':key, **json.loads(payload), 'outcome':json.loads(outcome) if outcome else None} for key,payload,outcome in rows]

    def report(self, recommendations_only: bool = False, model_version: str | None = None) -> dict:
        from dataclasses import fields
        from sportsbet.arbitrage.ev import quote_terms
        with self.connect() as db:
            records = db.execute('SELECT id,payload,outcome FROM predictions').fetchall()
        signals = []
        excluded = 0
        duplicate = 0
        seen = set()
        parsed = []
        versions = set()
        for prediction_id, raw, outcome in records:
            p = json.loads(raw)
            version = p.get('model_version') or 'unversioned'
            versions.add(version)
            if model_version is not None and version != model_version:
                continue
            if recommendations_only and not p.get('accepted'):
                continue
            # Without recorded actual tipoff/entry, no trustworthy historical evaluation.
            if not p.get('game_start_time') or not p.get('captured_at') or p.get('model_probability') is None:
                excluded += 1
                continue
            try:
                start = utc_timestamp(p['game_start_time'])
                entered = utc_timestamp(p['captured_at'])
                quote_time = utc_timestamp(p.get('quote_time') or p['captured_at'])
                generated = utc_timestamp(p.get('model_generated_at') or p['captured_at'])
                probability = Decimal(str(p['model_probability']))
                push = Decimal(str(p.get('push_probability',0)))
                stake = Decimal(str(p.get('stake_fraction',0))) if recommendations_only else Decimal(1)
                if not stake.is_finite() or stake < 0:
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
            parsed.append((entered,prediction_id,start,p,outcome))
        # UTC chronology, not lexical ISO strings with different offsets.
        parsed.sort(key=lambda row: (row[0], row[1]))
        for entered,_,start,p,outcome in parsed:
            selection = tuple(p.get(k) for k in ('game_id','player','prop_type','direction','line'))
            if selection in seen:
                duplicate += 1
                continue
            seen.add(selection)
            with self.connect() as db:
                closing = db.execute('SELECT captured_at,probability FROM quotes WHERE identity=? AND captured_at>? AND captured_at<? ORDER BY captured_at DESC LIMIT 1',
                    (self.quote_identity(p), entered.astimezone(timezone.utc).isoformat(),start.astimezone(timezone.utc).isoformat())).fetchone()
            close = closing[1] if closing else None
            signals.append(BacktestSignal(
                QuantResult(true_probability=Decimal(str(p['model_probability']))),
                Decimal(str(close)) if close is not None else None,
                json.loads(outcome) if outcome is not None else None,
                Decimal(str(p.get('stake_fraction',0))) if recommendations_only else Decimal('1'),
                quote_terms(p['american_odds'],Decimal(0))[1]+1, start,
                datetime.fromisoformat(closing[0] if closing else p['captured_at']), entered,
                push_probability=Decimal(str(p.get('push_probability',0))),
            ))
        report = BacktestEngine().run(signals)
        return {**{f.name:getattr(report,f.name) for f in fields(report) if f.name!='signals_df'},
                'excluded_missing_metadata':excluded, 'duplicate_predictions':duplicate,
                'cohort':'recommendations' if recommendations_only else 'all_predictions',
                'model_version':model_version, 'available_model_versions':sorted(versions),
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
        ledger.settle(json.loads(Path(args.settlements).read_text(encoding='utf-8-sig')))
    print(json.dumps(ledger.predictions() if args.list else ledger.report(args.recommendations_only,args.model_version),indent=2))

if __name__=='__main__':
    main()
