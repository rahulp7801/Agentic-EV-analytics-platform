import importlib
import sys

import pytest

from sportsbet.config import DEFAULT_DAILY_CREDIT_LIMIT, settings
from sportsbet.ledger import Ledger


@pytest.mark.parametrize('module_name',['daily','scan','market_watch'])
@pytest.mark.parametrize('requested',[None,8])
def test_all_collector_commands_default_to_twenty_and_allow_lower_limits(monkeypatch,module_name,requested):
    module=importlib.import_module('sportsbet.'+module_name)
    seen=[]
    async def run(*args,**kwargs):
        seen.append(args[2] if module_name=='daily' else args[1])
        if module_name=='daily':return {'status':'complete'}
        if module_name=='scan':return {'nfl':{'status':'complete'}}
        return {'sources':{'sportsbook':{'status':'observed'}},'comparisons':[]},{}
    monkeypatch.setattr(module,'run',run)
    argv=[module_name,'--sport','nfl']
    if requested is not None:argv+=['--daily-credit-limit',str(requested)]
    monkeypatch.setattr(sys,'argv',argv)
    module.main()
    assert seen==[20 if requested is None else requested]
    assert DEFAULT_DAILY_CREDIT_LIMIT==20


def test_default_atomic_reservation_keeps_reserve_and_stops_at_twenty(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,'odds_rolling_credit_limit',450)
    ledger=Ledger(tmp_path/'default-budget.sqlite')
    assert ledger.reserve_api_credits(12,holdback=8)
    assert ledger.reserve_api_credits_with_reason(1,holdback=8)==(False,'pregame_credit_reserve')
    assert ledger.reserve_api_credits(8)
    assert ledger.reserve_api_credits_with_reason(1)==(False,'daily_credit_limit')
    with ledger.connect() as db:
        assert db.execute('SELECT SUM(credits) FROM api_usage').fetchone()[0]==20
