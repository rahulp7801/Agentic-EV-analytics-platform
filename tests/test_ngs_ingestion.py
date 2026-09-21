"""NFL Next Gen Stats source validation and provenance."""
import hashlib
import io
from datetime import datetime, timedelta, timezone

import httpx
import polars as pl
import pytest

from sportsbet.ingestion.ngs import (
    MAX_ASSET_BYTES,
    asset_url,
    load_asset,
    normalize_asset,
)
from sportsbet.ingestion.provenance import row_sha256


def parquet(rows: list[dict]) -> bytes:
    buffer = io.BytesIO()
    pl.DataFrame(rows).write_parquet(buffer)
    return buffer.getvalue()


def passing_rows() -> list[dict]:
    base = {
        "season": 2026,
        "player_gsis_id": "00-0031234",
        "team_abbr": "SEA",
        "player_position": "QB",
        "avg_time_to_throw": 2.75,
        "avg_completed_air_yards": 6.2,
        "avg_intended_air_yards": 7.1,
        "aggressiveness": 14.5,
        "passer_rating": 97.2,
        "attempts": 31,
    }
    return [base | {"week": 0}, base | {"week": 1}, base | {"week": 2}]


def test_normalize_ngs_excludes_summary_and_commits_exact_source() -> None:
    payload = parquet(passing_rows())
    observed = datetime(2026, 9, 20, tzinfo=timezone.utc)
    records, coverage = normalize_asset(payload, 2026, "passing", observed)
    assert [record["week"] for record in records] == [1, 2]
    assert coverage["rows"] == 2
    assert coverage["source_sha256"] == hashlib.sha256(payload).hexdigest()
    assert coverage["source_url"] == asset_url("passing")
    record = records[0]
    evidence = {key: value for key, value in record.items() if not key.startswith("source_")}
    assert record["source_record_sha256"] == row_sha256(evidence)
    assert record["source_provider"] == "nflverse_ngs"
    assert record["source_observed_at"] == observed


def test_normalize_ngs_rejects_schema_duplicates_and_nonfinite_values() -> None:
    observed = datetime(2026, 9, 20, tzinfo=timezone.utc)
    incomplete = passing_rows()
    for row in incomplete:
        row.pop("avg_intended_air_yards")
    with pytest.raises(ValueError, match="schema"):
        normalize_asset(parquet(incomplete), 2026, "passing", observed)

    duplicate = passing_rows()[1]
    with pytest.raises(ValueError, match="Duplicate"):
        normalize_asset(parquet([duplicate, duplicate]), 2026, "passing", observed)

    nonfinite = passing_rows()[1] | {"avg_time_to_throw": float("nan")}
    with pytest.raises(ValueError, match="non-finite"):
        normalize_asset(parquet([nonfinite]), 2026, "passing", observed)

    unidentified = passing_rows()[1] | {"player_gsis_id": "not-a-gsis-id"}
    with pytest.raises(ValueError, match="no identified"):
        normalize_asset(parquet([unidentified]), 2026, "passing", observed)


def test_ngs_asset_download_is_bounded_and_cached(tmp_path) -> None:
    payload = parquet(passing_rows())
    calls = 0

    def redirect(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.host == "github.com":
            return httpx.Response(
                302,
                headers={"location": "https://release-assets.githubusercontent.com/ngs"},
            )
        return httpx.Response(200, content=payload)

    now = datetime.now(timezone.utc)
    with httpx.Client(
        transport=httpx.MockTransport(redirect), follow_redirects=False
    ) as client:
        first, observed, cache_hit = load_asset(
            client, "passing", cache_dir=tmp_path, now=now
        )
        second, cached_at, second_hit = load_asset(
            client, "passing", cache_dir=tmp_path, now=now + timedelta(minutes=1)
        )
    assert first == second == payload
    assert observed == now and cached_at <= now + timedelta(minutes=1)
    assert cache_hit is False and second_hit is True and calls == 2

    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
            200, headers={"content-length": str(MAX_ASSET_BYTES + 1)}
    )), follow_redirects=False) as client:
        with pytest.raises(ValueError, match="response"):
            load_asset(client, "rushing", cache_dir=tmp_path, now=now)

    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
            302, headers={"location": "https://evil.example/ngs"}
    )), follow_redirects=False) as client:
        with pytest.raises(ValueError, match="Untrusted"):
            load_asset(client, "receiving", cache_dir=tmp_path, now=now)
