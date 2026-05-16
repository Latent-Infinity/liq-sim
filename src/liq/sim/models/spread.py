"""Spread-based slippage placeholder."""

from decimal import Decimal
from typing import Protocol

from liq.core import Bar, OrderRequest


class SpreadLikeBar(Protocol):
    """Bar-like input that may expose an explicit spread."""

    high: Decimal
    low: Decimal


class SpreadBasedSlippage:
    """Execute at full spread width (mid ± spread/2)."""

    def calculate(self, order: OrderRequest, bar: Bar | SpreadLikeBar) -> Decimal:
        # Use ask - bid if available, else fall back to (high - low) as a crude spread proxy
        spread_attr = getattr(bar, "spread", None)
        if spread_attr is not None:
            spread: Decimal = spread_attr
        else:
            spread = bar.high - bar.low
        # Return half-spread so that buy adds and sell subtracts to achieve full width
        return Decimal(spread / 2)
