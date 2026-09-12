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
from datetime import datetime, timezone
from typing import Optional

import sqlalchemy as sa
import structlog
from pydantic import BaseModel, ConfigDict, Field

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
    game_start_time: Optional[datetime] = None
    snapped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    side: Optional[str] = None  # "Over" | "Under" — in-memory only, not persisted to DB


def parse_event_quotes(event: dict, sport: str, allowed_markets: set[str] | None = None) -> list[PlayerPropSnapshotCreate]:
    """Normalize observed sportsbook quotes without inventing timestamps or prices."""
    from sportsbet.quant.vig import american_to_raw_prob

    def timestamp(raw):
        parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('Provider timestamp requires a timezone')
        return parsed

    if sport not in ('nba', 'nfl') or not isinstance(event.get('id'), str) or not event['id'].strip():
        return []
    try:
        start = timestamp(event['commence_time'])
    except (KeyError, AttributeError, TypeError, ValueError):
        return []
    quotes = []
    for book in event.get('bookmakers', []):
        if not book.get('key') or book['key'].lower() == 'prizepicks':
            continue  # A whole-entry payout cannot become an American single-leg price.
        for market in book.get('markets', []):
            key = market.get('key')
            if not key or (allowed_markets is not None and key not in allowed_markets):
                continue
            try:
                observed = timestamp(market.get('last_update') or book.get('last_update'))
            except (AttributeError, TypeError, ValueError):
                continue
            for outcome in market.get('outcomes', []):
                price, player, side = outcome.get('price'), outcome.get('description'), outcome.get('name')
                if type(price) is not int or abs(price) < 100 or not isinstance(player, str) or not player.strip() or side not in ('Over', 'Under'):
                    continue
                try:
                    line = Decimal(str(outcome['point']))
                    if not line.is_finite() or line < 0:
                        continue
                except (KeyError, ArithmeticError, ValueError):
                    continue
                quotes.append(PlayerPropSnapshotCreate(sport=sport, game_id=event['id'],
                    player_name=player, sportsbook=book['key'], prop_type=key, side=side,
                    line=line, price=price, implied_probability=american_to_raw_prob(price),
                    snapped_at=observed, game_start_time=start))
    return quotes


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
    strings = ((snapshot.game_id,64),(snapshot.player_name,100),(snapshot.sportsbook,50),(snapshot.prop_type,40))
    complete = (snapshot.sport in ('nba','nfl')
        and all(isinstance(value,str) and bool(value.strip()) and len(value)<=limit for value,limit in strings)
        and isinstance(snapshot.line,Decimal) and snapshot.line.is_finite()
        and Decimal(0)<=snapshot.line<=Decimal('99999.99')
        and type(snapshot.price) is int and 100<=abs(snapshot.price)<=32767
        and isinstance(snapshot.implied_probability,Decimal) and snapshot.implied_probability.is_finite()
        and Decimal(0)<snapshot.implied_probability<Decimal(1)
        and snapshot.side in ('Over','Under')
        and isinstance(snapshot.snapped_at,datetime) and snapshot.snapped_at.utcoffset() is not None
        and isinstance(snapshot.game_start_time,datetime) and snapshot.game_start_time.utcoffset() is not None
        and snapshot.snapped_at<snapshot.game_start_time)
    if not complete:
        raise ValueError('Persistence requires a complete pregame quote')
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
                side=snapshot.side,
                game_start_time=snapshot.game_start_time,
                snapped_at=snapshot.snapped_at,
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
