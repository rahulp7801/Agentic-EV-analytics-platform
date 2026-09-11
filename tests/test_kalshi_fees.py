"""Public fee terms and arithmetic fixtures, not trading performance."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal

import httpx
import pytest

from sportsbet.arbitrage.kalshi_fees import fee_terms,taker_buy_cost
from sportsbet.ingestion.kalshi import KalshiReader

NOW=datetime(2026,9,11,12,tzinfo=timezone.utc)


def context():
    return dict(status='observed',received_at=NOW.isoformat(),
        series={'ticker':'KXNFLGAME','fee_type':'quadratic_with_maker_fees','fee_multiplier':1,
            'last_updated_ts':(NOW-timedelta(days=1)).isoformat()},
        series_changes={'series_fee_change_arr':[]},event_changes={'event_fee_changes':[],'cursor':''})


def change(**updates):
    return dict(event_ticker='EVENT',series_ticker='KXNFLGAME',fee_type_override='quadratic',
        fee_multiplier_override=2,scheduled_ts=(NOW-timedelta(hours=1)).isoformat())|updates


def test_effective_event_override_clear_future_and_fail_closed():
    data=context()
    assert fee_terms(data,'EVENT',NOW)==('quadratic_with_maker_fees',Decimal(1))
    data['event_changes']['event_fee_changes']=[change(),change(scheduled_ts=(NOW+timedelta(hours=1)).isoformat(),fee_multiplier_override=8)]
    assert fee_terms(data,'EVENT',NOW)==('quadratic',Decimal(2))
    data['event_changes']['event_fee_changes'].append(change(scheduled_ts=NOW.isoformat(),fee_type_override=None,fee_multiplier_override=None))
    assert fee_terms(data,'EVENT',NOW)==('quadratic_with_maker_fees',Decimal(1))
    for invalid in (change(event_ticker='OTHER'),change(fee_type_override='unknown'),change(fee_multiplier_override=None),
                    change(fee_multiplier_override=True),change(fee_multiplier_override='NaN')):
        data=context();data['event_changes']['event_fee_changes']=[invalid]
        with pytest.raises(ValueError):fee_terms(data,'EVENT',NOW)
    data=context();data['event_changes']['cursor']='another-page'
    with pytest.raises(ValueError,match='Incomplete'):fee_terms(data,'EVENT',NOW)
    data=context();data['event_changes']['event_fee_changes']=[change(),change(fee_multiplier_override=3)]
    with pytest.raises(ValueError,match='Ambiguous'):fee_terms(data,'EVENT',NOW)


def test_series_transition_and_stale_or_future_fee_evidence():
    data=context()
    data['series_changes']['series_fee_change_arr']=[dict(series_ticker='KXNFLGAME',fee_type='quadratic',fee_multiplier=3,
        scheduled_ts=(NOW+timedelta(seconds=1)).isoformat())]
    with pytest.raises(ValueError,match='changed during'):fee_terms(data,'EVENT',NOW+timedelta(seconds=2))
    data['series_changes']['series_fee_change_arr'][0]['scheduled_ts']=(NOW-timedelta(hours=1)).isoformat()
    with pytest.raises(ValueError,match='disagrees'):fee_terms(data,'EVENT',NOW)
    with pytest.raises(ValueError,match='future or stale'):fee_terms(context(),'EVENT',NOW-timedelta(seconds=1))
    with pytest.raises(ValueError,match='future or stale'):fee_terms(context(),'EVENT',NOW+timedelta(seconds=301))


def test_single_fill_rounds_balance_not_fee_and_keeps_account_scenarios_separate():
    # Published general fee table: 100 contracts at $0.50 costs $1.75 in fees.
    result=taker_buy_cost(Decimal('.5'),Decimal(100),Decimal(1),Decimal('.01'))
    assert Decimal(result['exchange_fee'])==Decimal('1.75')
    direct=taker_buy_cost(Decimal('.5'),Decimal(1),Decimal(1),Decimal('.0001'))
    indirect=taker_buy_cost(Decimal('.5'),Decimal(1),Decimal(1),Decimal('.01'))
    assert Decimal(direct['exchange_fee'])==Decimal('.0175')
    assert Decimal(indirect['exchange_fee'])==Decimal('.02')
    # At fractional quantity, rounding the fee alone would give the wrong balance.
    result=taker_buy_cost(Decimal('.55'),Decimal('.1'),Decimal(1),Decimal('.01'))
    assert Decimal(result['principal'])==Decimal('.055')
    assert Decimal(result['total_cost'])==Decimal('.06')
    assert Decimal(result['exchange_fee'])==Decimal('.005')
    assert Decimal(result['trade_fee'])+Decimal(result['rounding_fee'])==Decimal(result['exchange_fee'])
    for bad in (Decimal('NaN'),Decimal('-1'),Decimal('1')):
        with pytest.raises(ValueError):taker_buy_cost(bad,Decimal(1),Decimal(1),Decimal('.01'))


@pytest.mark.asyncio
async def test_fee_readers_use_public_get_and_preserve_incomplete_history():
    paths=[]
    def handler(request):
        assert request.method=='GET' and 'KALSHI-ACCESS-KEY' not in request.headers
        paths.append(request.url.path)
        if '/series/' in request.url.path:
            assert request.url.params['show_historical']=='true'
            return httpx.Response(200,json={'series_fee_change_arr':[]})
        assert request.url.params['event_ticker']=='EVENT'
        return httpx.Response(200,json={'event_fee_changes':[],'cursor':'next'})
    async with KalshiReader(transport=httpx.MockTransport(handler)) as reader:
        await reader.series_fee_changes('KXNFLGAME')
        assert (await reader.event_fee_changes('EVENT'))['cursor']=='next'
    assert paths==['/trade-api/v2/series/fee_changes','/trade-api/v2/events/fee_changes']
