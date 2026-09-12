from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sportsbet.ingestion.prop_odds import PlayerPropSnapshotCreate
from sportsbet.market_watch import digest
from sportsbet.arbitrage.kalshi_fees import taker_buy_cost
from sportsbet.prop.cross_venue import screen, screen_sportsbooks
from sportsbet.quant.vig import american_to_raw_prob


NOW = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)
START = NOW + timedelta(hours=2)


def event() -> dict:
    return dict(id='book-game', home_team='Kansas City Chiefs', away_team='Buffalo Bills',
        commence_time=START.isoformat())


def book(side='Under', line=Decimal('249.5'), observed=NOW, player='Player Name'):
    price = 150
    return PlayerPropSnapshotCreate(sport='nfl', game_id='book-game', player_name=player,
        sportsbook='book', prop_type='player_pass_yds', side=side, line=line, price=price,
        implied_probability=american_to_raw_prob(price), snapped_at=observed, game_start_time=START)


def handoff() -> dict:
    sha = 'a'*64
    evidence = dict(quotes=[dict(ticker='KXNFLPASSYDS-PLAYER-250', milestone_id='milestone',
            scheduled_game_start_time=START.isoformat(), prop_type='pass_yds',
            player_target_id='player', team_target_id='home', strike_type='greater', line='249.5',
            yes_ask={'cost':'0.45','displayed_size':'12'}, no_ask={'cost':'0.65','displayed_size':'9'},
            request_started_at=(NOW-timedelta(seconds=2)).isoformat(), received_at=NOW.isoformat(),
            market_sha256=sha, source_page_sha256=sha, rules_sha256=sha,
            settlement_equivalent=False, execution_ready=False)],
        player_targets={'player':{'player_name':'Player Name','team_target_id':'home',
            'target_sha256':sha,'target_page_sha256':sha,
            'target_request_started_at':(NOW-timedelta(seconds=2)).isoformat(),
            'target_received_at':(NOW-timedelta(seconds=1)).isoformat()}},
        games=[dict(milestone_id='milestone', scheduled_game_start_time=START.isoformat(),
            main_game_event_ticker='KXNFLGAME', home_team_id='home', away_team_id='away',
            home_team_aliases=['KC', 'Kansas City Chiefs'], away_team_aliases=['BUF', 'Buffalo Bills'])],
        coverage=dict(discovery_complete=True, series_observed=4, series_expected=4,
            structured_quote_markets=1, player_resolved_quote_markets=1,
            fee_contexts_expected=0,fee_contexts_observed=0), partial_coverage=False)
    return dict(schema_version=1, sport='nfl', captured_at=NOW.isoformat(), status='observed',
        evidence=evidence, evidence_sha256=digest(evidence), execution_ready=False)


def rehash(value: dict) -> dict:
    value['evidence_sha256'] = digest(value['evidence'])
    return value


def fee_handoff() -> dict:
    value=handoff();value['schema_version']=2
    quote=value['evidence']['quotes'][0]
    quote['event_ticker']='KXNFLPASSYDS-26SEP13KCBUF'
    quote['series_ticker']='KXNFLPASSYDS'
    sha='b'*64
    value['evidence']['fee_contexts']={quote['event_ticker']:dict(status='observed',
        received_at=(NOW-timedelta(seconds=3)).isoformat(),event_ticker=quote['event_ticker'],
        series={'ticker':quote['series_ticker'],'fee_type':'quadratic','fee_multiplier':1,
            'last_updated_ts':(NOW-timedelta(days=1)).isoformat()},
        series_changes={'series_fee_change_arr':[]},
        event_changes={'event_fee_changes':[],'cursor':''},series_sha256=sha,
        series_changes_sha256=sha,event_changes_sha256=sha)}
    value['evidence']['coverage']['fee_contexts_expected']=1
    value['evidence']['coverage']['fee_contexts_observed']=1
    return rehash(value)


def test_exact_complementary_quotes_emit_only_an_unverified_gross_screen():
    result = screen(event(), 'nfl', [book()], handoff(), NOW)
    row, = result['comparisons']
    assert result['status'] == 'observed'
    assert result['coverage']['exact_markets'] == 1
    assert row['legs'][0]['side'] == 'yes' and row['legs'][1]['side'] == 'Under'
    assert row['gross_cost_to_one_dollar'] == '0.85'
    assert row['gross_gap_to_one_dollar'] == '0.15'
    assert row['settlement_equivalent'] is False and row['execution_ready'] is False
    assert row['fee_adjusted_profit'] is None and row['realized_profit'] is None


def test_captured_prop_fees_add_a_cost_scenario_without_claiming_profit():
    result=screen(event(),'nfl',[book()],fee_handoff(),NOW)
    row,=result['comparisons'];scenario=row['exchange_fee_scenarios']
    expected=taker_buy_cost(Decimal('.45'),Decimal(1),Decimal(1),Decimal('.0001'))
    assert scenario['kalshi_leg']['direct']==expected
    assert Decimal(scenario['combined_cost']['direct'])==Decimal(expected['total_cost'])+Decimal('.4')
    assert scenario['schedule_ref']=='https://kalshi.com/regulatory/fee-schedule'
    assert row['fee_adjusted_profit'] is None and row['settlement_equivalent'] is False
    assert row['execution_ready'] is False


