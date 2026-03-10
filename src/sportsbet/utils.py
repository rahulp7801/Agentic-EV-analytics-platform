"""Utility functions for Quant-Sports platform."""

from datetime import date


def current_nfl_season() -> int:
    """Return the current NFL season year.

    The NFL season starts in September. If today is before September,
    we are in the prior season (e.g., March 2026 → 2025 season).

    Uses date.today() — NOT datetime.now().year — to avoid timezone drift.
    """
    today: date = date.today()
    if today.month >= 9:
        return today.year
    return today.year - 1
