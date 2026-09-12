from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sportsbet.ingestion.prop_odds import PlayerPropSnapshotCreate
from sportsbet.market_watch import digest
from sportsbet.prop.cross_venue import screen
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
            structured_quote_markets=1, player_resolved_quote_markets=1), partial_coverage=False)
    return dict(schema_version=1, sport='nfl', captured_at=NOW.isoformat(), status='observed',
        evidence=evidence, evidence_sha256=digest(evidence), execution_ready=False)


def rehash(value: dict) -> dict:
    value['evidence_sha256'] = digest(value['evidence'])
    return value


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
