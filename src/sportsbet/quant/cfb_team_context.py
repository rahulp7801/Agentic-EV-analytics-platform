"""Exploratory CFB last-observed-team comparison; never a live model or pick."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
import psycopg
from psycopg.rows import dict_row

from sportsbet.quant.audit_storage import audit_database_url
from sportsbet.quant.history_tuning import PROPS, QUERIES, build_examples, compare, score, source_summary

PROTOCOL = '2026-09-25-cfb-team-context-exploratory-v1'
PRIOR_STRENGTH = 20


def team_estimate(history: list[dict], stat: str, line: float) -> dict:
    """The latest contiguous observed team segment defines context, never the target team."""
    if not 20 <= len(history) <= 40 or not math.isfinite(line) or line < .5 or line % 1 != .5:
        raise ValueError('Invalid research history or threshold')
    if any(not isinstance(r.get('team'), str) or not r['team'].strip() for r in history):
        raise ValueError('Missing prior team identity')
    values = [r.get(stat) for r in history]
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError('Missing or invalid category observation')
    if len({r['game'] for r in history}) != len(history) or any(
            a['day'] > b['day'] for a, b in zip(history, history[1:])):
        raise ValueError('Invalid history chronology or duplicate game')
    hits = [v > line for v in values]
    base = (sum(hits) + .5) / (len(hits) + 1)
    boundary = len(history) - 1
    while boundary > 0 and history[boundary-1]['team'] == history[-1]['team']:
        boundary -= 1
    current = len(history) - boundary
    if boundary:
        older = (sum(hits[:boundary]) + .5) / (boundary + 1)
        probability = (sum(hits[boundary:]) + PRIOR_STRENGTH * older) / (current + PRIOR_STRENGTH)
    else:
        probability = base
    return dict(probability=probability, baseline=base, sample=len(history),
                current_segment_games=current, older_segment_games=boundary)


def candidate_examples(rows: list[dict], prop: str):
    examples, coverage = build_examples(rows, 'cfb', prop)
    players = defaultdict(list)
    targets = {}
    for row in rows:
        players[str(row['player'])].append(row)
        key = (str(row['player']), str(row['game']))
        if key in targets:
            raise ValueError('Duplicate player/game history')
        targets[key] = row
    for history in players.values():
        history.sort(key=lambda r: (r['day'], str(r['game'])))
    stat = PROPS['cfb'][prop][0]
    probabilities, contexts = [], []
    for example in examples:
        target = targets[example.player, example.game]
        history = [r for r in players[example.player] if r['day'] < example.day
                   and r['season'] >= target['season'] - 2 and r.get(stat) is not None][-40:]
        estimate = team_estimate(history, stat, example.line)
        if estimate['sample'] != example.sample or abs(estimate['baseline'] - example.base) > 1e-12:
            raise ValueError('Research baseline reconstruction mismatch')
        probabilities.append(estimate['probability'])
        contexts.append(estimate['older_segment_games'] > 0)
    return examples, np.asarray(probabilities), contexts, coverage


def audit_rows(rows: list[dict]) -> dict:
    sources = source_summary(rows, 'cfb')
    if sources['provenance'].get('verified_core_stat_commitment', 0) != len(rows) or any(
            r.get('source_provider') != 'sportsdataverse_espn'
            or not re.fullmatch('[a-f0-9]{64}', str(r.get('source_sha256', '')))
            or r.get('team') != r.get('team_abbreviation')
            or str(r.get('game')) != str(r.get('game_id'))
            or r.get('day') != r.get('game_date')
            or str(r.get('player')) != str(r.get('athlete_id')) for r in rows):
        raise ValueError('Invalid source commitment or research identity')
    digest = hashlib.sha256()
    for row in rows:
        digest.update(json.dumps(row, sort_keys=True, default=str, separators=(',', ':')).encode())
        digest.update(b'\n')
    report = dict(protocol=PROTOCOL, generated_at=datetime.now(timezone.utc).isoformat(),
        prior_strength=PRIOR_STRENGTH, promote=False, read_only=True,
        scope='Post-hoc exploratory research on reused historical outcomes; no priced or prospective claim.',
        history=sources, input_sha256=digest.hexdigest(), markets={})
    for prop in PROPS['cfb']:
        examples, candidate, contexts, coverage = candidate_examples(rows, prop)
        partitions = {}
        for split in ('fit', 'select', 'evaluate'):
            groups = {}
            for name in ('all', 'team_transition'):
                indexes = [i for i, e in enumerate(examples) if e.split == split
                           and (name == 'all' or contexts[i])]
                cohort = [examples[i] for i in indexes]
                base = np.asarray([e.base for e in cohort])
                groups[name] = dict(baseline=score(cohort, base),
                    candidate=score(cohort, candidate[indexes]),
                    comparison=compare(cohort, base, candidate[indexes]) if cohort else None,
                    promote=False)
            partitions[split] = groups
        report['markets'][prop] = dict(coverage=coverage, partitions=partitions, promote=False)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv()
    try:
        dsn = audit_database_url().replace('postgresql+psycopg://', 'postgresql://', 1)
        with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=15,
                options='-c default_transaction_read_only=on -c statement_timeout=120000') as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            rows = conn.execute(QUERIES['cfb']).fetchall()
        report = audit_rows(rows)
        report['implementation_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        print(json.dumps({prop:result['partitions']['evaluate']['all']['comparison']
            for prop,result in report['markets'].items()}))
    except Exception as exc:
        raise SystemExit(f'Team-context audit unavailable: {type(exc).__name__}') from None


if __name__ == '__main__':
    main()
