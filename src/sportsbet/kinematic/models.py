"""Kinematic Agent I/O models — Pydantic gate before any NGS SQL executes.

KinematicParams:
    Input model. Validates season/week/receiver before any DB query.
    Season field uses ge=2016 (NOT ge=1999) — NGS data starts 2016.
    See RESEARCH.md Pitfall 2.

KinematicAnalysis:
    Output model. All tracking fields are Optional[Decimal] = None.
    press_man_rate is ALWAYS None — the column is a forward-compat placeholder
    that is NULL in all current ngs_stats rows (see RESEARCH.md Pitfall 1).
    geometric_mismatch_flag is computed by run_matchup_query, not a validator.

Design: both models use strict=True (ConfigDict). No imports from graph/.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field


class KinematicParams(BaseModel):
    """Pydantic gate: validated before any NGS SQL executes.

    Season constraint enforces NGS data availability boundary (2016 onward).
    All values are positional params in asyncpg queries — never interpolated
    into SQL strings.
    """

    model_config = ConfigDict(strict=True)

    season: Annotated[int, Field(ge=2016, le=2030)]
    week: Annotated[int, Field(ge=1, le=22)]
    receiver_gsis_id: str
    min_targets: Annotated[int, Field(ge=1, le=200)] = 10


class KinematicAnalysis(BaseModel):
    """Output model for the Kinematic Agent matchup query.

    All tracking fields are Optional[Decimal] = None — not all players or seasons
    have every NGS metric populated. Signal is independent of QuantResult:
    no true_probability, no sample_size, no confidence_interval.

    press_man_rate is ALWAYS None. The column exists in ngs_stats as a nullable
    forward-compat placeholder. Do not query or populate it from the current schema.

    geometric_mismatch_flag is computed from avg_separation against SEPARATION_THRESHOLD
    inside run_matchup_query — it is NOT a Pydantic validator to keep the model
    as a plain container.
    """

    model_config = ConfigDict(strict=True)

    season: int
    week: int
    receiver_gsis_id: str
    avg_separation: Optional[Decimal] = None       # from ngs_stats receiving
    avg_cushion: Optional[Decimal] = None           # from ngs_stats receiving
    avg_time_to_throw: Optional[Decimal] = None     # QB context — may be None
    press_man_rate: Optional[Decimal] = None        # ALWAYS None — forward-compat placeholder
    geometric_mismatch_flag: bool = False           # True if avg_separation >= threshold
    signal_description: Optional[str] = None
    data_source: str = "ngs_stats"
    ngs_available: bool = True
