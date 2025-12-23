"""Tests for bracket order edge cases.

Following TDD: Tests verify bracket (stop-loss/take-profit) behavior.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from liq.core import Bar, OrderRequest, OrderSide, OrderType, TimeInForce

from liq.sim.brackets import BracketState, create_brackets, process_brackets


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


def make_order_with_brackets(
    symbol: str,
    ts: datetime,
    side: OrderSide,
    qty: str,
    stop_loss_price: str | None = None,
    take_profit_price: str | None = None,
) -> OrderRequest:
    """Create an order with bracket config via metadata."""
    metadata = {}
    if stop_loss_price:
        metadata["stop_loss_price"] = Decimal(stop_loss_price)
    if take_profit_price:
        metadata["take_profit_price"] = Decimal(take_profit_price)

    return OrderRequest(
        client_order_id=uuid4(),
        symbol=symbol,
        side=side,
        order_type=OrderType.MARKET,
        quantity=Decimal(qty),
        time_in_force=TimeInForce.GTC,
        timestamp=ts,
        metadata=metadata if metadata else None,
    )


class TestBracketCreation:
    """Tests for bracket creation from filled orders."""

    def test_create_brackets_long_with_stop_loss(self) -> None:
        """Long position should create sell stop-loss at specified price."""
        order = make_order_with_brackets(
            "AAPL", datetime.now(UTC), OrderSide.BUY, "100", stop_loss_price="95"
        )
        fill_price = Decimal("100")

        bracket = create_brackets(fill_price, order)

        assert bracket.stop_loss is not None
        assert bracket.stop_loss.side == OrderSide.SELL
        assert bracket.stop_loss.stop_price == Decimal("95")
        assert bracket.take_profit is None

    def test_create_brackets_long_with_take_profit(self) -> None:
        """Long position should create sell limit take-profit at specified price."""
        order = make_order_with_brackets(
            "AAPL", datetime.now(UTC), OrderSide.BUY, "100", take_profit_price="110"
        )
        fill_price = Decimal("100")

        bracket = create_brackets(fill_price, order)

        assert bracket.take_profit is not None
        assert bracket.take_profit.side == OrderSide.SELL
        assert bracket.take_profit.limit_price == Decimal("110")
        assert bracket.stop_loss is None

    def test_create_brackets_long_both_legs(self) -> None:
        """Long position with both stop-loss and take-profit."""
        order = make_order_with_brackets(
            "AAPL",
            datetime.now(UTC),
            OrderSide.BUY,
            "100",
            stop_loss_price="95",
            take_profit_price="110",
        )
        fill_price = Decimal("100")

        bracket = create_brackets(fill_price, order)

        assert bracket.stop_loss is not None
        assert bracket.take_profit is not None
        assert bracket.stop_loss.stop_price == Decimal("95")
        assert bracket.take_profit.limit_price == Decimal("110")

    def test_create_brackets_short_with_stop_loss(self) -> None:
        """Short position should create buy stop-loss at specified price."""
        order = make_order_with_brackets(
            "AAPL", datetime.now(UTC), OrderSide.SELL, "100", stop_loss_price="105"
        )
        fill_price = Decimal("100")

        bracket = create_brackets(fill_price, order)

        assert bracket.stop_loss is not None
        assert bracket.stop_loss.side == OrderSide.BUY  # Buy to cover short
        assert bracket.stop_loss.stop_price == Decimal("105")

    def test_create_brackets_short_with_take_profit(self) -> None:
        """Short position should create buy limit take-profit at specified price."""
        order = make_order_with_brackets(
            "AAPL", datetime.now(UTC), OrderSide.SELL, "100", take_profit_price="90"
        )
        fill_price = Decimal("100")

        bracket = create_brackets(fill_price, order)

        assert bracket.take_profit is not None
        assert bracket.take_profit.side == OrderSide.BUY  # Buy to cover short
        assert bracket.take_profit.limit_price == Decimal("90")

    def test_create_brackets_no_config(self) -> None:
        """Order without bracket metadata should create empty bracket."""
        order = make_order_with_brackets("AAPL", datetime.now(UTC), OrderSide.BUY, "100")
        fill_price = Decimal("100")

        bracket = create_brackets(fill_price, order)

        assert bracket.stop_loss is None
        assert bracket.take_profit is None


class TestBracketProcessing:
    """Tests for processing brackets against bars."""

    def test_stop_loss_triggers_on_low_for_sell_stop(self) -> None:
        """Sell stop-loss should trigger when bar low hits stop price."""
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        stop_order = OrderRequest(
            client_order_id=uuid4(),
            symbol="AAPL",
            side=OrderSide.SELL,
            order_type=OrderType.STOP,
            quantity=Decimal("100"),
            stop_price=Decimal("95"),
            time_in_force=TimeInForce.GTC,
            timestamp=t0,
        )
        bracket = BracketState(
            parent_id=str(uuid4()),
            stop_loss=stop_order,
            take_profit=None,
        )
        # Bar low hits stop price
        bar = make_bar("AAPL", t0, "100", "101", "94", "97")

        trigger, remaining = process_brackets(bracket, bar.high, bar.low)

        assert trigger is not None
        assert trigger.stop_price == Decimal("95")

    def test_take_profit_triggers_on_high_for_sell_limit(self) -> None:
        """Sell take-profit should trigger when bar high hits limit price."""
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        tp_order = OrderRequest(
            client_order_id=uuid4(),
            symbol="AAPL",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            limit_price=Decimal("110"),
            time_in_force=TimeInForce.GTC,
            timestamp=t0,
        )
        bracket = BracketState(
            parent_id=str(uuid4()),
            stop_loss=None,
            take_profit=tp_order,
        )
        # Bar high hits take-profit
        bar = make_bar("AAPL", t0, "100", "112", "99", "108")

        trigger, remaining = process_brackets(bracket, bar.high, bar.low)

        assert trigger is not None
        assert trigger.limit_price == Decimal("110")

    def test_neither_triggers_if_prices_not_hit(self) -> None:
        """Neither leg should trigger if bar doesn't hit prices."""
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        stop_order = OrderRequest(
            client_order_id=uuid4(),
            symbol="AAPL",
            side=OrderSide.SELL,
            order_type=OrderType.STOP,
            quantity=Decimal("100"),
            stop_price=Decimal("90"),
            time_in_force=TimeInForce.GTC,
            timestamp=t0,
        )
        tp_order = OrderRequest(
            client_order_id=uuid4(),
            symbol="AAPL",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            limit_price=Decimal("120"),
            time_in_force=TimeInForce.GTC,
            timestamp=t0,
        )
        bracket = BracketState(
            parent_id=str(uuid4()),
            stop_loss=stop_order,
            take_profit=tp_order,
        )
        # Bar doesn't hit either price
        bar = make_bar("AAPL", t0, "100", "105", "95", "102")

        trigger, remaining = process_brackets(bracket, bar.high, bar.low)

        assert trigger is None

    def test_stop_loss_wins_when_both_triggered(self) -> None:
        """Stop-loss should be returned when both could trigger (adverse path rule)."""
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        stop_order = OrderRequest(
            client_order_id=uuid4(),
            symbol="AAPL",
            side=OrderSide.SELL,
            order_type=OrderType.STOP,
            quantity=Decimal("100"),
            stop_price=Decimal("95"),
            time_in_force=TimeInForce.GTC,
            timestamp=t0,
        )
        tp_order = OrderRequest(
            client_order_id=uuid4(),
            symbol="AAPL",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            limit_price=Decimal("110"),
            time_in_force=TimeInForce.GTC,
            timestamp=t0,
        )
        bracket = BracketState(
            parent_id=str(uuid4()),
            stop_loss=stop_order,
            take_profit=tp_order,
        )
        # Bar hits BOTH stop and take-profit (wide bar)
        bar = make_bar("AAPL", t0, "100", "115", "90", "105")

        trigger, remaining = process_brackets(bracket, bar.high, bar.low)

        # Stop-loss wins per adverse path rule
        assert trigger is not None
        assert trigger.stop_price == Decimal("95")

    def test_short_stop_loss_triggers_on_high(self) -> None:
        """Short position stop-loss (buy stop) triggers when high hits stop."""
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        stop_order = OrderRequest(
            client_order_id=uuid4(),
            symbol="AAPL",
            side=OrderSide.BUY,  # Buy stop for short
            order_type=OrderType.STOP,
            quantity=Decimal("100"),
            stop_price=Decimal("105"),
            time_in_force=TimeInForce.GTC,
            timestamp=t0,
        )
        bracket = BracketState(
            parent_id=str(uuid4()),
            stop_loss=stop_order,
            take_profit=None,
        )
        # Bar high hits stop
        bar = make_bar("AAPL", t0, "100", "107", "99", "103")

        trigger, remaining = process_brackets(bracket, bar.high, bar.low)

        assert trigger is not None
        assert trigger.side == OrderSide.BUY

    def test_short_take_profit_triggers_on_low(self) -> None:
        """Short position take-profit (buy limit) triggers when low hits limit."""
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        tp_order = OrderRequest(
            client_order_id=uuid4(),
            symbol="AAPL",
            side=OrderSide.BUY,  # Buy limit for short take-profit
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            limit_price=Decimal("90"),
            time_in_force=TimeInForce.GTC,
            timestamp=t0,
        )
        bracket = BracketState(
            parent_id=str(uuid4()),
            stop_loss=None,
            take_profit=tp_order,
        )
        # Bar low hits take-profit
        bar = make_bar("AAPL", t0, "95", "96", "88", "91")

        trigger, remaining = process_brackets(bracket, bar.high, bar.low)

        assert trigger is not None
        assert trigger.side == OrderSide.BUY
        assert trigger.limit_price == Decimal("90")
