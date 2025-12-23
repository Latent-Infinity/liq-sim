"""Tests for gross leverage constraint enforcement.

Following TDD: These tests verify check_gross_leverage() correctly enforces
the max_gross_leverage cap on total portfolio exposure.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from liq.core import OrderRequest, PortfolioState, Position
from liq.core.enums import OrderType

from liq.sim.constraints import ConstraintViolation, check_gross_leverage


def make_portfolio(
    cash: Decimal,
    positions: dict[str, Position] | None = None,
) -> PortfolioState:
    """Create a portfolio state for testing."""
    now = datetime.now(UTC)
    return PortfolioState(
        cash=cash,
        unsettled_cash=Decimal("0"),
        positions=positions or {},
        realized_pnl=Decimal("0"),
        buying_power=None,
        margin_used=None,
        day_trades_remaining=None,
        timestamp=now,
    )


def make_position(
    symbol: str,
    quantity: Decimal,
    avg_price: Decimal,
    current_price: Decimal | None = None,
) -> Position:
    """Create a position for testing."""
    now = datetime.now(UTC)
    return Position(
        symbol=symbol,
        quantity=quantity,
        average_price=avg_price,
        current_price=current_price or avg_price,
        realized_pnl=Decimal("0"),
        timestamp=now,
    )


def make_buy_order(symbol: str, quantity: Decimal) -> OrderRequest:
    """Create a buy order for testing."""
    return OrderRequest(
        client_order_id=uuid4(),
        symbol=symbol,
        side="buy",
        order_type=OrderType.MARKET,
        quantity=quantity,
        timestamp=datetime.now(UTC),
    )


def make_sell_order(symbol: str, quantity: Decimal) -> OrderRequest:
    """Create a sell order for testing."""
    return OrderRequest(
        client_order_id=uuid4(),
        symbol=symbol,
        side="sell",
        order_type=OrderType.MARKET,
        quantity=quantity,
        timestamp=datetime.now(UTC),
    )


class TestGrossLeverageBasic:
    """Basic gross leverage enforcement tests."""

    def test_order_within_leverage_limit_passes(self) -> None:
        """Order within leverage limit should pass."""
        portfolio = make_portfolio(Decimal("100000"))
        order = make_buy_order("AAPL", Decimal("500"))
        mark_price = Decimal("100")  # 500 * 100 = 50000 = 50% of equity

        # 1.0x leverage limit, 50% exposure should pass
        check_gross_leverage(order, portfolio, mark_price, max_gross_leverage=1.0)

    def test_order_exceeding_leverage_limit_raises(self) -> None:
        """Order exceeding leverage limit should raise ConstraintViolation."""
        portfolio = make_portfolio(Decimal("100000"))
        order = make_buy_order("AAPL", Decimal("1500"))
        mark_price = Decimal("100")  # 1500 * 100 = 150000 = 150% of equity

        with pytest.raises(ConstraintViolation) as exc_info:
            check_gross_leverage(order, portfolio, mark_price, max_gross_leverage=1.0)

        assert "Gross leverage exceeded" in str(exc_info.value)
        assert "150000" in str(exc_info.value)  # projected exposure
        assert "100000" in str(exc_info.value)  # cap

    def test_order_exactly_at_leverage_limit_passes(self) -> None:
        """Order exactly at leverage limit should pass (boundary condition)."""
        portfolio = make_portfolio(Decimal("100000"))
        order = make_buy_order("AAPL", Decimal("1000"))
        mark_price = Decimal("100")  # 1000 * 100 = 100000 = 100% of equity

        # 1.0x leverage limit, exactly 100% should pass
        check_gross_leverage(order, portfolio, mark_price, max_gross_leverage=1.0)

    def test_error_message_includes_leverage_values(self) -> None:
        """Error message should include leverage values for debugging."""
        portfolio = make_portfolio(Decimal("50000"))
        order = make_buy_order("AAPL", Decimal("1000"))
        mark_price = Decimal("100")  # 1000 * 100 = 100000 = 200% of equity

        with pytest.raises(ConstraintViolation) as exc_info:
            check_gross_leverage(order, portfolio, mark_price, max_gross_leverage=1.0)

        msg = str(exc_info.value)
        assert "100000" in msg  # projected
        assert "50000" in msg  # cap (1.0 * 50000)
        assert "1.0" in msg or "1x" in msg.lower()  # leverage multiplier


class TestGrossLeverageWithExistingPositions:
    """Tests for gross leverage with existing positions."""

    def test_existing_long_position_plus_new_buy(self) -> None:
        """Existing long position + new buy must respect leverage limit."""
        # Already 50% exposed with AAPL
        position = make_position("AAPL", Decimal("500"), Decimal("100"))
        portfolio = make_portfolio(
            Decimal("50000"),  # cash
            positions={"AAPL": position},  # 500 * 100 = 50000 exposure
        )
        # equity = 50000 cash + 50000 position = 100000

        # Try to buy more - would be 50000 + 50000 = 100000 exposure
        order = make_buy_order("GOOGL", Decimal("500"))
        mark_price = Decimal("100")

        # At 1.0x leverage, 100000 exposure = 100% = exactly at limit
        check_gross_leverage(order, portfolio, mark_price, max_gross_leverage=1.0)

        # Now try to exceed
        order2 = make_buy_order("GOOGL", Decimal("600"))
        with pytest.raises(ConstraintViolation):
            check_gross_leverage(order2, portfolio, mark_price, max_gross_leverage=1.0)

    def test_existing_short_position_plus_new_short(self) -> None:
        """Existing short position + new short must respect leverage limit."""
        # Short 500 shares of AAPL at $100 = -50000 exposure (but abs = 50000)
        position = make_position("AAPL", Decimal("-500"), Decimal("100"))
        portfolio = make_portfolio(
            Decimal("150000"),  # cash (includes short proceeds)
            positions={"AAPL": position},
        )
        # equity = 150000 + (-50000) = 100000, gross = 50000

        # Try to short more
        order = make_sell_order("GOOGL", Decimal("600"))
        mark_price = Decimal("100")  # 60000 new exposure

        # 50000 + 60000 = 110000 > 100000 cap
        with pytest.raises(ConstraintViolation):
            check_gross_leverage(order, portfolio, mark_price, max_gross_leverage=1.0)

    def test_mixed_long_short_summed_as_absolute(self) -> None:
        """Long and short positions should be summed by absolute value."""
        # Long AAPL, Short GOOGL
        long_pos = make_position("AAPL", Decimal("300"), Decimal("100"))
        short_pos = make_position("GOOGL", Decimal("-200"), Decimal("100"))
        portfolio = make_portfolio(
            Decimal("50000"),
            positions={"AAPL": long_pos, "GOOGL": short_pos},
        )
        # equity = 50000 + 30000 - 20000 = 60000
        # gross = |30000| + |-20000| = 50000

        # New buy of 20000 -> gross = 70000
        order = make_buy_order("MSFT", Decimal("200"))
        mark_price = Decimal("100")

        # 70000 > 60000 (1.0x cap)
        with pytest.raises(ConstraintViolation):
            check_gross_leverage(order, portfolio, mark_price, max_gross_leverage=1.0)

        # But should pass at 1.5x
        check_gross_leverage(order, portfolio, mark_price, max_gross_leverage=1.5)

    def test_multiple_symbols_summed_correctly(self) -> None:
        """Multiple positions should all contribute to gross exposure."""
        positions = {
            "AAPL": make_position("AAPL", Decimal("100"), Decimal("100")),  # 10000
            "GOOGL": make_position("GOOGL", Decimal("50"), Decimal("200")),  # 10000
            "MSFT": make_position("MSFT", Decimal("200"), Decimal("50")),  # 10000
        }
        portfolio = make_portfolio(Decimal("70000"), positions=positions)
        # equity = 70000 + 30000 = 100000, gross = 30000

        # New buy of 80000 -> gross = 110000 > 100000 cap
        order = make_buy_order("AMZN", Decimal("800"))
        mark_price = Decimal("100")

        with pytest.raises(ConstraintViolation):
            check_gross_leverage(order, portfolio, mark_price, max_gross_leverage=1.0)


class TestGrossLeverageWithSells:
    """Tests for sell orders in gross leverage calculation."""

    def test_sell_closing_position_still_adds_to_projected(self) -> None:
        """Sell orders add to projected gross exposure in current implementation.

        Note: This tests the CURRENT behavior. The implementation adds order_value
        for both buys and sells, which may need review.
        """
        position = make_position("AAPL", Decimal("1000"), Decimal("100"))
        portfolio = make_portfolio(Decimal("0"), positions={"AAPL": position})
        # equity = 100000, gross = 100000 (fully invested)

        # Sell to close - projected = 100000 + 50000 = 150000
        order = make_sell_order("AAPL", Decimal("500"))
        mark_price = Decimal("100")

        # At 1.0x cap (100000), this would fail in current implementation
        # This may be incorrect behavior - sells should reduce exposure
        with pytest.raises(ConstraintViolation):
            check_gross_leverage(order, portfolio, mark_price, max_gross_leverage=1.0)

        # But passes at 2.0x
        check_gross_leverage(order, portfolio, mark_price, max_gross_leverage=2.0)

    def test_sell_initiating_short_increases_exposure(self) -> None:
        """Sell order creating a short position should increase gross exposure."""
        portfolio = make_portfolio(Decimal("100000"))
        # No positions, equity = 100000

        # Sell (short) AAPL
        order = make_sell_order("AAPL", Decimal("500"))
        mark_price = Decimal("100")  # 50000 exposure

        # Should pass at 1.0x (50000 < 100000)
        check_gross_leverage(order, portfolio, mark_price, max_gross_leverage=1.0)

        # Larger short should fail
        order2 = make_sell_order("AAPL", Decimal("1500"))
        with pytest.raises(ConstraintViolation):
            check_gross_leverage(order2, portfolio, mark_price, max_gross_leverage=1.0)


class TestGrossLeverageEdgeCases:
    """Edge case tests for gross leverage."""

    def test_zero_equity_raises(self) -> None:
        """Zero equity should raise ConstraintViolation."""
        portfolio = make_portfolio(Decimal("0"))
        order = make_buy_order("AAPL", Decimal("1"))
        mark_price = Decimal("100")

        with pytest.raises(ConstraintViolation) as exc_info:
            check_gross_leverage(order, portfolio, mark_price, max_gross_leverage=1.0)

        assert "non-positive equity" in str(exc_info.value).lower()

    def test_negative_equity_raises(self) -> None:
        """Negative equity should raise ConstraintViolation."""
        # Create a position with negative value larger than cash
        position = make_position("AAPL", Decimal("-1000"), Decimal("100"), Decimal("150"))
        portfolio = make_portfolio(
            Decimal("50000"),  # cash
            positions={"AAPL": position},  # -150000 market value
        )
        # equity = 50000 - 150000 = -100000

        order = make_buy_order("GOOGL", Decimal("1"))
        mark_price = Decimal("100")

        with pytest.raises(ConstraintViolation) as exc_info:
            check_gross_leverage(order, portfolio, mark_price, max_gross_leverage=1.0)

        assert "non-positive equity" in str(exc_info.value).lower()

    def test_high_leverage_multiplier(self) -> None:
        """High leverage multiplier should allow more exposure."""
        portfolio = make_portfolio(Decimal("10000"))
        order = make_buy_order("AAPL", Decimal("500"))
        mark_price = Decimal("100")  # 50000 = 5x leverage

        # Should fail at 2x
        with pytest.raises(ConstraintViolation):
            check_gross_leverage(order, portfolio, mark_price, max_gross_leverage=2.0)

        # Should pass at 5x
        check_gross_leverage(order, portfolio, mark_price, max_gross_leverage=5.0)

        # Should pass at 10x
        check_gross_leverage(order, portfolio, mark_price, max_gross_leverage=10.0)

    def test_fractional_leverage_limit(self) -> None:
        """Fractional leverage limits should work correctly."""
        portfolio = make_portfolio(Decimal("100000"))
        order = make_buy_order("AAPL", Decimal("600"))
        mark_price = Decimal("100")  # 60000 = 60% exposure

        # Should fail at 0.5x (50000 cap)
        with pytest.raises(ConstraintViolation):
            check_gross_leverage(order, portfolio, mark_price, max_gross_leverage=0.5)

        # Should pass at 0.75x (75000 cap)
        check_gross_leverage(order, portfolio, mark_price, max_gross_leverage=0.75)


class TestGrossLeveragePropertyBased:
    """Property-based tests for gross leverage."""

    @pytest.mark.parametrize("leverage", [0.5, 1.0, 1.5, 2.0, 3.0])
    def test_leverage_cap_respected(self, leverage: float) -> None:
        """Orders should only pass if projected exposure <= leverage * equity."""
        equity = Decimal("100000")
        portfolio = make_portfolio(equity)
        cap = Decimal(str(leverage)) * equity

        # Order exactly at cap should pass
        order_at_cap = make_buy_order("AAPL", cap / Decimal("100"))
        check_gross_leverage(order_at_cap, portfolio, Decimal("100"), leverage)

        # Order slightly over cap should fail
        order_over_cap = make_buy_order("AAPL", (cap / Decimal("100")) + Decimal("1"))
        with pytest.raises(ConstraintViolation):
            check_gross_leverage(order_over_cap, portfolio, Decimal("100"), leverage)
