"""Order matching against OHLC bars."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from liq.types import Bar, Fill, OrderRequest, OrderSide, OrderType


def match_order(
    order: OrderRequest,
    bar: Bar,
    *,
    slippage: Decimal = Decimal("0"),
    commission: Decimal = Decimal("0"),
    provider: str = "mock",
    timestamp: datetime | None = None,
) -> Fill | None:
    """Match a single order against a bar and return a Fill or None if unfilled."""
    ts = timestamp or bar.timestamp

    # Helper to build Fill
    def _fill(price: Decimal, is_partial: bool = False) -> Fill:
        slip_value = slippage if slippage is not None else Decimal("0")
        return Fill(
            fill_id=uuid4(),
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=price,
            commission=commission,
            slippage=slip_value,
            realized_pnl=None,
            timestamp=ts,
            provider=provider,
            is_partial=is_partial,
        )

    # STOP_LIMIT handling: convert to limit if triggered
    effective_type = order.order_type
    limit_price = order.limit_price
    stop_price = order.stop_price
    if order.order_type == OrderType.STOP_LIMIT:
        if order.side == OrderSide.BUY:
            if bar.high >= (stop_price or Decimal("0")):
                effective_type = OrderType.LIMIT
                limit_price = order.limit_price
            else:
                return None
        else:  # SELL
            if bar.low <= (stop_price or Decimal("0")):
                effective_type = OrderType.LIMIT
                limit_price = order.limit_price
            else:
                return None

    if effective_type == OrderType.MARKET:
        if order.side == OrderSide.BUY:
            return _fill(bar.open + slippage)
        return _fill(bar.open - slippage)

    if effective_type == OrderType.LIMIT:
        if order.side == OrderSide.BUY:
            if bar.low <= (limit_price or Decimal("0")):
                if bar.open < (limit_price or Decimal("0")):
                    return _fill(min(bar.open, limit_price))
                return _fill(limit_price or bar.open)
            return None
        else:
            if bar.high >= (limit_price or Decimal("0")):
                if bar.open > (limit_price or Decimal("0")):
                    return _fill(max(bar.open, limit_price))
                return _fill(limit_price or bar.open)
            return None

    if effective_type == OrderType.STOP:
        if order.side == OrderSide.BUY:
            if bar.high >= (stop_price or Decimal("0")):
                price = max(stop_price or Decimal("0"), bar.open) + slippage
                return _fill(price)
            return None
        else:
            if bar.low <= (stop_price or Decimal("0")):
                price = min(stop_price or Decimal("0"), bar.open) - slippage
                return _fill(price)
            return None

    return None
