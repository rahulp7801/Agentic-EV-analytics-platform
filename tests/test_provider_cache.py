import pytest

from sportsbet.provider_cache import MAX_PAYLOAD_BYTES, payload_sha256
from sportsbet.scan import cache_key, validate_event_listing, validate_provider_event


def event(identity='event-1'):
    return {'id':identity,'home_team':'Home','away_team':'Away',
        'commence_time':'2026-09-20T17:00:00Z','bookmakers':[]}


def test_provider_payload_hash_is_canonical_and_bounded():
    assert payload_sha256({'b':2,'a':1})==payload_sha256({'a':1,'b':2})
    with pytest.raises(ValueError,match='cache limit'):
        payload_sha256({'payload':'x'*MAX_PAYLOAD_BYTES})


def test_provider_event_identity_and_listing_are_strict():
    expected=event()
    assert validate_provider_event(dict(expected),expected)==expected
    with pytest.raises(ValueError,match='does not match'):
        validate_provider_event(event('other'),expected)
    with pytest.raises(ValueError,match='Duplicate'):
        validate_event_listing([expected,expected])
    with pytest.raises(ValueError,match='Invalid provider event identity'):
        validate_event_listing([expected | {'away_team':'Home'}])


def test_provider_cache_keys_are_bounded_and_normalized():
    assert cache_key('events','cfb')=='odds:events:cfb'
    assert cache_key('event','nfl','ABC-123')=='odds:event:nfl:abc-123'
    with pytest.raises(ValueError,match='cache key'):
        cache_key('event','nfl','not/a/provider/id')
