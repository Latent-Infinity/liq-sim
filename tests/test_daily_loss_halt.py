"""Tests for daily loss halt (kill-switch) enforcement.

Following TDD: Tests verify max_daily_loss_pct correctly triggers
kill-switch when daily losses exceed threshold.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

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


def make_sell_order(
    symbol: str,
    timestamp: datetime,
    quantity: str,
) -> OrderRequest:
    """Create a sell order for testing."""
    return OrderRequest(
        client_order_id=uuid4(),
        symbol=symbol,
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal(quantity),
        time_in_force=TimeInForce.DAY,
        timestamp=timestamp,
    )


class TestDailyLossHaltTrigger:
    """Tests for daily loss halt trigger conditions."""

    def test_daily_loss_below_threshold_no_halt(self) -> None:
        """Daily loss below threshold should not trigger halt."""
        cfg = make_provider_config()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("100000"),
                max_daily_loss_pct=0.10,  # 10% daily loss limit
                min_order_delay_bars=0,
            ),
        )
        # Set up: start of day equity $100k, current equity $95k = 5% loss (< 10%)
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        sim.daily_start_equity = Decimal("100000")
        sim.account_state.cash = Decimal("95000")

        # Order should fill since kill-switch not triggered
        orders = [make_buy_order("AAPL", t0, "100")]
        bars = [make_bar("AAPL", t0, "100")]

        result = sim.run(orders, bars)

        assert sim.kill_switch_engaged is False
        assert len(result.fills) == 1

    def test_daily_loss_at_threshold_does_not_trigger_halt(self) -> None:
        """Daily loss exactly at threshold should NOT trigger halt (uses strict less-than).

        Note: The simulator uses strict inequality (equity < threshold), so
        exactly at 10% loss with 10% limit doesn't trigger. This tests
        the actual implementation behavior.
        """
        cfg = make_provider_config()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("90000"),  # Start with current cash
                max_daily_loss_pct=0.10,  # 10% daily loss limit
                min_order_delay_bars=0,
            ),
        )
        # Set up: start of day equity $100k, current equity $90k = exactly 10% loss
        # Need to set current_day to avoid reset
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        sim.current_day = t0  # Prevent daily reset
        sim.daily_start_equity = Decimal("100000")

        orders = [make_buy_order("AAPL", t0, "100")]
        bars = [make_bar("AAPL", t0, "100")]

        result = sim.run(orders, bars)

        # Exactly at threshold does NOT trigger (strict <)
        assert sim.kill_switch_engaged is False
        assert len(result.fills) == 1

    def test_daily_loss_exceeds_threshold_triggers_halt(self) -> None:
        """Daily loss exceeding threshold should trigger halt."""
        cfg = make_provider_config()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("85000"),  # Start with current cash
                max_daily_loss_pct=0.10,  # 10% daily loss limit
                min_order_delay_bars=0,
            ),
        )
        # Set up: start of day equity $100k, current equity $85k = 15% loss (> 10%)
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        sim.current_day = t0  # Prevent daily reset
        sim.daily_start_equity = Decimal("100000")

        orders = [make_buy_order("AAPL", t0, "100")]
        bars = [make_bar("AAPL", t0, "100")]

        result = sim.run(orders, bars)

        assert sim.kill_switch_engaged is True
        assert len(result.fills) == 0

    def test_daily_reset_on_new_day(self) -> None:
        """Daily loss counter should reset on new trading day."""
        cfg = make_provider_config()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("85000"),  # Start with $85k
                max_daily_loss_pct=0.10,
                min_order_delay_bars=0,
            ),
        )
        # Day 1: Set up to be in kill-switch state
        day1 = datetime(2024, 1, 1, tzinfo=UTC)
        sim.current_day = day1  # Prevent reset on day 1
        sim.daily_start_equity = Decimal("100000")  # 15% loss triggers kill-switch

        # Verify kill-switch is engaged on day 1
        orders_day1 = [make_buy_order("AAPL", day1, "10")]
        bars_day1 = [make_bar("AAPL", day1, "100")]
        result_day1 = sim.run(orders_day1, bars_day1)
        assert sim.kill_switch_engaged is True
        assert len(result_day1.fills) == 0

        # Day 2: New day should reset daily tracking
        # Reset kill-switch manually (as would happen in real reset)
        sim.kill_switch_engaged = False
        sim.current_day = day1  # Set to day1 so day2 triggers reset
        day2 = datetime(2024, 1, 2, tzinfo=UTC)

        orders_day2 = [make_buy_order("AAPL", day2, "10")]
        bars_day2 = [make_bar("AAPL", day2, "100")]
        result_day2 = sim.run(orders_day2, bars_day2)

        # After day reset, daily_start_equity resets to current equity
        # Loss from $85k is now relative to new day start ($85k), so no loss
        assert len(result_day2.fills) == 1


class TestDailyLossHaltIntegration:
    """Integration tests for daily loss halt in full simulation."""

    def test_simulation_halts_buys_after_daily_loss_breach(self) -> None:
        """Simulation should halt buy orders after daily loss breach."""
        cfg = make_provider_config()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("90000"),  # Current cash
                max_daily_loss_pct=0.05,  # 5% daily loss limit
                min_order_delay_bars=0,
            ),
        )
        # Force a loss situation - set current_day to avoid reset
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        sim.current_day = t0
        sim.daily_start_equity = Decimal("100000")  # 10% loss > 5% threshold

        orders = [make_buy_order("AAPL", t0, "100")]
        bars = [make_bar("AAPL", t0, "100")]

        result = sim.run(orders, bars)

        assert sim.kill_switch_engaged is True
        assert len(result.fills) == 0
        assert len(result.rejected_orders) == 1

    def test_simulation_allows_sells_after_daily_loss_breach(self) -> None:
        """Simulation should allow sells (to close positions) after daily loss breach."""
        cfg = ProviderConfig(
            name="test_broker",
            asset_classes=["equity"],
            fee_model="ZeroCommission",
            slippage_model="VolumeWeighted",
            slippage_params={"base_bps": "0", "volume_impact": "0"},
            short_enabled=True,  # Allow sells
        )
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("100000"),
                max_daily_loss_pct=0.05,  # 5% daily loss limit
                max_position_pct=1.0,
                min_order_delay_bars=0,
            ),
        )
        # Force a loss situation with kill-switch engaged
        sim.daily_start_equity = Decimal("100000")
        sim.account_state.cash = Decimal("90000")  # 10% loss > 5% threshold
        sim.kill_switch_engaged = True

        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Sell order should still work to reduce exposure
        orders = [make_sell_order("AAPL", t0, "100")]
        bars = [make_bar("AAPL", t0, "100")]

        result = sim.run(orders, bars)

        # Sells should still be allowed even with kill-switch
        assert len(result.fills) == 1

    def test_kill_switch_reason_captured_in_rejection(self) -> None:
        """Kill-switch rejection should capture reason in result."""
        cfg = make_provider_config()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("90000"),  # Current cash
                max_daily_loss_pct=0.05,
                min_order_delay_bars=0,
            ),
        )
        # Force kill-switch state - set current_day to avoid reset
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        sim.current_day = t0
        sim.daily_start_equity = Decimal("100000")  # 10% loss > 5% threshold

        orders = [make_buy_order("AAPL", t0, "100")]
        bars = [make_bar("AAPL", t0, "100")]

        result = sim.run(orders, bars)

        assert len(result.rejected_orders) == 1
        rejection = result.rejected_orders[0]
        assert "kill" in rejection.reason.lower() or "switch" in rejection.reason.lower()


class TestDrawdownHalt:
    """Tests for drawdown-based kill-switch."""

    def test_drawdown_within_limit_no_halt(self) -> None:
        """Drawdown within limit should not trigger halt."""
        cfg = make_provider_config()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("95000"),
                max_drawdown_pct=0.10,  # 10% max drawdown
                min_order_delay_bars=0,
            ),
        )
        # Peak equity $100k, current $95k = 5% drawdown (< 10%)
        sim.peak_equity = Decimal("100000")

        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        orders = [make_buy_order("AAPL", t0, "100")]
        bars = [make_bar("AAPL", t0, "100")]

        result = sim.run(orders, bars)

        assert sim.kill_switch_engaged is False
        assert len(result.fills) == 1

    def test_drawdown_exceeding_limit_triggers_halt(self) -> None:
        """Drawdown exceeding limit should trigger halt."""
        cfg = make_provider_config()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("85000"),
                max_drawdown_pct=0.10,  # 10% max drawdown
                min_order_delay_bars=0,
            ),
        )
        # Peak equity $100k, current $85k = 15% drawdown (> 10%)
        sim.peak_equity = Decimal("100000")

        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        orders = [make_buy_order("AAPL", t0, "100")]
        bars = [make_bar("AAPL", t0, "100")]

        result = sim.run(orders, bars)

        assert sim.kill_switch_engaged is True
        assert len(result.fills) == 0

    def test_both_daily_loss_and_drawdown_checked(self) -> None:
        """Both daily loss and drawdown limits should be enforced."""
        cfg = make_provider_config()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("93000"),  # Current cash
                max_daily_loss_pct=0.05,  # 5% daily loss
                max_drawdown_pct=0.10,  # 10% drawdown
                min_order_delay_bars=0,
            ),
        )
        # Set up: within drawdown limit but exceed daily loss
        # Need to set current_day to avoid reset
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        sim.current_day = t0
        sim.peak_equity = Decimal("100000")  # 7% drawdown (< 10%)
        sim.daily_start_equity = Decimal("100000")  # 7% daily loss (> 5%)

        orders = [make_buy_order("AAPL", t0, "100")]
        bars = [make_bar("AAPL", t0, "100")]

        result = sim.run(orders, bars)

        # Should trigger because daily loss exceeds 5%
        assert sim.kill_switch_engaged is True
        assert len(result.fills) == 0
