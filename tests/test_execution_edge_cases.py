"""Tests for execution engine edge cases.

Following TDD: Tests verify edge case behavior in order matching.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from liq.core import Bar, OrderRequest
from liq.core.enums import OrderSide, OrderType, TimeInForce

from liq.sim.execution import match_order


def make_bar(
    symbol: str,
    ts: datetime,
    open_: str,
    high: str,
    low: str,
    close: str,
    volume: str = "1000000",
) -> Bar:
    """Create a bar for testing."""
    return Bar(
        symbol=symbol,
        timestamp=ts,
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal(volume),
    )


def make_limit_buy(symbol: str, ts: datetime, qty: str, limit: str) -> OrderRequest:
    """Create a limit buy order."""
    return OrderRequest(
        client_order_id=uuid4(),
        symbol=symbol,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal(qty),
        limit_price=Decimal(limit),
        time_in_force=TimeInForce.DAY,
        timestamp=ts,
    )


def make_limit_sell(symbol: str, ts: datetime, qty: str, limit: str) -> OrderRequest:
    """Create a limit sell order."""
    return OrderRequest(
        client_order_id=uuid4(),
        symbol=symbol,
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=Decimal(qty),
        limit_price=Decimal(limit),
        time_in_force=TimeInForce.DAY,
        timestamp=ts,
    )


def make_stop_buy(symbol: str, ts: datetime, qty: str, stop: str) -> OrderRequest:
    """Create a stop buy order."""
    return OrderRequest(
        client_order_id=uuid4(),
        symbol=symbol,
        side=OrderSide.BUY,
        order_type=OrderType.STOP,
        quantity=Decimal(qty),
        stop_price=Decimal(stop),
        time_in_force=TimeInForce.DAY,
        timestamp=ts,
    )


def make_stop_sell(symbol: str, ts: datetime, qty: str, stop: str) -> OrderRequest:
    """Create a stop sell order."""
    return OrderRequest(
        client_order_id=uuid4(),
        symbol=symbol,
        side=OrderSide.SELL,
        order_type=OrderType.STOP,
        quantity=Decimal(qty),
        stop_price=Decimal(stop),
        time_in_force=TimeInForce.DAY,
        timestamp=ts,
    )


def make_stop_limit_buy(
    symbol: str, ts: datetime, qty: str, stop: str, limit: str
) -> OrderRequest:
    """Create a stop-limit buy order."""
    return OrderRequest(
        client_order_id=uuid4(),
        symbol=symbol,
        side=OrderSide.BUY,
        order_type=OrderType.STOP_LIMIT,
        quantity=Decimal(qty),
        stop_price=Decimal(stop),
        limit_price=Decimal(limit),
        time_in_force=TimeInForce.DAY,
        timestamp=ts,
    )


def make_stop_limit_sell(
    symbol: str, ts: datetime, qty: str, stop: str, limit: str
) -> OrderRequest:
    """Create a stop-limit sell order."""
    return OrderRequest(
        client_order_id=uuid4(),
        symbol=symbol,
        side=OrderSide.SELL,
        order_type=OrderType.STOP_LIMIT,
        quantity=Decimal(qty),
        stop_price=Decimal(stop),
        limit_price=Decimal(limit),
        time_in_force=TimeInForce.DAY,
        timestamp=ts,
    )


class TestLimitOrderGaps:
    """Tests for limit orders with price gaps."""

    def test_limit_buy_gap_down_fills_at_open(self) -> None:
        """Limit buy when price gaps down should fill at open (better price)."""
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Limit at $100, but price gaps down to open at $95
        order = make_limit_buy("AAPL", t0, "10", "100")
        bar = make_bar("AAPL", t0, "95", "98", "94", "96")

        fill = match_order(order, bar)

        assert fill is not None
        # Should fill at open (better than limit)
        assert fill.price == Decimal("95")

    def test_limit_buy_gap_up_no_fill(self) -> None:
        """Limit buy when price gaps up above limit should not fill."""
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Limit at $100, but price gaps up to $105
        order = make_limit_buy("AAPL", t0, "10", "100")
        bar = make_bar("AAPL", t0, "105", "110", "104", "108")

        fill = match_order(order, bar)

        assert fill is None

    def test_limit_sell_gap_up_fills_at_open(self) -> None:
        """Limit sell when price gaps up should fill at open (better price)."""
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Limit at $100, but price gaps up to $105
        order = make_limit_sell("AAPL", t0, "10", "100")
        bar = make_bar("AAPL", t0, "105", "110", "104", "108")

        fill = match_order(order, bar)

        assert fill is not None
        # Should fill at open (better than limit)
        assert fill.price == Decimal("105")

    def test_limit_sell_gap_down_no_fill(self) -> None:
        """Limit sell when price gaps down below limit should not fill."""
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Limit at $100, but price gaps down to $95
        order = make_limit_sell("AAPL", t0, "10", "100")
        bar = make_bar("AAPL", t0, "95", "98", "94", "96")

        fill = match_order(order, bar)

        assert fill is None


class TestStopOrderEdgeCases:
    """Tests for stop order edge cases."""

    def test_stop_buy_triggered_at_exact_price(self) -> None:
        """Stop buy should trigger when high equals stop price exactly."""
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Stop at $100, high exactly $100
        order = make_stop_buy("AAPL", t0, "10", "100")
        bar = make_bar("AAPL", t0, "95", "100", "94", "98")

        fill = match_order(order, bar)

        assert fill is not None
        # Fills at stop price
        assert fill.price == Decimal("100")

    def test_stop_buy_not_triggered_below_stop(self) -> None:
        """Stop buy should not trigger when high is below stop price."""
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Stop at $100, high only $99
        order = make_stop_buy("AAPL", t0, "10", "100")
        bar = make_bar("AAPL", t0, "95", "99", "94", "98")

        fill = match_order(order, bar)

        assert fill is None

    def test_stop_sell_triggered_at_exact_price(self) -> None:
        """Stop sell should trigger when low equals stop price exactly."""
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Stop at $100, low exactly $100
        order = make_stop_sell("AAPL", t0, "10", "100")
        bar = make_bar("AAPL", t0, "105", "108", "100", "102")

        fill = match_order(order, bar)

        assert fill is not None
        # Fills at stop price
        assert fill.price == Decimal("100")

    def test_stop_sell_not_triggered_above_stop(self) -> None:
        """Stop sell should not trigger when low is above stop price."""
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Stop at $100, low only $101
        order = make_stop_sell("AAPL", t0, "10", "100")
        bar = make_bar("AAPL", t0, "105", "108", "101", "102")

        fill = match_order(order, bar)

        assert fill is None

    def test_stop_buy_gaps_through_fills_at_open(self) -> None:
        """Stop buy when price gaps through stop should fill at open."""
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Stop at $100, but price gaps up to $105
        order = make_stop_buy("AAPL", t0, "10", "100")
        bar = make_bar("AAPL", t0, "105", "110", "104", "108")

        fill = match_order(order, bar)

        assert fill is not None
        # Fills at open (worst case for buyer)
        assert fill.price == Decimal("105")

    def test_stop_sell_gaps_through_fills_at_open(self) -> None:
        """Stop sell when price gaps through stop should fill at open."""
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Stop at $100, but price gaps down to $95
        order = make_stop_sell("AAPL", t0, "10", "100")
        bar = make_bar("AAPL", t0, "95", "98", "94", "96")

        fill = match_order(order, bar)

        assert fill is not None
        # Fills at open (worst case for seller)
        assert fill.price == Decimal("95")


class TestStopLimitEdgeCases:
    """Tests for stop-limit order edge cases."""

    def test_stop_limit_buy_not_triggered(self) -> None:
        """Stop-limit buy should not trigger when stop not reached."""
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Stop at $100, limit at $102, high only $99
        order = make_stop_limit_buy("AAPL", t0, "10", "100", "102")
        bar = make_bar("AAPL", t0, "95", "99", "94", "98")

        fill = match_order(order, bar)

        assert fill is None

    def test_stop_limit_buy_triggered_and_filled(self) -> None:
        """Stop-limit buy should trigger and fill when both conditions met.

        When stop-limit buy triggers and open is below limit, fills at open (better price).
        """
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Stop at $100, limit at $102, high $105 (triggers)
        # Open at $98 is below limit $102, so fills at open (better price)
        order = make_stop_limit_buy("AAPL", t0, "10", "100", "102")
        bar = make_bar("AAPL", t0, "98", "105", "97", "103")

        fill = match_order(order, bar)

        assert fill is not None
        # Fills at open since it's better than limit
        assert fill.price == Decimal("98")

    def test_stop_limit_buy_triggered_but_not_filled(self) -> None:
        """Stop-limit buy that triggers but limit not reached should not fill."""
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Stop at $100, limit at $102, gaps up to $105 (triggers but misses limit)
        order = make_stop_limit_buy("AAPL", t0, "10", "100", "102")
        bar = make_bar("AAPL", t0, "105", "110", "104", "108")

        fill = match_order(order, bar)

        # Triggered but limit not reached - no fill
        assert fill is None

    def test_stop_limit_sell_not_triggered(self) -> None:
        """Stop-limit sell should not trigger when stop not reached."""
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Stop at $100, limit at $98, low only $101
        order = make_stop_limit_sell("AAPL", t0, "10", "100", "98")
        bar = make_bar("AAPL", t0, "105", "108", "101", "102")

        fill = match_order(order, bar)

        assert fill is None

    def test_stop_limit_sell_triggered_and_filled(self) -> None:
        """Stop-limit sell should trigger and fill when both conditions met.

        When stop-limit sell triggers and open is above limit, fills at open (better price).
        """
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Stop at $100, limit at $98, low $95 (triggers)
        # Open at $102 is above limit $98, so fills at open (better price)
        order = make_stop_limit_sell("AAPL", t0, "10", "100", "98")
        bar = make_bar("AAPL", t0, "102", "103", "95", "97")

        fill = match_order(order, bar)

        assert fill is not None
        # Fills at open since it's better than limit
        assert fill.price == Decimal("102")

    def test_stop_limit_sell_triggered_but_not_filled(self) -> None:
        """Stop-limit sell that triggers but limit not reached should not fill."""
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Stop at $100, limit at $98, gaps down to $95 (triggers but misses limit)
        order = make_stop_limit_sell("AAPL", t0, "10", "100", "98")
        bar = make_bar("AAPL", t0, "95", "97", "94", "96")

        fill = match_order(order, bar)

        # Triggered but limit not reached - no fill
        assert fill is None


class TestSlippageApplication:
    """Tests for slippage in execution."""

    def test_market_buy_slippage_added(self) -> None:
        """Market buy should have slippage added to price."""
        from liq.core import OrderRequest

        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        order = OrderRequest(
            client_order_id=uuid4(),
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("10"),
            time_in_force=TimeInForce.DAY,
            timestamp=t0,
        )
        bar = make_bar("AAPL", t0, "100", "102", "99", "101")

        fill = match_order(order, bar, slippage=Decimal("0.50"))

        assert fill is not None
        assert fill.price == Decimal("100.50")  # open + slippage
        assert fill.slippage == Decimal("0.50")

    def test_market_sell_slippage_subtracted(self) -> None:
        """Market sell should have slippage subtracted from price."""
        from liq.core import OrderRequest

        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        order = OrderRequest(
            client_order_id=uuid4(),
            symbol="AAPL",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("10"),
            time_in_force=TimeInForce.DAY,
            timestamp=t0,
        )
        bar = make_bar("AAPL", t0, "100", "102", "99", "101")

        fill = match_order(order, bar, slippage=Decimal("0.50"))

        assert fill is not None
        assert fill.price == Decimal("99.50")  # open - slippage
        assert fill.slippage == Decimal("0.50")

    def test_stop_buy_slippage_added(self) -> None:
        """Stop buy should have slippage added to fill price."""
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        order = make_stop_buy("AAPL", t0, "10", "100")
        bar = make_bar("AAPL", t0, "98", "105", "97", "103")

        fill = match_order(order, bar, slippage=Decimal("0.25"))

        assert fill is not None
        # Stop at $100, triggered, slippage adds
        assert fill.price == Decimal("100.25")
