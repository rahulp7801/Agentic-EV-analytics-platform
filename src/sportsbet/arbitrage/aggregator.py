"""Aggregator: daily drawdown gate for recommended bet exposure.

Enforces CLAUDE.md prop firm rule: cumulative recommended exposure per day
must not exceed the configured daily_drawdown_limit fraction of bankroll.

Design:
- Stateful per-instance (cumulative_exposure_usd resets on new instance or restart)
- record_signal(signal) -> bool: True if signal accepted, False if gate triggered
- Gate triggered when cumulative_exposure_usd + new exposure >= daily_drawdown_limit * bankroll_usd
- Once triggered, gate remains closed for the instance's lifetime
- No persistence in v1 — WARNING logged on restart; persistent budget tracking deferred to Phase 5

daily_drawdown_limit is a fraction of bankroll (e.g., 0.05 = 5% max daily risk).
This is separate from max_kelly_fraction (per-signal cap) — both must be satisfied.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from sportsbet.graph.models import EVSignal

log = logging.getLogger(__name__)


class Aggregator:
    """Daily drawdown gate that tracks cumulative recommended bet exposure.

    Stateful: cumulative_exposure_usd accumulates until the daily drawdown
    limit is reached. Once the gate triggers, all subsequent record_signal()
    calls return False for the lifetime of the instance (resets on restart).
    """

    def __init__(
        self,
        bankroll_usd: float,
        daily_drawdown_limit: float = 0.05,
    ) -> None:
        self._bankroll = Decimal(str(bankroll_usd))
        self._limit = Decimal(str(daily_drawdown_limit)) * self._bankroll
        self._cumulative: Decimal = Decimal("0")
        self._gate_triggered: bool = False

    @property
    def cumulative_exposure_usd(self) -> Decimal:
        """Total accepted exposure in USD for the current day."""
        return self._cumulative

    @property
    def gate_triggered(self) -> bool:
        """True if the daily drawdown limit has been reached or exceeded."""
        return self._gate_triggered

    def record_signal(self, signal: EVSignal) -> bool:
        """Record a signal's exposure. Returns True if accepted, False if gate closed.

        Adds kelly_fraction * bankroll to cumulative exposure. If the cumulative
        exposure would meet or exceed the daily_drawdown_limit * bankroll after
        this signal, triggers the gate and blocks the signal. The signal that
        triggers the gate is NOT added to cumulative_exposure_usd.
        """
        if self._gate_triggered:
            log.warning(
                "aggregator_gate_closed cumulative_usd=%s limit_usd=%s",
                str(self._cumulative),
                str(self._limit),
            )
            return False
        exposure = signal.kelly_fraction * self._bankroll
        if self._cumulative + exposure >= self._limit:
            self._gate_triggered = True
            log.warning(
                "aggregator_drawdown_limit_reached cumulative_usd=%s limit_usd=%s",
                str(self._cumulative + exposure),
                str(self._limit),
            )
            return False
        self._cumulative += exposure
        return True
