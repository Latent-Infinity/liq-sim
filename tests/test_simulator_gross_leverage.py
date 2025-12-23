"""Integration tests for gross leverage constraint in simulator.

Following TDD: These tests verify the simulator correctly enforces
gross leverage limits during full simulation runs.
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


class TestSimulatorGrossLeverageRejection:
    """Tests verifying simulator rejects orders exceeding gross leverage."""

    def test_single_order_exceeding_leverage_rejected(self) -> None:
        """Order exceeding leverage limit should be rejected by simulator."""
        cfg = make_provider_config()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("100000"),
                max_gross_leverage=0.5,  # 0.5x leverage cap = $50k max
                max_position_pct=1.0,  # Disable position limit to test gross leverage
                min_order_delay_bars=0,
            ),
        )
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Order for 600 shares @ $100 = $60k > 0.5x leverage cap ($50k)
        orders = [make_buy_order("AAPL", t0, "600")]
        bars = [make_bar("AAPL", t0, "100")]

        result = sim.run(orders, bars)

        assert len(result.fills) == 0
        assert len(result.rejected_orders) == 1
        assert "leverage" in result.rejected_orders[0].reason.lower()

    def test_order_within_leverage_fills(self) -> None:
        """Order within leverage limit should fill."""
        cfg = make_provider_config()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("100000"),
                max_gross_leverage=1.0,
                max_position_pct=1.0,  # Disable position limit to test gross leverage
                min_order_delay_bars=0,
            ),
        )
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Order for 500 shares @ $100 = $50k = 0.5x leverage (within 1.0x)
        orders = [make_buy_order("AAPL", t0, "500")]
        bars = [make_bar("AAPL", t0, "100")]

        result = sim.run(orders, bars)

        assert len(result.fills) == 1
        assert result.fills[0].quantity == Decimal("500")
        assert len(result.rejected_orders) == 0

    def test_order_exactly_at_leverage_fills(self) -> None:
        """Order exactly at leverage limit should fill."""
        cfg = make_provider_config()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("100000"),
                max_gross_leverage=1.0,
                max_position_pct=1.0,  # Disable position limit to test gross leverage
                min_order_delay_bars=0,
            ),
        )
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Order for 1000 shares @ $100 = $100k = 1.0x leverage (exactly at limit)
        orders = [make_buy_order("AAPL", t0, "1000")]
        bars = [make_bar("AAPL", t0, "100")]

        result = sim.run(orders, bars)

        assert len(result.fills) == 1
        assert result.fills[0].quantity == Decimal("1000")


class TestSimulatorGrossLeverageMultiOrder:
    """Tests for multi-order gross leverage enforcement."""

    def test_sequential_orders_cumulative_leverage(self) -> None:
        """Multiple orders should respect cumulative leverage."""
        cfg = make_provider_config()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("100000"),
                max_gross_leverage=0.8,  # 0.8x = $80k max total exposure
                max_position_pct=1.0,  # Disable position limit to test gross leverage
                min_order_delay_bars=0,
            ),
        )
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        t1 = datetime(2024, 1, 2, tzinfo=UTC)
        # First order: 500 shares @ $100 = $50k = 0.5x
        # Second order: 500 shares @ $100 = $50k, total would be 1.0x > 0.8x
        orders = [
            make_buy_order("AAPL", t0, "500"),
            make_buy_order("AAPL", t1, "500"),
        ]
        bars = [
            make_bar("AAPL", t0, "100"),
            make_bar("AAPL", t1, "100"),
        ]

        result = sim.run(orders, bars)

        # First order should fill, second should be rejected
        assert len(result.fills) == 1
        assert result.fills[0].quantity == Decimal("500")
        assert len(result.rejected_orders) == 1
        assert "leverage" in result.rejected_orders[0].reason.lower()

    def test_multiple_symbols_summed(self) -> None:
        """Leverage should sum across symbols."""
        cfg = make_provider_config()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("100000"),
                max_gross_leverage=1.0,
                max_position_pct=1.0,  # Disable position limit to test gross leverage
                min_order_delay_bars=0,
            ),
        )
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        t1 = datetime(2024, 1, 2, tzinfo=UTC)
        # First order: AAPL 600 shares @ $100 = $60k = 0.6x
        # Second order: GOOGL 600 shares @ $100 = $60k, total would be 1.2x > 1.0x
        orders = [
            make_buy_order("AAPL", t0, "600"),
            make_buy_order("GOOGL", t1, "600"),
        ]
        bars = [
            make_bar("AAPL", t0, "100"),
            make_bar("AAPL", t1, "100"),
            make_bar("GOOGL", t1, "100"),
        ]

        result = sim.run(orders, bars)

        # First order fills, second rejected due to cumulative leverage
        assert len(result.fills) == 1
        assert len(result.rejected_orders) == 1


class TestSimulatorGrossLeverageWithShorts:
    """Tests for gross leverage with short positions."""

    def test_short_position_counts_toward_gross(self) -> None:
        """Short positions should count toward gross leverage."""
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
                initial_capital=Decimal("100000"),
                max_gross_leverage=1.0,
                max_position_pct=1.0,  # Disable position limit to test gross leverage
                min_order_delay_bars=0,
            ),
        )
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        t1 = datetime(2024, 1, 2, tzinfo=UTC)
        # Short AAPL: 600 shares @ $100 = $60k = 0.6x gross
        # Buy GOOGL: 600 shares @ $100 = $60k, total gross would be 1.2x > 1.0x
        orders = [
            make_sell_order("AAPL", t0, "600"),
            make_buy_order("GOOGL", t1, "600"),
        ]
        bars = [
            make_bar("AAPL", t0, "100"),
            make_bar("AAPL", t1, "100"),
            make_bar("GOOGL", t1, "100"),
        ]

        result = sim.run(orders, bars)

        # Short fills, then buy is rejected
        assert len(result.fills) == 1
        assert result.fills[0].side == OrderSide.SELL
        assert len(result.rejected_orders) == 1


def make_margin_provider_config() -> ProviderConfig:
    """Create a margin-enabled provider config for leverage testing."""
    return ProviderConfig(
        name="test_margin_broker",
        asset_classes=["equity"],
        fee_model="ZeroCommission",
        slippage_model="VolumeWeighted",
        slippage_params={"base_bps": "0", "volume_impact": "0"},
        margin_type="RegT",
        initial_margin_rate=Decimal("0.5"),  # 50% margin = 2x buying power
    )


class TestSimulatorGrossLeverageConfig:
    """Tests for different leverage configurations."""

    def test_high_leverage_with_margin_rejected_by_gross_leverage(self) -> None:
        """Orders exceeding gross leverage should be rejected even with margin.

        This tests that gross leverage constraint is enforced independently
        of margin/buying power constraints.
        """
        cfg = make_margin_provider_config()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("100000"),
                max_gross_leverage=0.8,  # 0.8x leverage cap = $80k max
                max_position_pct=1.0,  # Disable position limit
                min_order_delay_bars=0,
            ),
        )
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Order for 900 shares @ $100 = $90k = 0.9x (exceeds 0.8x gross leverage)
        # Even though margin is satisfied, gross leverage is exceeded
        orders = [make_buy_order("AAPL", t0, "900")]
        bars = [make_bar("AAPL", t0, "100")]

        result = sim.run(orders, bars)

        assert len(result.fills) == 0
        assert len(result.rejected_orders) == 1
        assert "leverage" in result.rejected_orders[0].reason.lower()

    def test_fractional_leverage_limit(self) -> None:
        """Fractional leverage limits should work."""
        cfg = make_provider_config()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("100000"),
                max_gross_leverage=0.5,  # 0.5x leverage (conservative)
                max_position_pct=1.0,  # Disable position limit to test gross leverage
                min_order_delay_bars=0,
            ),
        )
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Order for 600 shares @ $100 = $60k = 0.6x (exceeds 0.5x)
        orders = [make_buy_order("AAPL", t0, "600")]
        bars = [make_bar("AAPL", t0, "100")]

        result = sim.run(orders, bars)

        assert len(result.fills) == 0
        assert len(result.rejected_orders) == 1
        assert "leverage" in result.rejected_orders[0].reason.lower()

    @pytest.mark.parametrize("leverage", [0.25, 0.5, 0.75, 1.0])
    def test_leverage_boundary_respected(self, leverage: float) -> None:
        """Orders at boundary should fill, orders over should reject.

        Note: Tests limited to <= 1.0x leverage since higher requires margin.
        """
        cfg = make_provider_config()
        equity = Decimal("100000")
        cap = equity * Decimal(str(leverage))
        price = Decimal("100")
        shares_at_cap = int(cap / price)

        # Test exactly at cap (should fill)
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=equity,
                max_gross_leverage=leverage,
                max_position_pct=1.0,  # Disable position limit to test gross leverage
                min_order_delay_bars=0,
            ),
        )
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        orders = [make_buy_order("AAPL", t0, str(shares_at_cap))]
        bars = [make_bar("AAPL", t0, "100")]

        result = sim.run(orders, bars)
        assert len(result.fills) == 1

        # Test 1 share over cap (should reject)
        sim2 = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=equity,
                max_gross_leverage=leverage,
                max_position_pct=1.0,  # Disable position limit to test gross leverage
                min_order_delay_bars=0,
            ),
        )
        orders2 = [make_buy_order("AAPL", t0, str(shares_at_cap + 1))]
        result2 = sim2.run(orders2, bars)
        assert len(result2.fills) == 0
        assert len(result2.rejected_orders) == 1


class TestSimulatorGrossLeverageWithMarkPrices:
    """Tests for gross leverage using current mark prices."""

    def test_leverage_uses_current_bar_price(self) -> None:
        """Leverage check should use current bar's price."""
        cfg = make_provider_config()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("100000"),
                max_gross_leverage=1.0,
                max_position_pct=1.0,  # Disable position limit to test gross leverage
                min_order_delay_bars=0,
            ),
        )
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # 500 shares @ $200 = $100k = 1.0x (at limit)
        orders = [make_buy_order("AAPL", t0, "500")]
        bars = [make_bar("AAPL", t0, "200")]

        result = sim.run(orders, bars)

        assert len(result.fills) == 1

        # Now try 501 shares @ $200 = $100.2k > 1.0x
        sim2 = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("100000"),
                max_gross_leverage=1.0,
                max_position_pct=1.0,  # Disable position limit to test gross leverage
                min_order_delay_bars=0,
            ),
        )
        orders2 = [make_buy_order("AAPL", t0, "501")]
        result2 = sim2.run(orders2, bars)

        assert len(result2.fills) == 0
        assert len(result2.rejected_orders) == 1
