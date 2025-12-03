from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from liq.sim.execution import match_order
from liq.types import Bar, OrderRequest
from liq.types.enums import OrderSide, OrderType, TimeInForce


def make_order(
    *,
    side: OrderSide,
    order_type: OrderType,
    qty: str,
    limit: str | None = None,
    stop: str | None = None,
) -> OrderRequest:
    return OrderRequest(
        client_order_id=uuid4(),
        symbol="AAPL",
        side=side,
        order_type=order_type,
        quantity=Decimal(qty),
        limit_price=Decimal(limit) if limit else None,
        stop_price=Decimal(stop) if stop else None,
        time_in_force=TimeInForce.DAY,
        timestamp=datetime.now(timezone.utc),
    )


def make_bar(open_price: str, high: str, low: str, close: str) -> Bar:
    return Bar(
        symbol="AAPL",
        timestamp=datetime.now(timezone.utc),
        open=Decimal(open_price),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("1000"),
    )


def test_market_buy_price_with_slippage() -> None:
    order = make_order(side=OrderSide.BUY, order_type=OrderType.MARKET, qty="1")
    bar = make_bar("100", "105", "95", "102")
    fill = match_order(order, bar, slippage=Decimal("1"))
    assert fill
    assert fill.price == Decimal("101")


def test_limit_buy_gap_benefit() -> None:
    order = make_order(side=OrderSide.BUY, order_type=OrderType.LIMIT, qty="1", limit="100")
    bar = make_bar("95", "105", "90", "100")
    fill = match_order(order, bar)
    assert fill
    # gap down, better than limit
    assert fill.price == Decimal("95")


def test_limit_sell_gap_benefit() -> None:
    order = make_order(side=OrderSide.SELL, order_type=OrderType.LIMIT, qty="1", limit="100")
    bar = make_bar("105", "110", "90", "100")
    fill = match_order(order, bar)
    assert fill
    assert fill.price == Decimal("105")


def test_stop_buy_triggers_with_slippage() -> None:
    order = make_order(side=OrderSide.BUY, order_type=OrderType.STOP, qty="1", stop="101")
    bar = make_bar("100", "102", "99", "101")
    fill = match_order(order, bar, slippage=Decimal("1"))
    assert fill
    assert fill.price == Decimal("102")


def test_stop_sell_triggers_with_slippage() -> None:
    order = make_order(side=OrderSide.SELL, order_type=OrderType.STOP, qty="1", stop="99")
    bar = make_bar("100", "101", "98", "99")
    fill = match_order(order, bar, slippage=Decimal("1"))
    assert fill
    assert fill.price == Decimal("98")


def test_stop_limit_buy_converts_to_limit() -> None:
    order = make_order(
        side=OrderSide.BUY, order_type=OrderType.STOP_LIMIT, qty="1", limit="101", stop="100"
    )
    bar = make_bar("99", "101", "95", "100")
    fill = match_order(order, bar)
    assert fill
    assert fill.price == Decimal("99")


def test_stop_limit_not_triggered_returns_none() -> None:
    order = make_order(
        side=OrderSide.BUY, order_type=OrderType.STOP_LIMIT, qty="1", limit="101", stop="100"
    )
    bar = make_bar("95", "99", "90", "95")
    fill = match_order(order, bar)
    assert fill is None


def test_stop_limit_sell_triggers_on_break() -> None:
    order = make_order(
        side=OrderSide.SELL, order_type=OrderType.STOP_LIMIT, qty="1", limit="99", stop="100"
    )
    bar = make_bar("101", "102", "98", "99")
    fill = match_order(order, bar)
    assert fill
    assert fill.price == Decimal("101")  # gap benefit on open when triggered


def test_limit_sell_not_hit_returns_none() -> None:
    order = make_order(side=OrderSide.SELL, order_type=OrderType.LIMIT, qty="1", limit="110")
    bar = make_bar("100", "105", "95", "100")
    assert match_order(order, bar) is None


def test_stop_orders_not_triggered_return_none() -> None:
    buy_stop = make_order(side=OrderSide.BUY, order_type=OrderType.STOP, qty="1", stop="120")
    sell_stop = make_order(side=OrderSide.SELL, order_type=OrderType.STOP, qty="1", stop="80")
    bar = make_bar("100", "105", "95", "100")
    assert match_order(buy_stop, bar) is None
    assert match_order(sell_stop, bar) is None
