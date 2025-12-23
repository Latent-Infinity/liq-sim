"""Tests for fee affordability and edge cases.

Following TDD: Tests verify fee handling behavior and document
whether fees can push cash negative.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from liq.core import Bar, OrderRequest
from liq.core.enums import OrderSide, OrderType, TimeInForce

from liq.sim.config import ProviderConfig, SimulatorConfig
from liq.sim.simulator import Simulator


def make_provider_with_fees() -> ProviderConfig:
    """Create a provider config with non-zero fees."""
    return ProviderConfig(
        name="test_broker_fees",
        asset_classes=["equity"],
        fee_model="TieredMakerTaker",
        fee_params={"maker_bps": "10", "taker_bps": "20"},  # 0.1% / 0.2%
        slippage_model="VolumeWeighted",
        slippage_params={"base_bps": "0", "volume_impact": "0"},
    )


def make_provider_zero_fees() -> ProviderConfig:
    """Create a provider config with zero fees."""
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


class TestFeeDeduction:
    """Tests for fee deduction during order execution."""

    def test_fee_deducted_from_cash_on_fill(self) -> None:
        """Fees should be deducted from cash when order fills."""
        cfg = make_provider_with_fees()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("10000"),
                min_order_delay_bars=0,
            ),
        )
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Buy 10 shares @ $100 = $1000 notional
        # Taker fee: $1000 * 20bps = $2
        orders = [make_buy_order("AAPL", t0, "10")]
        bars = [make_bar("AAPL", t0, "100")]

        result = sim.run(orders, bars)

        assert len(result.fills) == 1
        fill = result.fills[0]
        assert fill.commission == Decimal("2")  # 20 bps of $1000
        # Cash should be reduced by notional + commission
        # $10000 - $1000 - $2 = $8998
        assert sim.account_state.cash == Decimal("8998")

    def test_zero_fee_provider_no_deduction(self) -> None:
        """Zero fee provider should not deduct commission."""
        cfg = make_provider_zero_fees()
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
        fill = result.fills[0]
        assert fill.commission == Decimal("0")
        # Cash: $10000 - $1000 = $9000
        assert sim.account_state.cash == Decimal("9000")


class TestFeeAffordability:
    """Tests for fee affordability edge cases.

    Note: Current implementation does NOT check fee affordability pre-trade.
    Fees are deducted post-fill and can push cash negative.
    These tests document the current behavior.
    """

    def test_order_using_exact_cash_succeeds_fee_deducted(self) -> None:
        """Order using exact cash amount should succeed, fee deducted after."""
        cfg = make_provider_with_fees()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("1000"),  # Exactly enough for 10 shares @ $100
                max_position_pct=1.0,  # Disable position limit
                min_order_delay_bars=0,
            ),
        )
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Buy 10 shares @ $100 = $1000 notional (exactly our cash)
        # Fee: $2 taker
        orders = [make_buy_order("AAPL", t0, "10")]
        bars = [make_bar("AAPL", t0, "100")]

        result = sim.run(orders, bars)

        assert len(result.fills) == 1
        # Cash goes negative by the fee amount
        # $1000 - $1000 - $2 = -$2
        assert sim.account_state.cash == Decimal("-2")

    def test_fee_can_push_cash_negative_documented_behavior(self) -> None:
        """Document: Fees can push cash negative in current implementation.

        This test documents the current behavior where fees are not
        checked pre-trade. A future enhancement could add pre-trade
        fee affordability checks.
        """
        cfg = make_provider_with_fees()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("1001"),  # $1 more than notional
                max_position_pct=1.0,  # Disable position limit
                min_order_delay_bars=0,
            ),
        )
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Buy 10 shares @ $100 = $1000 notional
        # Fee: $2 taker
        # Total cost: $1002
        orders = [make_buy_order("AAPL", t0, "10")]
        bars = [make_bar("AAPL", t0, "100")]

        result = sim.run(orders, bars)

        assert len(result.fills) == 1
        # Cash: $1001 - $1000 - $2 = -$1
        assert sim.account_state.cash == Decimal("-1")

    def test_buying_power_check_ignores_fees(self) -> None:
        """Buying power check does not account for fees (documents current behavior)."""
        cfg = make_provider_with_fees()
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("1000"),
                max_position_pct=1.0,  # Disable position limit
                min_order_delay_bars=0,
            ),
        )
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Order exactly equal to cash passes buying power check
        # but fee makes it exceed actual affordability
        orders = [make_buy_order("AAPL", t0, "10")]
        bars = [make_bar("AAPL", t0, "100")]

        result = sim.run(orders, bars)

        # Order passes buying power check (notional == cash)
        # Fee is deducted afterward, pushing cash negative
        assert len(result.fills) == 1
        assert sim.account_state.cash < 0


class TestFeeModels:
    """Tests for different fee model behaviors in simulation."""

    def test_tiered_maker_taker_limit_order_as_maker(self) -> None:
        """Limit order away from market should get maker fee."""
        cfg = ProviderConfig(
            name="test_broker",
            asset_classes=["equity"],
            fee_model="TieredMakerTaker",
            fee_params={"maker_bps": "10", "taker_bps": "20"},
            slippage_model="VolumeWeighted",
            slippage_params={"base_bps": "0", "volume_impact": "0"},
        )
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("10000"),
                min_order_delay_bars=0,
            ),
        )
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Limit buy below market should be maker
        order = OrderRequest(
            client_order_id=uuid4(),
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("10"),
            limit_price=Decimal("99"),  # Below open of 100
            time_in_force=TimeInForce.DAY,
            timestamp=t0,
        )
        bar = Bar(
            symbol="AAPL",
            timestamp=t0,
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("98"),  # Low hits limit
            close=Decimal("99"),
            volume=Decimal("1000000"),
        )

        result = sim.run([order], [bar])

        assert len(result.fills) == 1
        # Maker fee: 10 bps of (10 * 100) = $1
        assert result.fills[0].commission == Decimal("1")

    def test_per_share_fee_model(self) -> None:
        """Per-share fee model should calculate correctly."""
        cfg = ProviderConfig(
            name="test_broker",
            asset_classes=["equity"],
            fee_model="PerShare",
            fee_params={"per_share": "0.01", "min_per_order": "1.00"},
            slippage_model="VolumeWeighted",
            slippage_params={"base_bps": "0", "volume_impact": "0"},
        )
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("10000"),
                min_order_delay_bars=0,
            ),
        )
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # 10 shares * $0.01 = $0.10, but min is $1.00
        orders = [make_buy_order("AAPL", t0, "10")]
        bars = [make_bar("AAPL", t0, "100")]

        result = sim.run(orders, bars)

        assert len(result.fills) == 1
        assert result.fills[0].commission == Decimal("1.00")  # Minimum applies

    def test_per_share_fee_above_minimum(self) -> None:
        """Per-share fee above minimum should use actual fee."""
        cfg = ProviderConfig(
            name="test_broker",
            asset_classes=["equity"],
            fee_model="PerShare",
            fee_params={"per_share": "0.01", "min_per_order": "1.00"},
            slippage_model="VolumeWeighted",
            slippage_params={"base_bps": "0", "volume_impact": "0"},
        )
        sim = Simulator(
            provider_config=cfg,
            config=SimulatorConfig(
                initial_capital=Decimal("100000"),
                min_order_delay_bars=0,
            ),
        )
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # 200 shares * $0.01 = $2.00, above $1.00 min
        orders = [make_buy_order("AAPL", t0, "200")]
        bars = [make_bar("AAPL", t0, "100")]

        result = sim.run(orders, bars)

        assert len(result.fills) == 1
        assert result.fills[0].commission == Decimal("2.00")
