"""Observed fee precedence and single-fill exchange cost scenarios, never fills."""
from datetime import datetime
from decimal import Decimal, ROUND_CEILING


def timestamp(value: str) -> datetime:
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.utcoffset() is None:
        raise ValueError('Fee evidence requires a timezone')
    return result


def fee_terms(context: dict, event_ticker: str, as_of: datetime) -> tuple[str, Decimal]:
    """Use captured current series terms plus the last effective event override."""
    if as_of.utcoffset() is None or context['status']!='observed':
        raise ValueError('Fee evidence is unavailable')
    observed=timestamp(context['received_at'])
    if not 0<=(as_of-observed).total_seconds()<=300:
        raise ValueError('Fee evidence is future or stale')
    series=context['series']
    if timestamp(series['last_updated_ts'])>observed:
        raise ValueError('Series metadata is from the future')
    kind,multiplier=series['fee_type'],series['fee_multiplier']
    scheduled=context['series_changes']['series_fee_change_arr']
    effective_series={}
    for change in scheduled:
        if change['series_ticker']!=series['ticker']:
            raise ValueError('Wrong series fee change')
        # Current metadata may predate a scheduled change during collection.
        when=timestamp(change['scheduled_ts'])
        if observed<when<=as_of:
            raise ValueError('Fees changed during collection; refresh required')
        if when<=observed:
            terms=(change['fee_type'],change['fee_multiplier'])
            if when in effective_series and effective_series[when]!=terms:
                raise ValueError('Ambiguous simultaneous series fees')
            effective_series[when]=terms
    if effective_series and effective_series[max(effective_series)]!=(kind,multiplier):
        raise ValueError('Series metadata disagrees with effective fee history')
    page=context['event_changes']
    if page.get('cursor'):
        raise ValueError('Incomplete event fee history')
    effective={}
    for change in page['event_fee_changes']:
        if change['event_ticker']!=event_ticker or change['series_ticker']!=series['ticker']:
            raise ValueError('Wrong event fee change')
        when=timestamp(change['scheduled_ts'])
        if when>as_of:
            continue
        terms=(change['fee_type_override'],change['fee_multiplier_override'])
        if when in effective and effective[when]!=terms:
            raise ValueError('Ambiguous simultaneous fee changes')
        effective[when]=terms
    if effective:
        override_type,override_multiplier=effective[max(effective)]
        if (override_type is None)!=(override_multiplier is None):
            raise ValueError('Incomplete event fee override')
        if override_type is not None:
            kind,multiplier=override_type,override_multiplier
    if kind not in ('quadratic','quadratic_with_maker_fees') or isinstance(multiplier,bool):
        raise ValueError('Unsupported fee model')
    multiplier=Decimal(str(multiplier))
    if not multiplier.is_finite() or not 0<=multiplier<=100:
        raise ValueError('Invalid fee multiplier')
    return kind,multiplier


def taker_buy_cost(price: Decimal, count: Decimal, multiplier: Decimal, precision: Decimal) -> dict:
    """One hypothetical fill, zero prior fee accumulator, excluding FCM/funding fees.

    Official fee-rounding rules round the model fee to six decimal dollars, then
    align the *total balance change*. Rounding the fee alone is incorrect for
    sub-cent prices. Actual multi-fill order fees need the exchange accumulator.
    """
    if any(not x.is_finite() for x in (price,count,multiplier,precision)) or not (
        0<price<1 and 0<count<=1_000_000 and 0<=multiplier<=100 and precision in (Decimal('.0001'),Decimal('.01'))):
        raise ValueError('Invalid fee scenario')
    principal=price*count
    model=Decimal('.07')*multiplier*count*price*(1-price)
    trade=model.quantize(Decimal('.000001'),rounding=ROUND_CEILING)
    total=((principal+trade)/precision).to_integral_value(rounding=ROUND_CEILING)*precision
    rounding=total-principal-trade
    return {'principal':str(principal),'trade_fee':str(trade),'rounding_fee':str(rounding),
        'exchange_fee':str(total-principal),'total_cost':str(total),'balance_precision':str(precision)}
