"""Database transport normalization outside frozen shadow model implementations."""
from datetime import datetime, timezone


def normalize_source_timestamps(histories: dict) -> dict:
    """Copy driver rows into the existing source timestamp string contract.

    Game dates, source hashes, stat values and row order are untouched. Never
    invent a timezone for a naive datetime or replace the source observation.
    """
    normalized = {}
    for key, rows in histories.items():
        converted = []
        for raw in rows:
            row = dict(raw)
            stamp = row.get('source_observed_at')
            if isinstance(stamp, datetime):
                if stamp.tzinfo is None or stamp.utcoffset() is None:
                    raise ValueError('Source observation requires a timezone')
                row['source_observed_at'] = stamp.astimezone(timezone.utc).isoformat()
            converted.append(row)
        normalized[key] = converted
    return normalized
