from datetime import datetime, timedelta, timezone
import pytest
from sportsbet.scan import next_quote_check, prop_credit_holdback
from sportsbet.ledger import Ledger

NOW=datetime(2026,9,20,12,tzinfo=timezone.utc)

@pytest.mark.parametrize('hours,interval',[(24,720),(4,120),(.5,15)])
def test_quote_requests_are_spaced_by_kickoff_distance(hours,interval):
    event={'commence_time':(NOW+timedelta(hours=hours)).isoformat()}
    assert next_quote_check(event,NOW.isoformat(),NOW)==NOW+timedelta(minutes=interval)

@pytest.mark.parametrize('hours',[6,1])
def test_entering_closer_kickoff_phase_requests_a_new_quote(hours):
    event={'commence_time':(NOW+timedelta(hours=hours)).isoformat()}
    assert next_quote_check(event,(NOW-timedelta(minutes=1)).isoformat(),NOW)==NOW

@pytest.mark.parametrize('stamp',[None,'invalid','2026-09-21T12:00:00Z','2026-09-20T12:00:00'])
def test_missing_invalid_or_future_attempts_do_not_postpone_collection(stamp):
    assert next_quote_check({'commence_time':(NOW+timedelta(days=1)).isoformat()},stamp,NOW)==NOW

def test_next_check_is_bounded_by_transition_to_pregame_window():
    assert next_quote_check({'commence_time':(NOW+timedelta(hours=7)).isoformat()},NOW.isoformat(),NOW)==NOW+timedelta(hours=1)

def test_budget_holdback_protects_credits_without_spending_them(tmp_path,monkeypatch):
    from sportsbet.config import settings
    monkeypatch.setattr(settings,'odds_rolling_credit_limit',450)
    ledger=Ledger(tmp_path/'credits.sqlite')
    assert prop_credit_holdback(['nba','nfl'],25)==8
    assert prop_credit_holdback(['nba'],25)==6
    assert prop_credit_holdback(['nfl'],4)==0
    assert ledger.reserve_api_credits(4,12,holdback=8)
    assert not ledger.reserve_api_credits(1,12,holdback=8)
    assert ledger.reserve_api_credits(8,12)
    assert not ledger.reserve_api_credits(1,12)

def test_rolling_budget_also_retains_pregame_credits(tmp_path,monkeypatch):
    from sportsbet.config import settings
    monkeypatch.setattr(settings,'odds_rolling_credit_limit',12)
    ledger=Ledger(tmp_path/'rolling.sqlite')
    assert ledger.reserve_api_credits(4,25,holdback=8)
    assert not ledger.reserve_api_credits(1,25,holdback=8)
    assert ledger.reserve_api_credits(8,25)



@pytest.mark.parametrize('daily,older,rolling_limit,holdback,expected',[
    (11,0,450,8,'pregame_credit_reserve'),
    (17,0,450,8,'daily_credit_limit'),
    (11,438,450,8,'rolling_credit_limit'),
    (4,438,450,8,'pregame_credit_reserve'),
    (11,0,450,0,'reserved'),
    (8,0,450,8,'reserved'),
])
def test_credit_reason_preserves_exact_allowance_policy(tmp_path,monkeypatch,daily,older,rolling_limit,holdback,expected):
    from sportsbet.config import settings
    monkeypatch.setattr(settings,'odds_rolling_credit_limit',rolling_limit)
    ledger=Ledger(tmp_path/'reason.sqlite');today=datetime.now(timezone.utc).date()
    with ledger.connect() as db:
        db.execute('INSERT INTO api_usage VALUES (?,?)',(today.isoformat(),daily))
        db.execute('INSERT INTO api_usage VALUES (?,?)',((today-timedelta(days=1)).isoformat(),older))
    accepted,reason=ledger.reserve_api_credits_with_reason(4,20,holdback)
    assert reason==expected
    assert accepted==(daily+4+holdback<=20 and daily+older+4+holdback<=rolling_limit)
    with ledger.connect() as db:
        assert db.execute('SELECT credits FROM api_usage WHERE risk_day=?',(today.isoformat(),)).fetchone()[0]==daily+(4 if accepted else 0)


def test_concurrent_credit_decisions_keep_the_reserve_and_hard_cap(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from sportsbet.config import settings
    monkeypatch.setattr(settings,'odds_rolling_credit_limit',450)
    ledger=Ledger(tmp_path/'concurrent.sqlite')
    with ThreadPoolExecutor(max_workers=4) as executor:
        decisions=list(executor.map(lambda _:ledger.reserve_api_credits_with_reason(4,20,8),range(8)))
    assert decisions.count((True,'reserved'))==3
    assert decisions.count((False,'pregame_credit_reserve'))==5
    assert ledger.reserve_api_credits(8,20)
    assert ledger.reserve_api_credits_with_reason(1,20)==(False,'daily_credit_limit')


@pytest.mark.parametrize('cost,limit,holdback',[(True,20,8),(0,20,8),(4,0,8),(4,20,-1)])
def test_invalid_credit_requests_have_no_reservation(tmp_path,cost,limit,holdback):
    ledger=Ledger(tmp_path/'invalid.sqlite')
    assert ledger.reserve_api_credits_with_reason(cost,limit,holdback)==(False,'invalid_credit_request')
    with ledger.connect() as db:
        assert db.execute('SELECT count(*) FROM api_usage').fetchone()[0]==0
