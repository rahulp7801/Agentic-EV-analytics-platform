"""Reproducible NFL Next Gen Stats evidence from free nflverse releases."""
from __future__ import annotations

import hashlib
import io
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pandas as pd
import polars as pl
import sqlalchemy as sa
import structlog

from sportsbet.db.connection import get_sync_engine
from sportsbet.ingestion.provenance import row_sha256
from sportsbet.ingestion.upsert import upsert_rows

log = structlog.get_logger()

NGS_MIN_SEASON = 2016
NGS_MAX_WEEK = 22
NGS_PROVIDER = "nflverse_ngs"
NGS_BASE_URL = "https://github.com/nflverse/nflverse-data/releases/download/nextgen_stats"
NGS_CACHE_DIR = Path(".local/ngs-cache")
NGS_CACHE_TTL = timedelta(hours=20)
MAX_ASSET_BYTES = 64_000_000
TRUSTED_HOSTS = {
    "github.com",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
}

IDENTITY_COLUMNS = (
    "season", "week", "player_gsis_id", "team_abbr", "player_position",
)
METRIC_COLUMNS = {
    "passing": (
        "avg_time_to_throw", "avg_completed_air_yards", "avg_intended_air_yards",
        "aggressiveness", "passer_rating", "attempts",
    ),
    "receiving": (
        "avg_separation", "avg_cushion", "avg_yac", "avg_yac_above_expectation",
        "catch_percentage", "targets", "receptions",
    ),
    "rushing": (
        "efficiency", "percent_attempts_gte_eight_defenders",
        "rush_yards_over_expected", "avg_time_to_los", "rush_attempts",
    ),
}
PRIMARY_METRIC = {
    "passing": "avg_time_to_throw",
    "receiving": "avg_separation",
    "rushing": "efficiency",
}
COUNT_COLUMNS = {"attempts", "targets", "receptions", "rush_attempts"}
RATE_COLUMNS = {
    "aggressiveness", "catch_percentage", "percent_attempts_gte_eight_defenders",
}

# Preserve the former public constants for callers outside this module.
NGS_PASSING_COLUMNS = list(IDENTITY_COLUMNS + METRIC_COLUMNS["passing"])
NGS_RECEIVING_COLUMNS = list(IDENTITY_COLUMNS + METRIC_COLUMNS["receiving"])
NGS_RUSHING_COLUMNS = list(IDENTITY_COLUMNS + METRIC_COLUMNS["rushing"])


def asset_url(stat_type: str) -> str:
    if stat_type not in METRIC_COLUMNS:
        raise ValueError("Invalid NGS stat type")
    return f"{NGS_BASE_URL}/ngs_{stat_type}.parquet"


def _download(client: httpx.Client, url: str) -> bytes:
    target = httpx.URL(url)
    for _ in range(4):
        if (
            target.scheme != "https"
            or target.host not in TRUSTED_HOSTS
            or target.port not in (None, 443)
            or target.userinfo
        ):
            raise ValueError("Untrusted NGS asset URL")
        with client.stream("GET", target) as response:
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise ValueError("Invalid NGS asset redirect")
                target = target.join(location)
                continue
            response.raise_for_status()
            try:
                announced = int(response.headers.get("content-length", "0"))
            except ValueError:
                raise ValueError("Invalid NGS asset length") from None
            if response.status_code != 200 or not 0 <= announced <= MAX_ASSET_BYTES:
                raise ValueError("Invalid NGS asset response")
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_ASSET_BYTES:
                    raise ValueError("Invalid NGS asset response")
                chunks.append(chunk)
            payload = b"".join(chunks)
            if not payload:
                raise ValueError("Invalid NGS asset response")
            return payload
    raise ValueError("Too many NGS asset redirects")


def load_asset(
    client: httpx.Client,
    stat_type: str,
    *,
    cache_dir: Path = NGS_CACHE_DIR,
    now: datetime | None = None,
) -> tuple[bytes, datetime, bool]:
    """Load one raw release asset, reusing a bounded local cache when fresh."""
    now = now or datetime.now(timezone.utc)
    if now.utcoffset() is None:
        raise ValueError("NGS observation time requires a timezone")
    url = asset_url(stat_type)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"ngs_{stat_type}.parquet"
    try:
        modified = datetime.fromtimestamp(cached.stat().st_mtime, timezone.utc)
        if timedelta(0) <= now - modified <= NGS_CACHE_TTL:
            payload = cached.read_bytes()
            if 0 < len(payload) <= MAX_ASSET_BYTES:
                try:
                    pl.read_parquet(io.BytesIO(payload))
                    return payload, modified, True
                except Exception:
                    cached.unlink(missing_ok=True)
    except OSError:
        pass

    payload = _download(client, url)
    temporary = cached.with_suffix(".tmp")
    temporary.write_bytes(payload)
    temporary.replace(cached)
    return payload, now, False


def _number(value: object, column: str) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("NGS evidence contains a non-finite or non-numeric value")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError("NGS evidence contains a non-finite or non-numeric value")
    if column in COUNT_COLUMNS:
        if numeric < 0 or not numeric.is_integer():
            raise ValueError("NGS evidence contains an invalid count")
        return int(numeric)
    result = numeric
    if column in RATE_COLUMNS and not 0 <= result <= 100:
        raise ValueError("NGS evidence contains an invalid percentage")
    return result


