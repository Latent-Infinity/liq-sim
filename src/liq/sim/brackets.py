"""Bracket order handling (stop-loss / take-profit with OCO)."""

from dataclasses import dataclass
from decimal import Decimal

from liq.core import OrderRequest, OrderSide, OrderType


@dataclass
class BracketState:
    """Track active bracket legs for a parent order."""

    stop_loss: OrderRequest | None
    take_profit: OrderRequest | None
    parent_id: str


def create_brackets(entry_fill_price: Decimal, entry_order: OrderRequest) -> BracketState:
    """Create contingent stop-loss / take-profit orders if configured on the entry."""
    sl_price = None
    tp_price = None
    if entry_order.metadata:
        sl_price = entry_order.metadata.get("stop_loss_price")
        tp_price = entry_order.metadata.get("take_profit_price")
    stop_loss = None
    take_profit = None
    if sl_price is not None:
        stop_loss = OrderRequest(
            symbol=entry_order.symbol,
            side=OrderSide.SELL if entry_order.side == OrderSide.BUY else OrderSide.BUY,
            order_type=OrderType.STOP,
            quantity=entry_order.quantity,
            stop_price=sl_price,
            time_in_force=entry_order.time_in_force,
            timestamp=entry_order.timestamp,
        )
    if tp_price is not None:
        take_profit = OrderRequest(
            symbol=entry_order.symbol,
            side=OrderSide.SELL if entry_order.side == OrderSide.BUY else OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=entry_order.quantity,
            limit_price=tp_price,
            time_in_force=entry_order.time_in_force,
            timestamp=entry_order.timestamp,
        )
    return BracketState(stop_loss=stop_loss, take_profit=take_profit, parent_id=str(entry_order.client_order_id))


def process_brackets(
    bracket: BracketState,
    bar_high: Decimal,
    bar_low: Decimal,
) -> tuple[OrderRequest | None, OrderRequest | None]:
    """Determine which bracket (if any) triggers on this bar; apply adverse-path rule."""
    sl_trigger = bracket.stop_loss and (
        (bracket.stop_loss.side == OrderSide.SELL and bar_low <= bracket.stop_loss.stop_price)
        or (bracket.stop_loss.side == OrderSide.BUY and bar_high >= bracket.stop_loss.stop_price)
    )
    tp_trigger = bracket.take_profit and (
        (bracket.take_profit.side == OrderSide.SELL and bar_high >= bracket.take_profit.limit_price)
        or (bracket.take_profit.side == OrderSide.BUY and bar_low <= bracket.take_profit.limit_price)
    )

    if sl_trigger and tp_trigger:
        # adverse path: stop-loss wins
        return bracket.stop_loss, None
    if sl_trigger:
        return bracket.stop_loss, None
    if tp_trigger:
        return bracket.take_profit, None
    return None, None
