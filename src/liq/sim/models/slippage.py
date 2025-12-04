"""Slippage models for execution price adjustments."""

from decimal import Decimal

from liq.core import Bar, OrderRequest


class SlippageModel:
    """Protocol-like base for slippage models."""

    def calculate(self, order: OrderRequest, bar: Bar) -> Decimal:
        raise NotImplementedError  # pragma: no cover


class VolumeWeightedSlippage(SlippageModel):
    """Slippage scales with order participation vs bar volume."""

    def __init__(self, base_bps: Decimal, volume_impact: Decimal) -> None:
        self.base_bps = base_bps
        self.volume_impact = volume_impact

    def calculate(self, order: OrderRequest, bar: Bar) -> Decimal:
        volume = bar.volume
        participation = Decimal("0")
        if volume > 0:
            participation = min(Decimal("1"), order.quantity / volume)
        slippage_bps = self.base_bps + self.volume_impact * participation
        price_ref = bar.midrange
        return (price_ref * slippage_bps) / Decimal("10000")


class PFOFSlippage(SlippageModel):
    """Fixed adverse selection in bps."""

    def __init__(self, adverse_bps: Decimal) -> None:
        self.adverse_bps = adverse_bps

    def calculate(self, order: OrderRequest, bar: Bar) -> Decimal:
        price_ref = bar.midrange
        return (price_ref * self.adverse_bps) / Decimal("10000")
