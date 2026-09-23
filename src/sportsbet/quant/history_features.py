"""Shared prior-history feature formula for frozen research and forward shadows."""
from __future__ import annotations

import math
import statistics

import numpy as np

FEATURES = ('base_logit', 'recent5_logit_delta', 'recent10_logit_delta',
            'recent_mean_delta', 'workload_log_ratio', 'log_days_since_game',
            'other_team_history_share')


def logit(p: float) -> float:
    return math.log(p / (1 - p))


def history_estimates(history: list[dict], stat: str, workload: str | None, target_day, line: float) -> dict:
    """Exact frozen formula. Callers enforce identity, cutoff, sample and eligibility."""
    values = np.asarray([float(r[stat]) for r in history])
    weights = np.exp2(-np.arange(len(values)-1, -1, -1) / 16)
    workload_ratio = (math.log((statistics.fmean(float(r[workload]) for r in history[-5:]) + 1)
                      / (statistics.fmean(float(r[workload]) for r in history) + 1)) if workload else 0.0)
    mean_delta = (float(values[-5:].mean()) - float(values.mean())) / max(1, float(values.std()))
    other_team = statistics.fmean(r['team'] != history[-1]['team'] for r in history)
    hits = values > line
    base = (float(hits.sum()) + .5) / (len(values) + 1)
    recent5 = (float(hits[-5:].sum()) + .5) / 6
    recent10 = (float(hits[-10:].sum()) + .5) / 11
    return dict(base=base, mean=float(values.mean()), sample=len(values),
        prior80=(float(hits.sum()) + 40) / (len(values) + 80),
        recency=(float(np.dot(weights, hits)) + .5) / (float(weights.sum()) + 1),
        features=(logit(base), logit(recent5)-logit(base), logit(recent10)-logit(base),
            mean_delta, max(-2, min(2, workload_ratio)),
            math.log1p((target_day-history[-1]['day']).days), other_team),
        role_drift=abs(workload_ratio) >= math.log(1.5) or abs(mean_delta) >= .5)
