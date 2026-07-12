"""Order matching against OHLC bars."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from liq.core import Bar, Fill, OrderRequest, OrderSide, OrderType


class FillPolicy(StrEnum):
    """How a resting limit interacts with a bar.

    TOUCH (default) fills a limit when price reaches it (``<=`` / ``>=``) —
    the historical behavior. TRADED_THROUGH fills only when price penetrates
    the limit (``<`` / ``>``), so a mere touch does not manufacture a passive
    fill that would in reality depend on queue priority.
    """

    TOUCH = "touch"
    TRADED_THROUGH = "traded_through"


class MakerFillOutcome(StrEnum):
    """Maker-fill quality for a resting limit against a bar (diagnostics)."""

    MISSED = "missed"  # price never reached the limit
    TOUCHED = "touched"  # reached the limit exactly, no penetration
    TRADED_THROUGH = "traded_through"  # penetrated and closed on the favorable side
    ADVERSE = "adverse"  # penetrated and closed beyond the limit against the maker


def classify_limit_fill(
    side: OrderSide,
    limit_price: Decimal,
    bar: Bar,
    *,
    adverse_margin: Decimal = Decimal("0"),
) -> MakerFillOutcome:
    """Classify how a resting limit at ``limit_price`` interacts with ``bar``.

    ``adverse_margin`` widens the band within which a through-fill is still
    considered clean; a close beyond the limit against the maker by more than
    the margin is ADVERSE (adverse selection). This is pure diagnostics — it
    does not decide whether an order fills (see :func:`match_order`).
    """
    if side == OrderSide.BUY:
        if bar.low > limit_price:
            return MakerFillOutcome.MISSED
        if bar.low == limit_price:
            return MakerFillOutcome.TOUCHED
        if bar.close < limit_price - adverse_margin:
            return MakerFillOutcome.ADVERSE
        return MakerFillOutcome.TRADED_THROUGH
    if bar.high < limit_price:
        return MakerFillOutcome.MISSED
    if bar.high == limit_price:
        return MakerFillOutcome.TOUCHED
    if bar.close > limit_price + adverse_margin:
        return MakerFillOutcome.ADVERSE
    return MakerFillOutcome.TRADED_THROUGH


def match_order(
    order: OrderRequest,
    bar: Bar,
    *,
    slippage: Decimal = Decimal("0"),
    commission: Decimal = Decimal("0"),
    provider: str = "mock",
    timestamp: datetime | None = None,
    fill_policy: FillPolicy = FillPolicy.TOUCH,
) -> Fill | None:
    """Match a single order against a bar and return a Fill or None if unfilled.

    ``fill_policy`` controls limit fills: TOUCH (default) fills on reach; the
    opt-in TRADED_THROUGH requires price to penetrate the limit.
    """
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
        if limit_price is None:
            return None
        through = fill_policy == FillPolicy.TRADED_THROUGH
        if order.side == OrderSide.BUY:
            reached = bar.low < limit_price if through else bar.low <= limit_price
            if reached:
                if bar.open < limit_price:
                    return _fill(min(bar.open, limit_price))
                return _fill(limit_price)
            return None
        else:
            reached = bar.high > limit_price if through else bar.high >= limit_price
            if reached:
                if bar.open > limit_price:
                    return _fill(max(bar.open, limit_price))
                return _fill(limit_price)
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
