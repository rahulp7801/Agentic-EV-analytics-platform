"""Exclusive, uniquely named source archives for reproducible analysis."""
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def write_archive(report: dict, output: Path | None = None, *, directory: Path = Path('.local/market-data')) -> Path:
    if output is None:
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        output = directory / f'{timestamp}-{uuid4().hex}.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
    return output
