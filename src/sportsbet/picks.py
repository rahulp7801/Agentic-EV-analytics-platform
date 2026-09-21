"""Publish a deterministic pregame pick board from immutable prediction records."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sportsbet.arbitrage.ev import compute_expected_return, quote_terms
from sportsbet.ledger import (quote_evidence_valid, settlement_identity_valid,
                              utc_timestamp, verified_settlement_evidence)
from sportsbet.model_contract import MODEL_VERSION

LOCK_BEFORE_START = timedelta(minutes=60)
BOARD_POLICY_VERSION = 'pregame-t60-v1'
MAX_CURRENT_PICKS = 100
MAX_HISTORY_PICKS = 200


def _accepted(row: dict, sport: str) -> bool:
    try:
        probability = Decimal(str(row['model_probability']))
        push = Decimal(str(row.get('push_probability', 0)))
        interval = tuple(Decimal(str(value)) for value in row['model_confidence_interval'])
        mean = (Decimal(str(row['model_mean_stat']))
            if row.get('model_mean_stat') is not None else None)
        captured = utc_timestamp(row['captured_at'])
        quote_time = utc_timestamp(row['quote_time'])
        start = utc_timestamp(row['game_start_time'])
        stake = Decimal(str(row['stake_fraction']))
        _, payout = quote_terms(row['american_odds'], Decimal(0))
        return (row.get('sport') == sport and row.get('model_version') == MODEL_VERSION
            and row.get('accepted') is True and row.get('gate_reason') == 'accepted'
            and row.get('recommendation_policy_version') == 'confidence-floor-v2'
            and Decimal('0') < stake <= Decimal('.05')
            and Decimal('0') <= probability <= Decimal('1')-push
            and (mean is None or (mean.is_finite()
                and Decimal('0') <= mean <= Decimal('99999.99')))
            and len(interval) == 2 and Decimal('0') <= interval[0] <= probability <= interval[1] <= Decimal('1')-push
            and interval[0] > quote_terms(row['american_odds'], Decimal(0))[0] * (Decimal('1')-push)
            and compute_expected_return(probability, payout, push) > 0
            and quote_time <= captured < start and start-captured <= timedelta(hours=48)
            and quote_evidence_valid(row) and settlement_identity_valid(row))
    except (ArithmeticError, KeyError, TypeError, ValueError):
        return False


def _signal(row: dict, state: str, lock_at: datetime) -> dict:
    implied, payout = quote_terms(row['american_odds'], Decimal(0))
    probability = Decimal(str(row['model_probability']))
    push = Decimal(str(row.get('push_probability', 0)))
    return dict(
        id=row['prediction_id'], prediction_id=row['prediction_id'], player=row['player'],
        player_id=row['player_id'], sport=row['sport'], game_id=row['game_id'],
        game_date=row['game_date'], home_team=row['home_team'], away_team=row['away_team'],
        team='', opponent='', prop_type=row['prop_type'], direction=row['direction'],
        line=float(row['line']), sportsbook=row['sportsbook'], american_odds=row['american_odds'],
        true_prob=float(probability), implied_prob=float(implied*(Decimal('1')-push)),
        ev_pct=float(probability-implied*(Decimal('1')-push)),
        expected_return=float(compute_expected_return(probability, payout, push)),
        push_probability=float(push), confidence_interval=[float(value) for value in row['model_confidence_interval']],
        sample_size=row['model_sample_size'],
        mean_stat=float(row['model_mean_stat']) if row.get('model_mean_stat') is not None else None,
        model_version=row['model_version'],
        kelly_fraction=float(row['stake_fraction']), gated=False, gate_reason='accepted',
        snapped_at=utc_timestamp(row['quote_time']).isoformat(),
        captured_at=utc_timestamp(row['captured_at']).isoformat(),
        game_start_time=utc_timestamp(row['game_start_time']).isoformat(),
        lock_at=lock_at.isoformat(), board_state=state,
        selection_policy_version=BOARD_POLICY_VERSION, strength='unrated',
        trade_plan=row.get('trade_plan', []), injury_flags={},
        market_type=row['prop_type'], availability=row.get('availability'),
        forecast_cutoff=row.get('forecast_cutoff'),
        **({'next_gen_stats':row['next_gen_stats']} if row.get('next_gen_stats') else {}),
    )


def build_pick_board(rows: list[dict], sport: str, now: datetime | None = None) -> dict:
    """Select one prospective recommendation per player/game at the fixed T-60 cutoff."""
    if sport not in ('nfl', 'nba', 'cfb'):
        raise ValueError('Unsupported pick-board sport')
    observed = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    accepted = [row for row in rows if _accepted(row, sport)]
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in accepted:
        groups.setdefault((row['game_id'], str(row['player_id'])), []).append(row)

    current=[]
    history=[]
    for candidates in groups.values():
        identities={(row['player'],str(row['player_id']),row['home_team'],row['away_team'],
            row['game_date'],utc_timestamp(row['game_start_time'])) for row in candidates}
        if len(identities) != 1:
            continue
        start=utc_timestamp(candidates[0]['game_start_time'])
        lock_at=start-LOCK_BEFORE_START
        cutoff=min(observed, lock_at)
        eligible=[row for row in candidates if utc_timestamp(row['captured_at']) <= cutoff]
        if not eligible:
            continue
        selected=max(eligible,key=lambda row:(utc_timestamp(row['captured_at']),
            Decimal(str(row['model_probability'])),Decimal(str(row['stake_fraction'])),row['prediction_id']))
        if observed < lock_at:
            current.append(_signal(selected,'recorded',lock_at))
            continue
        signal=_signal(selected,'locked' if observed < start else 'final',lock_at)
        if observed < start:
            current.append(signal)
            continue
        verified = selected.get('outcome') is not None and verified_settlement_evidence(
            selected,selected.get('outcome'),selected.get('outcome_source'),selected.get('outcome_ref'),
            selected.get('outcome_observed_at'),selected.get('actual_value'),selected.get('outcome_evidence'))
        signal.update(result=('win' if selected['outcome'] is True else 'loss' if selected['outcome'] is False
            else selected['outcome']) if verified else 'pending', result_verified=verified,
            actual_value=selected.get('actual_value') if verified else None,
            settled_at=selected.get('outcome_observed_at') if verified else None)
        history.append(signal)

    current.sort(key=lambda row:(row['true_prob'],row['expected_return'],row['sample_size']),reverse=True)
    history.sort(key=lambda row:(row['result_verified'],row['true_prob'],row['game_start_time']),reverse=True)
    current=current[:MAX_CURRENT_PICKS]
    history=history[:MAX_HISTORY_PICKS]
    settled=sum(row['result_verified'] for row in history)
    wins=sum(row.get('result')=='win' for row in history)
    losses=sum(row.get('result')=='loss' for row in history)
    return dict(schema_version=1,sport=sport,generated_at=observed.isoformat(),
        lock_minutes=int(LOCK_BEFORE_START.total_seconds()/60),selection_policy_version=BOARD_POLICY_VERSION,
        current=current,history=history,
        summary=dict(current=len(current),settled=settled,pending=len(history)-settled,wins=wins,
            losses=losses,pushes=sum(row.get('result')=='push' for row in history),
            verified_win_rate=(wins/(wins+losses) if wins+losses else None)))
