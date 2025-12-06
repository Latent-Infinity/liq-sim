from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from liq.sim.config import ProviderConfig, SimulatorConfig
from liq.sim.simulator import Simulator
from liq.core import Bar, OrderRequest
from liq.core.enums import OrderSide, OrderType, TimeInForce


def make_order(timestamp: datetime, qty: str, price: str) -> OrderRequest:
    return OrderRequest(
        client_order_id=uuid4(),
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal(qty),
        time_in_force=TimeInForce.DAY,
        timestamp=timestamp,
    )


def make_bar(ts: datetime, open_price: str) -> Bar:
    return Bar(
        symbol="AAPL",
        timestamp=ts,
        open=Decimal(open_price),
        high=Decimal(open_price),
        low=Decimal(open_price),
        close=Decimal(open_price),
        volume=Decimal("1000"),
    )


def test_position_limit_blocks_order() -> None:
    cfg = ProviderConfig(
        name="coinbase",
        asset_classes=["crypto"],
        fee_model="ZeroCommission",
        slippage_model="VolumeWeighted",
        slippage_params={"base_bps": "0", "volume_impact": "0"},
    )
    sim = Simulator(provider_config=cfg, config=SimulatorConfig(max_position_pct=0.1))
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    # order value 2000 vs equity 0 cash -> will raise due to non-positive equity
    orders = [make_order(t0, qty="20", price="100")]
    bars = [make_bar(t0, "100")]
    result = sim.run(orders, bars)
    assert len(result.fills) == 0


def test_rejected_orders_tracked_in_result() -> None:
    """Rejected orders should be recorded in SimulationResult.rejected_orders."""
    cfg = ProviderConfig(
        name="coinbase",
        asset_classes=["crypto"],
        fee_model="ZeroCommission",
        slippage_model="VolumeWeighted",
        slippage_params={"base_bps": "0", "volume_impact": "0"},
    )
    # Small capital, order will exceed buying power
    sim = Simulator(
        provider_config=cfg,
        config=SimulatorConfig(initial_capital=Decimal("100"), min_order_delay_bars=0),
    )
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    # Order value = 10 * 100 = 1000, but only 100 cash available
    orders = [make_order(t0, qty="10", price="100")]
    bars = [make_bar(t0, "100")]

    result = sim.run(orders, bars)

    assert len(result.fills) == 0
    assert len(result.rejected_orders) == 1
    rejected = result.rejected_orders[0]
    assert rejected.order.quantity == Decimal("10")
    assert "buying power" in rejected.reason.lower() or "equity" in rejected.reason.lower()


def test_multiple_rejections_all_tracked() -> None:
    """Multiple rejected orders should all be recorded."""
    cfg = ProviderConfig(
        name="coinbase",
        asset_classes=["crypto"],
        fee_model="ZeroCommission",
        slippage_model="VolumeWeighted",
        slippage_params={"base_bps": "0", "volume_impact": "0"},
    )
    sim = Simulator(
        provider_config=cfg,
        config=SimulatorConfig(initial_capital=Decimal("50"), min_order_delay_bars=0),
    )
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    t1 = datetime(2024, 1, 2, tzinfo=timezone.utc)
    # Both orders exceed buying power
    orders = [
        make_order(t0, qty="10", price="100"),
        make_order(t1, qty="5", price="100"),
    ]
    bars = [make_bar(t0, "100"), make_bar(t1, "100")]

    result = sim.run(orders, bars)

    assert len(result.fills) == 0
    assert len(result.rejected_orders) == 2
