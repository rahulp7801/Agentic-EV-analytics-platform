"""TDD RED tests for Task 1 ingestion modules.

These tests are written BEFORE the implementation and must fail until
the ingestion modules are created.
"""
from __future__ import annotations

import pytest


def test_pbp_columns_count() -> None:
    """PBP_COLUMNS must have exactly 21 entries (18 original + air_yards, two_point_attempt, complete_pass)."""
    from sportsbet.ingestion.pbp import PBP_COLUMNS
    assert len(PBP_COLUMNS) == 21, f"Expected 21 columns, got {len(PBP_COLUMNS)}"


def test_ngs_min_season() -> None:
    """NGS_MIN_SEASON must equal 2016."""
    from sportsbet.ingestion.ngs import NGS_MIN_SEASON
    assert NGS_MIN_SEASON == 2016


def test_ngs_season_guard_raises_value_error() -> None:
    """ingest_ngs_seasons must raise ValueError for season < 2016."""
    from sportsbet.ingestion.ngs import ingest_ngs_seasons
    with pytest.raises(ValueError, match="2016"):
        ingest_ngs_seasons([2015], engine=None)


def test_memory_guard_raises_memory_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """ingest_pbp_seasons raises MemoryError when memory > 80%."""
    import psutil
    import types

    mock_vm = types.SimpleNamespace(percent=85.0)
    monkeypatch.setattr(psutil, "virtual_memory", lambda: mock_vm)

    from sportsbet.ingestion import pbp as pbp_mod
    # Reload to pick up monkeypatch (psutil already imported at module level)
    import importlib
    importlib.reload(pbp_mod)

    with pytest.raises(MemoryError):
        pbp_mod.ingest_pbp_seasons([2023], engine=object())  # type: ignore[arg-type]


def test_no_nfl_data_py_imports() -> None:
    """No `import nfl_data_py` statements in any ingestion module.

    Comments mentioning nfl_data_py (e.g. '# NOT nfl_data_py') are allowed.
    Only actual import statements are checked.
    """
    import pathlib
    import re
    src_dir = pathlib.Path(__file__).parent.parent / "src"
    # Match actual import statements, not comments referencing the old package name
    import_pattern = re.compile(r"^(?:import|from)\s+nfl_data_py", re.MULTILINE)
    found: list[str] = []
    for py_file in src_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        if import_pattern.search(text):
            found.append(str(py_file))
    assert not found, f"Found nfl_data_py import statement in: {found}"