def normalize_asset(
    payload: bytes,
    season: int,
    stat_type: str,
    observed_at: datetime,
) -> tuple[list[dict], dict]:
    """Validate one release and return only identified weekly rows for a season."""
    if (
        type(season) is not int
        or not NGS_MIN_SEASON <= season <= 2100
        or stat_type not in METRIC_COLUMNS
        or not isinstance(payload, bytes)
        or not 0 < len(payload) <= MAX_ASSET_BYTES
        or not isinstance(observed_at, datetime)
        or observed_at.utcoffset() is None
    ):
        raise ValueError("Invalid NGS normalization request")
    try:
        source = pl.read_parquet(io.BytesIO(payload))
    except Exception as exc:
        raise ValueError("Invalid NGS parquet asset") from exc
    columns = IDENTITY_COLUMNS + METRIC_COLUMNS[stat_type]
    if set(columns) - set(source.columns):
        raise ValueError("NGS asset schema is incomplete")
    if source.height > 1_000_000:
        raise ValueError("NGS asset row limit exceeded")

    frame = source.select(columns).filter(
        (pl.col("season") == season)
        & (pl.col("week") >= 1)
        & (pl.col("week") <= NGS_MAX_WEEK)
    )
    source_hash = hashlib.sha256(payload).hexdigest()
    url = asset_url(stat_type)
    records: list[dict] = []
    skipped_unidentified = 0
    for raw in frame.to_dicts():
        player_id = raw["player_gsis_id"]
        team = raw["team_abbr"]
        if (
            not isinstance(player_id, str)
            or re.fullmatch(r"00-[0-9]{7}", player_id.strip()) is None
            or not isinstance(team, str)
            or re.fullmatch(r"[A-Z]{2,3}", team.strip()) is None
        ):
            skipped_unidentified += 1
            continue
        position = raw["player_position"]
        if position is not None and (
            not isinstance(position, str)
            or re.fullmatch(r"[A-Z0-9/-]{1,5}", position.strip()) is None
        ):
            raise ValueError("NGS evidence contains an invalid player position")
        if type(raw["season"]) is not int or type(raw["week"]) is not int:
            raise ValueError("NGS evidence contains an invalid season or week")
        record = {
            "season": season,
            "week": raw["week"],
            "player_gsis_id": player_id.strip(),
            "team_abbr": team.strip(),
            "player_position": position.strip() if position else None,
            "stat_type": stat_type,
        }
        record.update(
            {column: _number(raw[column], column) for column in METRIC_COLUMNS[stat_type]}
        )
        if record[PRIMARY_METRIC[stat_type]] is None:
            continue
        record_hash = row_sha256(record)
        records.append(record | {
            "source_provider": NGS_PROVIDER,
            "source_url": url,
            "source_sha256": source_hash,
            "source_record_sha256": record_hash,
            "source_observed_at": observed_at,
        })

    identities = {
        (row["player_gsis_id"], row["season"], row["week"], row["stat_type"])
        for row in records
    }
    if len(identities) != len(records):
        raise ValueError("Duplicate NGS weekly identity")
    if not records:
        raise ValueError("NGS asset contains no identified weekly evidence")
    return records, {
        "provider": NGS_PROVIDER,
        "source_url": url,
        "source_sha256": source_hash,
        "season": season,
        "stat_type": stat_type,
        "rows": len(records),
        "skipped_unidentified": skipped_unidentified,
    }


def ingest_ngs_seasons(
    seasons: list[int],
    engine: sa.Engine | None = None,
    *,
    cache_dir: Path = NGS_CACHE_DIR,
) -> dict:
    """Refresh identified weekly NGS rows with raw and normalized commitments."""
    if not seasons or any(
        type(season) is not int or not NGS_MIN_SEASON <= season <= 2100
        for season in seasons
    ):
        raise ValueError(f"NGS data not available before {NGS_MIN_SEASON}")
    if len(seasons) != len(set(seasons)):
        raise ValueError("Duplicate NGS season request")
    engine = engine or get_sync_engine()
    coverage: list[dict] = []
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        for stat_type in METRIC_COLUMNS:
            payload, observed_at, cache_hit = load_asset(client, stat_type, cache_dir=cache_dir)
            for season in sorted(seasons):
                records, summary = normalize_asset(payload, season, stat_type, observed_at)
                source_hash = summary["source_sha256"]
                record_hashes = sorted(row["source_record_sha256"] for row in records)
                with engine.begin() as conn:
                    existing = conn.execute(sa.text("""SELECT source_sha256,
                        source_record_sha256 FROM ngs_stats
                        WHERE season=:season AND stat_type=:stat_type"""), {
                            "season": season,
                            "stat_type": stat_type,
                        }).mappings().all()
                    unchanged = (
                        len(existing) == len(records)
                        and all(row["source_sha256"] == source_hash for row in existing)
                        and sorted(row["source_record_sha256"] for row in existing) == record_hashes
                    )
                    if not unchanged:
                        # Replace this small season/type partition atomically so
                        # provider removals cannot survive beside the new digest.
                        conn.execute(sa.text(
                            "DELETE FROM ngs_stats WHERE season=:season "
                            "AND stat_type=:stat_type"
                        ), {
                            "season": season,
                            "stat_type": stat_type,
                        })
                        pd.DataFrame.from_records(records).to_sql(
                            "ngs_stats", conn, if_exists="append", index=False, chunksize=1000,
                            method=upsert_rows(
                                ["player_gsis_id", "season", "week", "stat_type"]
                            ),
                        )
                coverage.append(summary | {"cache_hit": cache_hit, "unchanged": unchanged})
                log.info("ngs_load_done", season=season, stat_type=stat_type,
                         rows=len(records), unchanged=unchanged)
    return {"provider": NGS_PROVIDER, "assets": coverage}
