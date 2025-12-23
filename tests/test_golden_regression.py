from datetime import UTC, datetime, timedelta
from decimal import Decimal

from liq.core import Bar, OrderRequest
from liq.core.enums import OrderSide, OrderType, TimeInForce

from liq.sim.config import ProviderConfig, SimulatorConfig
from liq.sim.simulator import Simulator


def make_bar(ts: datetime, price: str) -> Bar:
    return Bar(
        symbol="BTC-USD",
        timestamp=ts,
        open=Decimal(price),
        high=Decimal(price),
        low=Decimal(price),
        close=Decimal(price),
        volume=Decimal("1000"),
    )


def test_golden_equity_curve_regression() -> None:
    """Deterministic regression: 1 buy then hold."""
    provider_cfg = ProviderConfig(
        name="coinbase",
        asset_classes=["crypto"],
        fee_model="ZeroCommission",
        slippage_model="VolumeWeighted",
        slippage_params={"base_bps": "0", "volume_impact": "0"},
    )
    sim_cfg = SimulatorConfig(initial_capital=Decimal("1000"), min_order_delay_bars=0)
    sim = Simulator(provider_config=provider_cfg, config=sim_cfg)

    t0 = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    order = OrderRequest(
        symbol="BTC-USD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        time_in_force=TimeInForce.DAY,
        timestamp=t0,
    )
    bars = [make_bar(t0, "100"), make_bar(t0 + timedelta(minutes=1), "110")]

    result = sim.run([order], bars)
    # One fill, no commission or slippage
    assert len(result.fills) == 1
    fill = result.fills[0]
    assert fill.price == Decimal("100")
    assert fill.slippage == Decimal("0")
    assert fill.commission == Decimal("0")

    # Equity curve matches expected marks: start 1000 -> hold at 100 -> mark at 110
    assert result.portfolio_history == [Decimal("1000"), Decimal("1010")]
    assert result.equity_curve[-1][1] == Decimal("1010")
