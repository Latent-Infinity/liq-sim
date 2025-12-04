"""Fee models for provider-specific commission calculations."""

from decimal import Decimal

from liq.core import OrderRequest


class CommissionModel:
    """Protocol-like base for commission models."""

    def calculate(self, order: OrderRequest, fill_price: Decimal, is_maker: bool) -> Decimal:
        raise NotImplementedError  # pragma: no cover


class TieredMakerTakerFee(CommissionModel):
    """Maker/taker fees expressed in basis points."""

    def __init__(self, maker_bps: Decimal, taker_bps: Decimal) -> None:
        self.maker_bps = maker_bps
        self.taker_bps = taker_bps

    def calculate(self, order: OrderRequest, fill_price: Decimal, is_maker: bool) -> Decimal:
        notional = order.quantity * fill_price
        bps = self.maker_bps if is_maker else self.taker_bps
        return (notional * bps) / Decimal("10000")


class ZeroCommissionFee(CommissionModel):
    """Commission-free model."""

    def calculate(self, order: OrderRequest, fill_price: Decimal, is_maker: bool) -> Decimal:
        return Decimal("0")


class PerShareFee(CommissionModel):
    """Per-share/per-unit fee with optional minimum."""

    def __init__(self, per_share: Decimal, min_per_order: Decimal | None = None) -> None:
        self.per_share = per_share
        self.min_per_order = min_per_order

    def calculate(self, order: OrderRequest, fill_price: Decimal, is_maker: bool) -> Decimal:
        fee = self.per_share * order.quantity
        if self.min_per_order is not None:
            fee = max(fee, self.min_per_order)
        return fee
