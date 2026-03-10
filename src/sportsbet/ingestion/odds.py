"""Odds snapshot writer module.

Writes a single point-in-time odds snapshot to the odds_snapshots table.
Input is validated via OddsSnapshotCreate (Pydantic v2) before any DB write.

The odds_snapshots table is append-only — never UPDATE or UPSERT.
CLV (closing line value) is computed by querying the latest snapped_at before
game kickoff, which requires the immutable append history.

Pydantic v2 ONLY: ConfigDict(strict=True) and @field_validator (no v1 patterns).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

import sqlalchemy as sa
import structlog
from pydantic import BaseModel, ConfigDict, field_validator

from sportsbet.db.connection import get_sync_engine
from sportsbet.db.models import OddsSnapshot

log = structlog.get_logger()


class OddsSnapshotCreate(BaseModel):
    """Validated input for writing a single odds snapshot row.

    Pydantic v2 ONLY — no @validator or @root_validator (archived v1 patterns).
    strict=True ensures no coercion: passing a string for price raises ValidationError.
    """

    model_config = ConfigDict(strict=True)

    game_id: Optional[str] = None
    sportsbook: str
    market_type: str
    line: Optional[Decimal] = None
    price: Optional[int] = None  # American odds e.g. -110

    @field_validator("sportsbook", "market_type")
    @classmethod
    def must_be_nonempty(cls, v: str) -> str:
        """Reject empty or whitespace-only strings."""
        if not v.strip():
            raise ValueError("Field must not be empty or whitespace")
        return v.strip()

    @field_validator("price")
    @classmethod
    def validate_american_odds(cls, v: Optional[int]) -> Optional[int]:
        """American odds price of 0 is mathematically meaningless."""
        if v is not None and v == 0:
            raise ValueError("American odds price cannot be 0")
        return v


def write_odds_snapshot(
    snapshot: OddsSnapshotCreate,
    engine: sa.Engine | None = None,
) -> int:
    """Write a validated odds snapshot row. Returns the inserted row id.

    The odds_snapshots table is append-only — never UPDATE or UPSERT.
    CLV is computed by querying the latest snapped_at before game kickoff.

    Args:
        snapshot: Validated OddsSnapshotCreate model.
        engine: SQLAlchemy sync engine. If None, creates from settings.

    Returns:
        The autoincrement row id of the newly inserted row.
    """
    if engine is None:
        engine = get_sync_engine()

    with engine.begin() as conn:
        result = conn.execute(
            sa.insert(OddsSnapshot)
            .values(
                game_id=snapshot.game_id,
                sportsbook=snapshot.sportsbook,
                market_type=snapshot.market_type,
                line=snapshot.line,
                price=snapshot.price,
            )
            .returning(OddsSnapshot.id)
        )
        row_id: int = result.scalar_one()

    log.info(
        "odds_snapshot_written",
        row_id=row_id,
        game_id=snapshot.game_id,
        sportsbook=snapshot.sportsbook,
        market_type=snapshot.market_type,
    )
    return row_id
