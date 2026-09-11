"""Bounded, long-only payoff optimization; results are scenarios, never fills."""
from __future__ import annotations

from decimal import Decimal
from math import inf
from typing import Annotated, Literal
import warnings

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from scipy.optimize import Bounds, LinearConstraint, milp

# SciPy intentionally forwards native HiGHS options but warns about them.
# Suppress only this exact, intentional option notice, not solver diagnostics.
warnings.filterwarnings('ignore',
    message=r"^Unrecognized options detected: \{'threads'\}\. These will be passed to HiGHS verbatim\.$",
    category=RuntimeWarning, module=r'^sportsbet\.arbitrage\.portfolio$')

Positive = Annotated[Decimal, Field(gt=0, le=1_000_000, allow_inf_nan=False)]
Nonnegative = Annotated[Decimal, Field(ge=0, le=1_000_000, allow_inf_nan=False)]
Identifier = Annotated[str, Field(min_length=1, max_length=200, pattern=r'\S')]


class PayoffLeg(BaseModel):
    """One independently available tranche. Units are contracts or whole entries.

    For a sportsbook, one unit can be one dollar staked. For PrizePicks it must
    represent a whole entry with its actual scenario payouts, not a single pick.
    Fees must be an explicit upper bound per unit, including rounding costs.
    """
    model_config = ConfigDict(extra='forbid', frozen=True)

    leg_id: Identifier
    venue: Literal['sportsbook', 'kalshi', 'prizepicks']
    account: Identifier
    quote_id: Identifier
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    rules_ref: Identifier
    observed_at: AwareDatetime
    available_at: AwareDatetime
    event_start: AwareDatetime
    unit_cost: Positive
    fee_per_unit_bound: Nonnegative | None = None
    max_units: Positive | None = None
    # Bound integer lot counts and floating solver precision at the input boundary.
    unit_step: Positive = Field(ge=Decimal('0.0001'))
    payouts: dict[Identifier, Nonnegative] = Field(min_length=2, max_length=256)

    @model_validator(mode='after')
    def valid_observation(self):
        if self.observed_at > self.available_at:
            raise ValueError('Observation cannot become available before it was observed')
        if self.max_units is not None and self.max_units < self.unit_step:
            raise ValueError('Depth is smaller than one available unit')
        return self


class PayoffCandidate(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    candidate_id: Identifier
    event_scope: Identifier
    # A trusted caller must review identity, full state coverage, and rule sources.
    # An LLM assertion or matching display names is not sufficient evidence.
    coverage_review_ref: Identifier | None = None
    states: list[Identifier] = Field(min_length=2, max_length=256)
    legs: list[PayoffLeg] = Field(min_length=2, max_length=16)

    @model_validator(mode='after')
    def unique_complete_states(self):
        if len(set(self.states)) != len(self.states):
            raise ValueError('Duplicate settlement state')
        if len({leg.leg_id for leg in self.legs}) != len(self.legs):
            raise ValueError('Duplicate leg identifier')
        if len({(leg.account, leg.quote_id) for leg in self.legs}) != len(self.legs):
            raise ValueError('Shared quote capacity cannot be counted twice')
        if any(set(leg.payouts) != set(self.states) for leg in self.legs):
            raise ValueError('Every leg needs a payout for every settlement state')
        return self


class MarketAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    as_of: AwareDatetime
    budget: Positive
    max_age_seconds: int = Field(default=5, ge=1, le=300)
    max_skew_seconds: int = Field(default=2, ge=0, le=30)
    candidates: list[PayoffCandidate] = Field(max_length=100)

    @model_validator(mode='after')
    def unique_candidates(self):
        if len({c.candidate_id for c in self.candidates}) != len(self.candidates):
            raise ValueError('Duplicate candidate identifier')
        return self


def specialist(candidate: PayoffCandidate) -> str:
    venues = {leg.venue for leg in candidate.legs}
    return 'prizepicks' if 'prizepicks' in venues else 'kalshi' if 'kalshi' in venues else 'sportsbook'


def analyze_candidate(candidate: PayoffCandidate, request: MarketAnalysisRequest) -> dict:
    result = dict(candidate_id=candidate.candidate_id, specialist=specialist(candidate),
        status='blocked', reasons=[], units={}, cost=None, state_profits={}, worst_profit=None,
        execution_ready=False)
    reasons = result['reasons']
    if not candidate.coverage_review_ref:
        reasons.append('unreviewed_settlement_coverage')
    for leg in candidate.legs:
        if leg.fee_per_unit_bound is None:
            reasons.append('unknown_fees')
        if leg.max_units is None:
            reasons.append('unknown_capacity')
        if leg.available_at > request.as_of:
            reasons.append('future_information')
        if (request.as_of - leg.observed_at).total_seconds() > request.max_age_seconds:
            reasons.append('stale_quote')
        if leg.event_start <= request.as_of:
            reasons.append('event_started')
    times = [leg.observed_at for leg in candidate.legs]
    if (max(times)-min(times)).total_seconds() > request.max_skew_seconds:
        reasons.append('quote_time_skew')
    result['reasons'] = sorted(set(reasons))
    if reasons:
        return result

    # Integer lot counts preserve whole contracts / entry sizes. Capital cannot
    # be reused between legs. Fees are conservative linear upper bounds.
    costs = [(leg.unit_cost + leg.fee_per_unit_bound) * leg.unit_step for leg in candidate.legs]
    profits = [[leg.payouts[state] * leg.unit_step - cost
                for leg, cost in zip(candidate.legs, costs)] for state in candidate.states]
    capacities = [int(leg.max_units // leg.unit_step) for leg in candidate.legs]
    rows = [[float(cost) for cost in costs] + [0.0]]
    rows += [[-float(p) for p in row] + [1.0] for row in profits]
    count = len(costs)
    solution = milp(c=[0.0]*count + [-1.0], integrality=[1]*count + [0],
        bounds=Bounds([0.0]*(count+1), capacities + [inf]),
        constraints=LinearConstraint(rows, -inf, [float(request.budget)] + [0.0]*len(profits)),
        # HiGHS otherwise creates a native scheduler sized from the host CPU.
        # Specialists already run concurrently; nested native pools stalled
        # repeated graph/CLI use on Windows. SciPy forwards this HiGHS option.
        options={'time_limit': 2.0, 'mip_rel_gap': 0.0, 'threads': 1})
    if not solution.success:
        result['reasons'] = ['optimizer_incomplete']
        return result
    lots = [round(float(n)) for n in solution.x[:count]]
    if any(abs(float(raw)-n) > 1e-5 for raw, n in zip(solution.x[:count], lots)):
        result['reasons'] = ['invalid_optimizer_rounding']
        return result
    # Recompute all money with Decimal; never trust a solver's floating tolerance
    # for budget, depth, or a claimed positive worst-case payoff.
    cost = sum((n*c for n, c in zip(lots, costs)), Decimal(0))
    state_profits = {state: sum((n*p for n, p in zip(lots, row)), Decimal(0))
                     for state, row in zip(candidate.states, profits)}
    if cost > request.budget or any(n < 0 or n > cap for n, cap in zip(lots, capacities)):
        result['reasons'] = ['invalid_optimizer_capacity']
        return result
    worst = min(state_profits.values())
    positive = cost > 0 and worst >= Decimal('0.01')
    result.update(status='scenario_edge' if positive else 'no_edge',
        units={leg.leg_id: str(n*leg.unit_step) for leg, n in zip(candidate.legs, lots) if n},
        cost=str(cost), state_profits={state: str(p) for state, p in state_profits.items()},
        worst_profit=str(worst))
    return result
