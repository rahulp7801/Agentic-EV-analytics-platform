"""Read-only temporal audit of history, recency and workload; no production writes.

Raw history stays in memory. Output is aggregate diagnostics and fitted parameters,
never player records, sportsbook recommendations, or a profitability assertion.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics

import numpy as np
import psycopg
from psycopg.rows import dict_row
from scipy.optimize import minimize
from scipy.special import expit

from sportsbet.ingestion.provenance import stat_row_sha256
from sportsbet.quant.backtest import _game_cluster_ratio_interval, calibration_metrics

FEATURES = ('base_logit', 'recent5_logit_delta', 'recent10_logit_delta',
            'recent_mean_delta', 'workload_log_ratio', 'log_days_since_game',
            'other_team_history_share')
BASE = 'rolling40_jeffreys'
CANDIDATES = (BASE, 'prior80', 'half_life16', 'logistic_l2_0.01', 'logistic_l2_0.1')
PROPS = {
    'nba': {'points': ('points', 'minutes', 10), 'rebounds': ('rebounds', 'minutes', 10),
            'assists': ('assists', 'minutes', 10)},
    'nfl': {'pass_yds': ('passing_yards', 'attempts', 10),
            'rush_yds': ('rushing_yards', 'carries', 3),
            'rec_yds': ('receiving_yards', 'targets', 2), 'receptions': ('receptions', 'targets', 2)},
    'cfb': {'pass_yds': ('passing_yards', None, 0), 'rush_yds': ('rushing_yards', None, 0),
            'rec_yds': ('receiving_yards', None, 0), 'receptions': ('receptions', None, 0)},
}


def partition(sport: str, day: date, season: int) -> str | None:
    if sport == 'nfl':
        if season == 2024:
            return 'fit'
        if date(2025, 9, 1) <= day < date(2025, 11, 1):
            return 'select'
        if date(2025, 11, 1) <= day < date(2026, 2, 15):
            return 'evaluate'
    elif sport == 'nba':
        if season == 2024:
            return 'fit'
        if date(2025, 10, 1) <= day < date(2026, 1, 1):
            return 'select'
        if date(2026, 1, 1) <= day < date(2026, 5, 1):
            return 'evaluate'
    elif sport == 'cfb':
        if season == 2025 and day < date(2025, 11, 1):
            return 'fit'
        if date(2025, 11, 1) <= day < date(2025, 12, 1):
            return 'select'
        if date(2025, 12, 1) <= day < date(2026, 9, 23):
            return 'evaluate'
    else:
        raise ValueError('Unsupported sport')
    return None


def logit(p: float) -> float:
    return math.log(p / (1 - p))


@dataclass(frozen=True)
class Example:
    split: str
    game: str
    player: str
    day: date
    line: float
    outcome: int
    base: float
    prior80: float
    recency: float
    features: tuple[float, ...]
    sample: int
    role_drift: bool


def build_examples(rows: list[dict], sport: str, prop: str) -> tuple[list[Example], dict]:
    stat, workload, minimum = PROPS[sport][prop]
    players = defaultdict(list)
    excluded = Counter()
    for row in rows:
        if not isinstance(row.get('day'), date) or not row.get('game'):
            excluded['missing_or_ambiguous_schedule'] += 1
            continue
        players[str(row['player'])].append(row)
    examples = []
    for player, observations in sorted(players.items()):
        observations.sort(key=lambda r: (r['day'], str(r['game'])))
        if len({str(r['game']) for r in observations}) != len(observations):
            raise ValueError('Duplicate player/game history')
        for target in observations:
            split = partition(sport, target['day'], target['season'])
            if split is None:
                continue
            # A missing observed category remains missing, never a zero or DNP.
            if target.get(stat) is None:
                excluded[split + ':missing_target_category'] += 1
                continue
            history = [r for r in observations if r['day'] < target['day']
                       and r['season'] >= target['season'] - 2 and r.get(stat) is not None][-40:]
            if len(history) < 20:
                excluded[split + ':fewer_than20'] += 1
                continue
            if workload:
                work = [r.get(workload) for r in history]
                if any(v is None or not math.isfinite(float(v)) or float(v) < 0 for v in work):
                    excluded[split + ':missing_workload'] += 1
                    continue
                if statistics.fmean(float(v) for v in work[-5:]) < minimum:
                    excluded[split + ':low_prior_workload'] += 1
                    continue
            values = np.asarray([float(r[stat]) for r in history])
            actual = float(target[stat])
            if not np.isfinite(values).all() or not math.isfinite(actual):
                raise ValueError('Nonfinite historical value')
            lines = sorted({max(0.5, math.floor(float(np.quantile(values[-10:], q))) + 0.5)
                            for q in (.25, .5, .75)})
            weights = np.exp2(-np.arange(len(values)-1, -1, -1) / 16)
            workload_ratio = (math.log((statistics.fmean(float(r[workload]) for r in history[-5:]) + 1)
                             / (statistics.fmean(float(r[workload]) for r in history) + 1))
                              if workload else 0.0)
            mean_delta = (float(values[-5:].mean()) - float(values.mean())) / max(1, float(values.std()))
            other_team = statistics.fmean(r['team'] != history[-1]['team'] for r in history)
            for line in lines:
                hits = values > line
                base = (float(hits.sum()) + .5) / (len(values) + 1)
                recent5 = (float(hits[-5:].sum()) + .5) / 6
                recent10 = (float(hits[-10:].sum()) + .5) / 11
                features = (logit(base), logit(recent5)-logit(base), logit(recent10)-logit(base),
                            mean_delta, max(-2, min(2, workload_ratio)),
                            math.log1p((target['day']-history[-1]['day']).days), other_team)
                examples.append(Example(split, str(target['game']), player, target['day'], line,
                    int(actual > line), base, (float(hits.sum()) + 40) / (len(values) + 80),
                    (float(np.dot(weights, hits)) + .5) / (float(weights.sum()) + 1),
                    features, len(values), abs(workload_ratio) >= math.log(1.5) or abs(mean_delta) >= .5))
    examples.sort(key=lambda e: (e.day, e.game, e.player, e.line))
    return examples, {'excluded': dict(sorted(excluded.items())),
                     'definition': 'Observed stat-category outcomes, conditional on prior-history coverage and workload'}


def game_weights(examples: list[Example]) -> np.ndarray:
    """Equal game weight, then equal player/game weight, then equal line weight."""
    lines = Counter((e.game, e.player) for e in examples)
    players = defaultdict(set)
    for e in examples:
        players[e.game].add(e.player)
    return np.asarray([1 / (len(players[e.game]) * lines[e.game, e.player]) for e in examples])


@dataclass(frozen=True)
class Correction:
    means: np.ndarray
    scales: np.ndarray
    coefficients: np.ndarray

    def predict(self, examples: list[Example]) -> np.ndarray:
        x = (np.asarray([e.features for e in examples])-self.means)/self.scales
        design = np.column_stack((np.ones(len(examples)), x))
        offset = np.asarray([logit(e.base) for e in examples])
        return np.clip(expit(offset + design @ self.coefficients), 1e-12, 1-1e-12)

    def metadata(self) -> dict:
        return {'feature_names': list(FEATURES), 'means': self.means.tolist(),
                'scales': self.scales.tolist(), 'coefficients': self.coefficients.tolist()}


def fit_correction(examples: list[Example], penalty: float) -> Correction:
    if len(examples) < 2 or penalty <= 0:
        raise ValueError('Insufficient training examples or invalid penalty')
    x = np.asarray([e.features for e in examples])
    w = game_weights(examples)
    w /= w.sum()
    means = np.average(x, axis=0, weights=w)
    scales = np.maximum(np.sqrt(np.average((x-means)**2, axis=0, weights=w)), 1e-6)
    design = np.column_stack((np.ones(len(examples)), (x-means)/scales))
    y = np.asarray([e.outcome for e in examples])
    offset = np.asarray([logit(e.base) for e in examples])
    def objective(beta):
        score = offset + design @ beta
        loss = np.dot(w, np.logaddexp(0, score)-y*score) + penalty*np.dot(beta[1:], beta[1:])/2
        gradient = design.T @ (w*(expit(score)-y))
        gradient[1:] += penalty*beta[1:]
        return loss, gradient
    fitted = minimize(objective, np.zeros(design.shape[1]), jac=True, method='L-BFGS-B',
                      options={'maxiter': 300, 'ftol': 1e-12, 'gtol': 1e-8})
    if not fitted.success or not np.isfinite(fitted.x).all():
        raise ValueError('Correction fit did not converge')
    return Correction(means, scales, fitted.x)


def probabilities(name: str, examples: list[Example], fitted: dict[str, Correction]) -> np.ndarray:
    if name in fitted:
        return fitted[name].predict(examples)
    field = {BASE: 'base', 'prior80': 'prior80', 'half_life16': 'recency'}[name]
    return np.asarray([getattr(e, field) for e in examples])


def score(examples: list[Example], p: np.ndarray) -> dict:
    if not examples:
        return {'examples': 0, 'games': 0, 'players': 0}
    if len(examples) != len(p) or not np.isfinite(p).all() or np.any((p <= 0) | (p >= 1)):
        raise ValueError('Invalid research probabilities')
    w = game_weights(examples)
    y = np.asarray([e.outcome for e in examples])
    plain = calibration_metrics(list(zip(p.tolist(), y.tolist(), strict=True)))
    return {'examples': len(examples), 'player_games': len({(e.player, e.game) for e in examples}),
        'games': len({e.game for e in examples}), 'players': len({e.player for e in examples}),
        'game_balanced_brier': float(np.average((p-y)**2, weights=w)),
        'game_balanced_log_loss': float(np.average(-(y*np.log(p)+(1-y)*np.log1p(-p)), weights=w)),
        'row_weighted_brier': plain['brier_score'], 'row_weighted_log_loss': plain['log_loss'],
        'row_weighted_calibration_error': plain['calibration_error'], 'calibration_bins': plain['calibration']}


def compare(examples: list[Example], base: np.ndarray, candidate: np.ndarray) -> dict:
    w = game_weights(examples)
    y = np.asarray([e.outcome for e in examples])
    deltas = {'brier': (candidate-y)**2-(base-y)**2,
              'log_loss': -(y*np.log(candidate)+(1-y)*np.log1p(-candidate))
                          +(y*np.log(base)+(1-y)*np.log1p(-base))}
    result = {}
    for metric, differences in deltas.items():
        result[metric+'_difference'] = float(np.average(differences, weights=w))
        for cluster in ('game', 'player'):
            _, interval = _game_cluster_ratio_interval([
                (getattr(e, cluster), float(weight*delta), float(weight))
                for e, weight, delta in zip(examples, w, differences, strict=True)])
            result[metric+'_'+cluster+'_95'] = list(interval) if interval else None
    return result


def evaluate_examples(examples: list[Example]) -> dict:
    groups = {split: [e for e in examples if e.split == split] for split in ('fit', 'select', 'evaluate')}
    counts = {split: {'examples': len(rows), 'games': len({e.game for e in rows})}
              for split, rows in groups.items()}
    if any(row['examples'] < 100 or row['games'] < 10 for row in counts.values()):
        return {'status': 'insufficient_data', 'counts': counts, 'promote': False}
    fitted = {f'logistic_l2_{penalty}': fit_correction(groups['fit'], penalty) for penalty in (.01, .1)}
    selection = {name: score(groups['select'], probabilities(name, groups['select'], fitted))
                 for name in CANDIDATES}
    selected = min(CANDIDATES, key=lambda name: (selection[name]['game_balanced_brier'], CANDIDATES.index(name)))
    held = groups['evaluate']
    base, candidate = probabilities(BASE, held, fitted), probabilities(selected, held, fitted)
    differences = compare(held, base, candidate)
    supported = selected != BASE and all(differences[metric+'_'+cluster+'_95'] is not None
        and differences[metric+'_'+cluster+'_95'][1] < 0
        for metric in ('brier', 'log_loss') for cluster in ('game', 'player'))
    drift = [i for i, e in enumerate(held) if e.role_drift]
    return {'status': 'evaluated', 'counts': counts, 'selected': selected, 'selection_scores': selection,
        'evaluation_baseline': score(held, base), 'evaluation_candidate': score(held, candidate),
        'paired_comparison': differences, 'shadow_research_supported': supported, 'promote': False,
        'evaluation_role_drift': {'baseline': score([held[i] for i in drift], base[drift]),
                                  'candidate': score([held[i] for i in drift], candidate[drift])},
        'fitted_corrections': {key: fit.metadata() for key, fit in fitted.items()}}


QUERIES = {
'nfl': '''SELECT ps.player_id AS player, ps.player_id,ps.season,ps.week,ps.team,
    g.game_date AS day,g.game_id AS game,ps.passing_yards,ps.rushing_yards,ps.receiving_yards,
    ps.receptions,ps.attempts,ps.carries,ps.targets,ps.source_provider,
    ps.source_sha256,ps.source_record_sha256 FROM player_stats ps
    LEFT JOIN LATERAL (SELECT min(game_date) game_date,min(game_id) game_id
        FROM games WHERE season=ps.season AND week=ps.week
        AND (home_team=ps.team OR away_team=ps.team) HAVING count(*)=1) g ON true
    WHERE ps.season BETWEEN 2023 AND 2025 ORDER BY ps.player_id,ps.season,ps.week''',
'nba': '''SELECT player_id::text AS player,player_id,season,game_date AS day,game_date,
    game_id AS game,game_id,team_abbreviation AS team,team_abbreviation,points,rebounds,
    assists,minutes,source_provider,source_sha256,source_record_sha256
    FROM nba_player_gamelogs WHERE season BETWEEN 2024 AND 2025
    ORDER BY player_id,game_date,game_id''',
'cfb': '''SELECT athlete_id::text AS player,athlete_id,season,week,game_date AS day,game_date,
    game_id AS game,game_id,team_abbreviation AS team,team_abbreviation,team_id,team_name,
    opponent_id,opponent_name,opponent_abbreviation,is_home,player_name,
    passing_yards,rushing_yards,receiving_yards,receptions,
    source_provider,source_sha256,source_record_sha256 FROM cfb_player_gamelogs
    WHERE season BETWEEN 2024 AND 2026 AND game_date<'2026-09-23'
    ORDER BY athlete_id,game_date,game_id''',
}


def source_summary(rows: list[dict], sport: str) -> dict:
    counts = Counter()
    for row in rows:
        if not row.get('source_record_sha256'):
            counts['missing_row_commitment'] += 1
        else:
            try:
                valid = stat_row_sha256(sport, row) == row['source_record_sha256']
            except (TypeError, ValueError):
                valid = False
            counts['verified_core_stat_commitment' if valid else 'mismatched_core_stat_commitment'] += 1
    return {'rows': len(rows), 'seasons': dict(sorted(Counter(str(r['season']) for r in rows).items())),
            'provenance': dict(counts), 'missing_categories': {
                prop: sum(r[fields[0]] is None for r in rows) for prop, fields in PROPS[sport].items()},
            'workload_fields_covered_by_stat_commitment': False}


def run_audit(database_url: str, sports: list[str]) -> dict:
    if not sports or len(sports) != len(set(sports)) or any(s not in PROPS for s in sports):
        raise ValueError('Invalid sport scope')
    report = {'protocol': '2026-09-23-model-audit-protocol', 'read_only': True,
              'generated_at': datetime.now(timezone.utc).isoformat(), 'sports': {},
              'limitations': ['Retrospective temporal split; some outcomes appeared in prior research.',
                'Research thresholds are generated from prior history, not historical sportsbook offers.',
                'Missing stat categories and DNP outcomes are not inferred; participating-row cohort.',
                'Historical source corrections may postdate games; source hashes do not prove pregame availability.',
                'Separate game/player clustered intervals do not fully model all cross-cluster dependence.',
                'No candidate is promoted; no ROI, CLV, calibrated live stake or betting-edge claim.']}
    dsn = database_url.replace('postgresql+psycopg://', 'postgresql://', 1)
    with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=15,
                        options='-c default_transaction_read_only=on -c statement_timeout=120000') as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        for sport in sports:
            rows = conn.execute(QUERIES[sport]).fetchall()
            # Commit to precisely the in-memory corpus; never persist its raw records.
            digest = hashlib.sha256()
            for row in rows:
                digest.update(json.dumps(row, sort_keys=True, default=str, separators=(',', ':')).encode())
                digest.update(b'\n')
            result = {'history': source_summary(rows, sport), 'input_sha256': digest.hexdigest(), 'props': {}}
            for prop in PROPS[sport]:
                examples, coverage = build_examples(rows, sport, prop)
                result['props'][prop] = evaluate_examples(examples) | {'coverage': coverage}
                print(f'{sport}/{prop}: {result["props"][prop]["status"]}', flush=True)
            report['sports'][sport] = result
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sport', choices=tuple(PROPS)+('all',), default='all')
    parser.add_argument('--database-env', default='DATABASE_URL')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Configuration is read only; no dotenv value or connection exception is echoed.
    from dotenv import load_dotenv
    load_dotenv()
    try:
        report = run_audit(os.environ[args.database_env], list(PROPS) if args.sport == 'all' else [args.sport])
        report['source_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    except Exception as exc:
        print(f'Audit unavailable: {type(exc).__name__}')
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
