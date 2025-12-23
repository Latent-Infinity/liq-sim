from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from liq.core import Bar, OrderRequest
from liq.core.enums import OrderType, TimeInForce

from liq.sim.config import ProviderConfig, SimulatorConfig
from liq.sim.simulator import Simulator


def make_order(timestamp: datetime, side: str, qty: str) -> OrderRequest:
    return OrderRequest(
        client_order_id=uuid4(),
        symbol="AAPL",
        side=side,
        order_type=OrderType.MARKET,
        quantity=Decimal(qty),
        time_in_force=TimeInForce.DAY,
        timestamp=timestamp,
    )


def make_bar(ts: datetime, price: str) -> Bar:
    return Bar(
        symbol="AAPL",
        timestamp=ts,
        open=Decimal(price),
        high=Decimal(price),
        low=Decimal(price),
        close=Decimal(price),
        volume=Decimal("1000"),
    )


def test_kill_switch_blocks_buys_after_drawdown() -> None:
    provider_cfg = ProviderConfig(
        name="coinbase",
        asset_classes=["crypto"],
        fee_model="ZeroCommission",
        slippage_model="VolumeWeighted",
        slippage_params={"base_bps": "0", "volume_impact": "0"},
    )
    sim = Simulator(
        provider_config=provider_cfg,
        config=SimulatorConfig(max_drawdown_pct=0.1, initial_capital=Decimal("0")),
    )
    # Force peak at 100 then current equity 50 to trigger drawdown kill-switch
    sim.peak_equity = Decimal("100")
    sim.daily_start_equity = Decimal("100")
    sim.account_state.cash = Decimal("50")

    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    orders = [make_order(t0, side="buy", qty="1")]
    bars = [make_bar(t0, "10")]

    result = sim.run(orders, bars)
    assert len(result.fills) == 0
    assert sim.kill_switch_engaged is True
