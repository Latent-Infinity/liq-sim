"""Tests for equity floor enforcement.

Following TDD: Tests verify simulation halts when equity reaches zero or negative.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from liq.core import Bar, OrderRequest
from liq.core.enums import OrderSide, OrderType, TimeInForce

from liq.sim.config import ProviderConfig, SimulatorConfig
from liq.sim.simulator import Simulator


def make_provider_config() -> ProviderConfig:
    """Create a standard provider config for testing."""
    return ProviderConfig(
        name="test_broker",
        asset_classes=["equity"],
        fee_model="ZeroCommission",
        slippage_model="VolumeWeighted",
        slippage_params={"base_bps": "0", "volume_impact": "0"},
    )


def make_bar(symbol: str, ts: datetime, price: str, volume: str = "1000000") -> Bar:
    """Create a bar for testing."""
    return Bar(
        symbol=symbol,
        timestamp=ts,
        open=Decimal(price),
        high=Decimal(price),
        low=Decimal(price),
        close=Decimal(price),
        volume=Decimal(volume),
    )


def make_buy_order(
    symbol: str,
    timestamp: datetime,
    quantity: str,
) -> OrderRequest:
    """Create a buy order for testing."""
    return OrderRequest(
        client_order_id=uuid4(),
        symbol=symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal(quantity),
        time_in_force=TimeInForce.DAY,
        timestamp=timestamp,
    )


class TestEquityFloor:
    """Tests for equity floor (halt at zero/negative equity)."""

    def test_positive_equity_allows_trading(self) -> None:
        """Positive equity should allow normal trading."""
        cfg = make_provider_config()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("10000"),
                min_order_delay_bars=0,
            ),
        )
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        orders = [make_buy_order("AAPL", t0, "10")]
        bars = [make_bar("AAPL", t0, "100")]

        result = sim.run(orders, bars)

        assert len(result.fills) == 1
        # Final equity should be positive
        assert result.portfolio_states[-1].equity > 0

    def test_zero_equity_halts_simulation(self) -> None:
        """Zero equity should halt simulation."""
        cfg = make_provider_config()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("0"),
                min_order_delay_bars=0,
            ),
        )
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        orders = [make_buy_order("AAPL", t0, "10")]
        bars = [make_bar("AAPL", t0, "100")]

        result = sim.run(orders, bars)

        # No fills should occur with zero equity
        assert len(result.fills) == 0
        # Equity curve should show zero
        assert result.equity_curve[-1][1] == Decimal("0")

    def test_negative_equity_halts_simulation(self) -> None:
        """Negative equity should halt simulation.

        Note: This tests an edge case where a position has negative market value
        that exceeds cash (e.g., a large short position with adverse move).
        """
        cfg = ProviderConfig(
            name="test_broker",
            asset_classes=["equity"],
            fee_model="ZeroCommission",
            slippage_model="VolumeWeighted",
            slippage_params={"base_bps": "0", "volume_impact": "0"},
            short_enabled=True,
        )
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("10000"),
                max_position_pct=1.0,
                min_order_delay_bars=0,
            ),
        )

        # Set up a situation where equity would be negative
        # Simulate a short position that has gone badly wrong
        # Create position directly in account state
        from liq.sim.accounting import PositionLot, PositionRecord

        sim.account_state.positions["AAPL"] = PositionRecord(
            lots=[
                PositionLot(
                    quantity=Decimal("-1000"),  # Short 1000 shares
                    entry_price=Decimal("100"),
                    entry_time=datetime(2024, 1, 1, tzinfo=UTC),
                )
            ],
            realized_pnl=Decimal("0"),
        )
        # Short at $100, now price is $200 = -$100k unrealized loss
        # Cash: $10k + $100k short proceeds = $110k
        # But marking at $200: equity = $110k - $200k (to cover) = -$90k
        sim.account_state.cash = Decimal("110000")

        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        orders = [make_buy_order("GOOGL", t0, "10")]
        bars = [
            make_bar("AAPL", t0, "200"),  # Price doubled - disastrous for short
            make_bar("GOOGL", t0, "100"),
        ]

        result = sim.run(orders, bars)

        # Simulation should halt - no new trades
        assert len(result.fills) == 0
        # Final equity should be non-positive
        assert result.equity_curve[-1][1] <= 0


class TestEquityFloorIntegration:
    """Integration tests for equity floor in simulation scenarios."""

    def test_simulation_stops_processing_at_zero_equity(self) -> None:
        """Simulation should stop processing bars when equity hits zero."""
        cfg = make_provider_config()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("0"),
                min_order_delay_bars=0,
            ),
        )
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        t1 = datetime(2024, 1, 2, tzinfo=UTC)
        t2 = datetime(2024, 1, 3, tzinfo=UTC)

        # Multiple days of bars
        orders = [
            make_buy_order("AAPL", t0, "10"),
            make_buy_order("AAPL", t1, "10"),
            make_buy_order("AAPL", t2, "10"),
        ]
        bars = [
            make_bar("AAPL", t0, "100"),
            make_bar("AAPL", t1, "100"),
            make_bar("AAPL", t2, "100"),
        ]

        result = sim.run(orders, bars)

        # Should halt early - only one bar processed
        assert len(result.equity_curve) == 1
        assert len(result.portfolio_states) == 1

    def test_total_return_never_exceeds_negative_100_percent(self) -> None:
        """Total return should never exceed -100% (equity floor at 0)."""
        cfg = make_provider_config()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("1000"),
                min_order_delay_bars=0,
            ),
        )
        # Start with small capital
        initial_equity = Decimal("1000")

        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        orders = []  # No orders, just observe
        bars = [make_bar("AAPL", t0, "100")]

        result = sim.run(orders, bars)

        # Calculate return
        final_equity = result.equity_curve[-1][1]
        # Return should be >= -100%
        if initial_equity > 0:
            return_pct = (final_equity - initial_equity) / initial_equity
            assert return_pct >= Decimal("-1")

    def test_equity_floor_with_sequence_of_losing_trades(self) -> None:
        """Equity floor should stop simulation during losing sequence."""
        cfg = make_provider_config()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("100"),  # Very small capital
                min_order_delay_bars=0,
                max_position_pct=1.0,
            ),
        )
        t0 = datetime(2024, 1, 1, tzinfo=UTC)

        # Try to buy more than we can afford
        orders = [make_buy_order("AAPL", t0, "10")]  # $1000 > $100
        bars = [make_bar("AAPL", t0, "100")]

        result = sim.run(orders, bars)

        # Order should be rejected due to insufficient buying power
        assert len(result.fills) == 0
        # But equity should still be positive (just can't trade)
        assert result.equity_curve[-1][1] > 0


class TestEquityFloorConstraintViolations:
    """Tests for constraint violations related to zero/negative equity."""

    def test_order_rejected_with_zero_equity(self) -> None:
        """Orders should be rejected when equity is zero."""
        cfg = make_provider_config()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("0"),
                min_order_delay_bars=0,
            ),
        )
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        orders = [make_buy_order("AAPL", t0, "1")]
        bars = [make_bar("AAPL", t0, "100")]

        result = sim.run(orders, bars)

        # No fills with zero equity - simulation halts before processing orders
        assert len(result.fills) == 0

    def test_gross_leverage_check_rejects_with_zero_equity(self) -> None:
        """Gross leverage check should reject order with zero equity."""
        from liq.core import PortfolioState

        from liq.sim.constraints import ConstraintViolation, check_gross_leverage

        portfolio = PortfolioState(
            cash=Decimal("0"),
            unsettled_cash=Decimal("0"),
            positions={},
            realized_pnl=Decimal("0"),
            timestamp=datetime.now(UTC),
        )
        order = make_buy_order("AAPL", datetime.now(UTC), "1")

        with pytest.raises(ConstraintViolation) as exc_info:
            check_gross_leverage(order, portfolio, Decimal("100"), max_gross_leverage=1.0)

        assert "non-positive equity" in str(exc_info.value).lower()

    def test_position_limit_check_rejects_with_zero_equity(self) -> None:
        """Position limit check should reject order with zero equity."""
        from liq.core import PortfolioState

        from liq.sim.constraints import ConstraintViolation, check_position_limit

        portfolio = PortfolioState(
            cash=Decimal("0"),
            unsettled_cash=Decimal("0"),
            positions={},
            realized_pnl=Decimal("0"),
            timestamp=datetime.now(UTC),
        )
        order = make_buy_order("AAPL", datetime.now(UTC), "1")

        with pytest.raises(ConstraintViolation) as exc_info:
            check_position_limit(order, portfolio, max_position_pct=0.25, mark_price=Decimal("100"))

        assert "non-positive equity" in str(exc_info.value).lower()
