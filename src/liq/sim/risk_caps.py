"""Risk-cap decision helpers (net-position, pyramiding, equity floor, frequency)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class RiskCapsState:
    """Represents current risk-cap-relevant state."""

    net_exposure: Decimal
    equity: Decimal
    trades_today: int
    pyramid_layers: int


def enforce_net_position_cap(net_exposure: Decimal, equity: Decimal, cap_pct: float | None) -> bool:
    """Return True if net exposure within cap."""
    if cap_pct is None:
        return True
    if equity <= 0:
        return False
    return abs(net_exposure) <= Decimal(str(cap_pct)) * equity


def enforce_pyramiding_limit(current_layers: int, max_layers: int | None) -> bool:
    """Return True if pyramiding layers are below limit."""
    if max_layers is None:
        return True
    return current_layers < max_layers


def enforce_equity_floor(equity: Decimal, floor_pct: float | None, starting_equity: Decimal) -> bool:
    """Return True if equity is above floor percentage of starting equity."""
    if floor_pct is None:
        return True
    return equity >= Decimal(str(floor_pct)) * starting_equity


def enforce_frequency_cap(trades_today: int, cap: int | None) -> bool:
    """Return True if trade count within cap."""
    if cap is None:
        return True
    return trades_today < cap
