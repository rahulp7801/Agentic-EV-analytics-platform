"""Ingestion tests (DATA-02).

Stubs: ingestion module does not yet exist (Plan 03). Tests are marked xfail
so pytest exits 0 during Wave 0 scaffold validation.
"""

import pytest


@pytest.mark.xfail(strict=False, reason="ingestion not yet implemented — pending Plan 03")
def test_pbp_column_whitelist() -> None:
    """Ingestion loop must select only whitelisted columns before writing to PostgreSQL."""
    raise NotImplementedError


@pytest.mark.xfail(strict=False, reason="ingestion not yet implemented — pending Plan 03")
def test_pbp_multiseason_load() -> None:
    """Ingestion loop must load 5+ seasons year-by-year with gc.collect() between each."""
    raise NotImplementedError
