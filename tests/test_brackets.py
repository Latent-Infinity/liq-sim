from decimal import Decimal
from datetime import datetime, timezone

from liq.sim.brackets import BracketState, create_brackets, process_brackets
from liq.types import OrderRequest
from liq.types.enums import OrderSide, OrderType


def make_entry(side: OrderSide, qty: str, sl: str | None, tp: str | None) -> OrderRequest:
    return OrderRequest(
        symbol="AAPL",
        side=side,
        order_type=OrderType.MARKET,
        quantity=Decimal(qty),
        stop_price=None,
        limit_price=None,
        timestamp=datetime.now(timezone.utc),
        # stash bracket levels in metadata for creation
        metadata={"stop_loss_price": Decimal(sl) if sl else None, "take_profit_price": Decimal(tp) if tp else None},
    )


def test_create_brackets_builds_orders() -> None:
    entry = make_entry(OrderSide.BUY, "1", "95", "110")
    bracket = create_brackets(Decimal("100"), entry)
    assert bracket.stop_loss is not None
    assert bracket.take_profit is not None
    assert bracket.stop_loss.side == OrderSide.SELL
    assert bracket.take_profit.limit_price == Decimal("110")


def test_process_brackets_adverse_path_prefers_stop() -> None:
    entry = make_entry(OrderSide.BUY, "1", "95", "110")
    bracket = create_brackets(Decimal("100"), entry)
    order, canceled = process_brackets(bracket, bar_high=Decimal("111"), bar_low=Decimal("94"))
    assert order is bracket.stop_loss
    assert canceled is None


def test_process_brackets_take_profit_only() -> None:
    entry = make_entry(OrderSide.BUY, "1", None, "110")
    bracket = create_brackets(Decimal("100"), entry)
    order, canceled = process_brackets(bracket, bar_high=Decimal("111"), bar_low=Decimal("100"))
    assert order is bracket.take_profit
    assert canceled is None