def test_missing_ambiguous_or_waived_prop_fees_preserve_only_the_gross_screen():
    cases=[]
    missing=fee_handoff();missing['evidence']['fee_contexts']={}
    missing['evidence']['coverage']['fee_contexts_observed']=0;cases.append(rehash(missing))
    incomplete=fee_handoff();context=next(iter(incomplete['evidence']['fee_contexts'].values()))
    context['event_changes']['cursor']='next';cases.append(rehash(incomplete))
    waived=fee_handoff();waived['evidence']['quotes'][0]['fee_waiver_expiration_time']=(
        NOW+timedelta(hours=1)).isoformat();cases.append(rehash(waived))
    small=fee_handoff();small['evidence']['quotes'][0]['yes_ask']['displayed_size']='0.5';cases.append(rehash(small))
    for changed in cases:
        row,=screen(event(),'nfl',[book()],changed,NOW)['comparisons']
        assert 'exchange_fee_scenarios' not in row
        assert row['gross_gap_to_one_dollar']=='0.15'
        assert row['fee_adjusted_profit'] is None


def test_all_collected_core_nfl_prop_series_have_a_sportsbook_market():
    from sportsbet.prop.cross_venue import PROP_MARKETS
    assert set(PROP_MARKETS['nfl'].values()) == {'pass_yds','rush_yds','rec_yds','receptions'}


def test_handoff_hash_completeness_status_and_age_fail_closed():
    cases = []
    changed = handoff(); changed['evidence_sha256'] = '0'*64; cases.append(changed)
    changed = handoff(); changed['evidence']['partial_coverage'] = True; cases.append(rehash(changed))
    changed = handoff(); changed['status'] = 'degraded'; cases.append(changed)
    changed = handoff(); changed['captured_at'] = (NOW-timedelta(seconds=301)).isoformat(); cases.append(changed)
    for changed in cases:
        result = screen(event(), 'nfl', [book()], changed, NOW)
        assert result['status'] == 'unavailable' and result['comparisons'] == []


def test_event_requires_one_exact_orientation_and_start():
    for key, value in [('home_team','Kansas City'), ('away_team','Kansas City Chiefs'),
            ('commence_time',(START+timedelta(seconds=1)).isoformat())]:
        changed = event(); changed[key] = value
        assert screen(changed, 'nfl', [book()], handoff(), NOW)['reason'] == 'event_not_matched'
    changed = handoff()
    changed['evidence']['games'].append(deepcopy(changed['evidence']['games'][0]))
    result = screen(event(), 'nfl', [book()], rehash(changed), NOW)
    assert result['status'] == 'unavailable'


def test_player_identity_strike_freshness_and_skew_are_never_fuzzy_matched():
    changed = handoff()
    changed['evidence']['player_targets']['other'] = {
        'player_name':' player   name ', 'team_target_id':'away',
        'target_sha256':'b'*64,'target_page_sha256':'b'*64,
        'target_request_started_at':(NOW-timedelta(seconds=2)).isoformat(),
        'target_received_at':(NOW-timedelta(seconds=1)).isoformat()}
    ambiguous = screen(event(), 'nfl', [book()], rehash(changed), NOW)
    assert ambiguous['comparisons'] == []
    assert ambiguous['coverage']['rejected']['ambiguous_player'] == 1

    changed = handoff(); changed['evidence']['quotes'][0]['line'] = '250'
    whole = screen(event(), 'nfl', [book(line=Decimal('250'))], rehash(changed), NOW)
    assert whole['coverage']['rejected']['non_complementary_strike'] == 1

    skewed = screen(event(), 'nfl', [book(observed=NOW+timedelta(seconds=31))], handoff(),
        NOW+timedelta(seconds=31))
    assert skewed['comparisons'] == []
    assert skewed['coverage']['rejected']['observation_skew_or_missing_side'] == 2


def test_malformed_target_or_quote_blocks_the_entire_screen():
    changed = handoff(); changed['evidence']['player_targets']['player']['team_target_id'] = 'away'
    result = screen(event(), 'nfl', [book()], rehash(changed), NOW)
    assert result['status'] == 'unavailable' and result['reason'] == 'invalid_quote_evidence'


def test_distinct_sportsbooks_can_produce_only_an_unverified_exact_prop_gap():
    over=book(side='Over');over.sportsbook='over-book';over.price=200
    over.implied_probability=american_to_raw_prob(200)
    under=book(side='Under');under.sportsbook='under-book';under.price=200
    under.implied_probability=american_to_raw_prob(200)
    result=screen_sportsbooks(event(),'nfl',[over,under],NOW)
    row,=result['comparisons']
    assert row['kind']=='sportsbook_sportsbook_prop'
    assert {leg['side'] for leg in row['legs']}=={'Over','Under'}
    assert row['gross_cost_to_one_dollar']==str(2*american_to_raw_prob(200))
    assert row['settlement_equivalent'] is False and row['execution_ready'] is False
    assert row['fee_adjusted_profit'] is None and row['realized_profit'] is None


def test_sportsbook_screen_requires_distinct_books_half_line_freshness_and_real_price():
    over=book(side='Over');under=book(side='Under')
    same=screen_sportsbooks(event(),'nfl',[over,under],NOW)
    assert same['comparisons']==[]
    under.sportsbook='other';under.line=Decimal('250')
    assert screen_sportsbooks(event(),'nfl',[over,under],NOW)['comparisons']==[]
    under.line=Decimal('249.5');under.snapped_at=NOW-timedelta(seconds=301)
    assert screen_sportsbooks(event(),'nfl',[over,under],NOW)['comparisons']==[]
    under.snapped_at=NOW;under.implied_probability=Decimal('.01')
    result=screen_sportsbooks(event(),'nfl',[over,under],NOW)
    assert result['comparisons']==[] and result['coverage']['rejected']['sportsbook_price']==1
