"""Player prop snapshot writer module.

Writes a single point-in-time player prop odds snapshot to the
player_prop_snapshots table. Input is validated via PlayerPropSnapshotCreate
(Pydantic v2) before any DB write.

The player_prop_snapshots table is append-only — never UPDATE or UPSERT.
implied_probability is stored as Decimal(str(round(raw_prob, 6))) — never
float assigned directly to prevent precision loss through Pydantic strict=True.

Pydantic v2 ONLY: ConfigDict(strict=True). No v1 patterns.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

import sqlalchemy as sa
import structlog
from pydantic import BaseModel, ConfigDict

from sportsbet.db.connection import get_sync_engine
from sportsbet.db.models import PlayerPropSnapshot

log = structlog.get_logger()


class PlayerPropSnapshotCreate(BaseModel):
    """Validated input for writing a single player prop snapshot row.

    Pydantic v2 ONLY — no @validator or @root_validator (archived v1 patterns).
    strict=True ensures no coercion: passing a string for price raises ValidationError.

    Fields match the PlayerPropSnapshot ORM columns, excluding id and snapped_at
    which have DB-level defaults (BIGSERIAL autoincrement and now() respectively).

    implied_probability must be pre-computed by the caller using the pattern:
        Decimal(str(round(raw_prob, 6)))
    This ensures float-to-Decimal conversion precision — never assign float directly.
    """

    model_config = ConfigDict(strict=True)

    sport: str
    game_id: Optional[str] = None
    player_name: str
    sportsbook: str
    prop_type: str
    line: Optional[Decimal] = None
    price: Optional[int] = None  # American odds e.g. -115
    implied_probability: Decimal


def write_player_prop_snapshot(
    snapshot: PlayerPropSnapshotCreate,
    engine: sa.Engine | None = None,
) -> int:
    """Write a validated player prop snapshot row. Returns the inserted row id.

    The player_prop_snapshots table is append-only — never UPDATE or UPSERT.

    Args:
        snapshot: Validated PlayerPropSnapshotCreate model.
        engine: SQLAlchemy sync engine. If None, creates from settings.

    Returns:
        The autoincrement row id of the newly inserted row.
    """
    if engine is None:
        engine = get_sync_engine()

    with engine.begin() as conn:
        result = conn.execute(
            sa.insert(PlayerPropSnapshot)
            .values(
                sport=snapshot.sport,
                game_id=snapshot.game_id,
                player_name=snapshot.player_name,
                sportsbook=snapshot.sportsbook,
                prop_type=snapshot.prop_type,
                line=snapshot.line,
                price=snapshot.price,
                implied_probability=snapshot.implied_probability,
            )
            .returning(PlayerPropSnapshot.id)
        )
        row_id: int = result.scalar_one()

    log.info(
        "player_prop_snapshot_written",
        row_id=row_id,
        sport=snapshot.sport,
        player_name=snapshot.player_name,
        prop_type=snapshot.prop_type,
        sportsbook=snapshot.sportsbook,
    )
    return row_id
