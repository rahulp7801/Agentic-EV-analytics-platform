"""Distinguish absent legacy metadata from contradictory reconstructed inputs.

Research diagnostics only. Partial agreement must never satisfy frozen prospective
input checks or be used to fill missing fields in the original forecast.
"""
from __future__ import annotations

import math


def baseline_evidence(payload: dict, estimate: dict) -> dict:
    if payload.get('direction') not in ('over', 'under'):
        raise ValueError('Invalid forecast direction')
    expected = {
        'model_sample_size': estimate['sample'],
        'model_probability': estimate['base'] if payload['direction']=='over' else 1-estimate['base'],
        'model_mean_stat': estimate['mean'],
        'push_probability': 0,
    }
    if (type(estimate['sample']) is not int or not 20 <= estimate['sample'] <= 40
            or not math.isfinite(float(estimate['base'])) or not 0 < estimate['base'] < 1
            or not math.isfinite(float(estimate['mean']))):
        raise ValueError('Invalid reconstructed baseline')
    tolerances = {'model_sample_size':0, 'model_probability':1e-6,
                  'model_mean_stat':.005001, 'push_probability':0}
    missing, invalid, conflicts = [], [], []
    for key, target in expected.items():
        value = payload.get(key)
        if value is None:
            missing.append(key)
            continue
        try:
            finite = not isinstance(value,bool) and math.isfinite(float(value))
        except (TypeError,ValueError,OverflowError):
            finite = False
        if (not finite or (key=='model_sample_size' and type(value) is not int)
                or (key in ('model_probability','push_probability') and not 0 <= float(value) <= 1)):
            invalid.append(key)
        elif abs(float(value)-target)>tolerances[key]:
            conflicts.append(key)
    if invalid or conflicts:
        status='conflict'
    elif not missing:
        status='complete_agreement'
    elif missing==['model_mean_stat']:
        status='partial_agreement_missing_mean'
    else:
        status='insufficient_metadata'
    return {'status':status,'missing_fields':missing,'invalid_fields':invalid,
            'conflicting_fields':conflicts,'prospective_eligible':False}
