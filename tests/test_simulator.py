from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from liq.core import Bar, OrderRequest
from liq.core.enums import OrderType, TimeInForce

from liq.sim.config import ProviderConfig, SimulatorConfig
from liq.sim.simulator import Simulator


def make_order(timestamp: datetime, side: str, qty: str, limit: str | None = None) -> OrderRequest:
    return OrderRequest(
        client_order_id=uuid4(),
        symbol="AAPL",
        side=side,
        order_type=OrderType.LIMIT if limit else OrderType.MARKET,
        quantity=Decimal(qty),
        limit_price=Decimal(limit) if limit else None,
        time_in_force=TimeInForce.DAY,
        timestamp=timestamp,
    )


def make_bar(ts: datetime, open_price: str, high: str, low: str, close: str) -> Bar:
    return Bar(
        symbol="AAPL",
        timestamp=ts,
        open=Decimal(open_price),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("1000"),
    )


def test_simulator_executes_with_delay_and_fees() -> None:
    provider_cfg = ProviderConfig(
        name="coinbase",
        asset_classes=["crypto"],
        fee_model="TieredMakerTaker",
        fee_params={"maker_bps": "10", "taker_bps": "20"},
        slippage_model="VolumeWeighted",
        slippage_params={"base_bps": "0", "volume_impact": "0"},
        settlement_days=0,
    )
    sim = Simulator(provider_config=provider_cfg, config=SimulatorConfig(min_order_delay_bars=1))

    t0 = datetime(2024, 1, 1, 9, 30, tzinfo=UTC)
    orders = [
        make_order(t0, side="buy", qty="1", limit="100"),
    ]
    bars = [
        make_bar(t0, "99", "101", "98", "100"),  # order not yet eligible
        make_bar(t0 + timedelta(minutes=1), "99", "101", "98", "100"),  # executes here
    ]

    result = sim.run(orders, bars)
    assert len(result.fills) == 1
    fill = result.fills[0]
    assert fill.price == Decimal("99")  # gap benefit
    assert fill.commission > Decimal("0")  # taker assumed since price crosses open
    assert len(result.portfolio_history) == 2


def test_simulator_honors_settlement_days() -> None:
    provider_cfg = ProviderConfig(
        name="robinhood",
        asset_classes=["equity"],
        fee_model="ZeroCommission",
        slippage_model="PFOF",
        slippage_params={"adverse_bps": "0"},
        settlement_days=1,
    )
    sim = Simulator(provider_config=provider_cfg, config=SimulatorConfig(min_order_delay_bars=0, initial_capital=Decimal("100")))

    t0 = datetime(2024, 1, 1, 9, 30, tzinfo=UTC)
    # seed a long position to sell
    from liq.sim.accounting import PositionLot, PositionRecord
    sim.account_state.positions["AAPL"] = PositionRecord(
        lots=[PositionLot(quantity=Decimal("1"), entry_price=Decimal("10"), entry_time=t0)]
    )
    orders = [make_order(t0, side="sell", qty="1")]
    bars = [
        make_bar(t0, "10", "11", "9", "10"),
        make_bar(t0 + timedelta(days=1), "10", "11", "9", "10"),
    ]

    result = sim.run(orders, bars)
    assert len(result.fills) == 1
    # unsettled proceeds reflected in equity immediately (cash + unsettled)
    assert result.portfolio_history[0] == Decimal("110")
    assert result.portfolio_history[1] == Decimal("110")


def test_simulator_outputs_equity_curve_with_timestamps() -> None:
    provider_cfg = ProviderConfig(
        name="coinbase",
        asset_classes=["crypto"],
        fee_model="ZeroCommission",
        slippage_model="VolumeWeighted",
        slippage_params={"base_bps": "0", "volume_impact": "0"},
        short_enabled=True,
    )
    sim = Simulator(provider_config=provider_cfg, config=SimulatorConfig(min_order_delay_bars=0))
    t0 = datetime(2024, 1, 1, 9, 30, tzinfo=UTC)
    orders = [make_order(t0, side="buy", qty="1", limit="100")]
    bars = [
        make_bar(t0, "100", "105", "99", "102"),
        make_bar(t0 + timedelta(minutes=1), "102", "106", "101", "103"),
    ]
    result = sim.run(orders, bars)
    assert len(result.equity_curve) == len(bars)
    assert result.equity_curve[0][0] == bars[0].timestamp
    assert result.portfolio_states[0].timestamp == bars[0].timestamp


def test_fills_include_realized_pnl_on_close() -> None:
    provider_cfg = ProviderConfig(
        name="coinbase",
        asset_classes=["crypto"],
        fee_model="ZeroCommission",
        slippage_model="VolumeWeighted",
        slippage_params={"base_bps": "0", "volume_impact": "0"},
        short_enabled=True,
    )
    sim = Simulator(provider_config=provider_cfg, config=SimulatorConfig(min_order_delay_bars=0))
    t0 = datetime(2024, 1, 1, 9, 30, tzinfo=UTC)
    buy = make_order(t0, side="buy", qty="1", limit="100")
    sell = make_order(t0 + timedelta(minutes=1), side="sell", qty="1", limit="110")
    bars = [
        make_bar(t0, "100", "100", "100", "100"),
        make_bar(t0 + timedelta(minutes=1), "110", "110", "110", "110"),
    ]
    result = sim.run([buy, sell], bars)
    assert len(result.fills) == 2
    assert result.fills[-1].realized_pnl == Decimal("10")


def test_final_equity_matches_pnl_long_and_short() -> None:
    """Ensure final equity reflects both long and short P&L with zero fees."""
    provider_cfg = ProviderConfig(
        name="coinbase",
        asset_classes=["crypto"],
        fee_model="ZeroCommission",
        slippage_model="VolumeWeighted",
        slippage_params={"base_bps": "0", "volume_impact": "0"},
        short_enabled=True,
    )
    sim = Simulator(
        provider_config=provider_cfg,
        config=SimulatorConfig(min_order_delay_bars=0, initial_capital=Decimal("1000")),
    )
    t0 = datetime(2024, 1, 1, 9, 30, tzinfo=UTC)
    bars = [
        make_bar(t0, "100", "101", "99", "100"),  # enter long at 100
        make_bar(t0 + timedelta(minutes=1), "110", "111", "109", "110"),  # exit long at 110 (+10)
        make_bar(t0 + timedelta(minutes=2), "110", "111", "109", "110"),  # enter short at 110
        make_bar(t0 + timedelta(minutes=3), "100", "101", "99", "100"),  # cover short at 100 (+10)
    ]
    orders = [
        make_order(bars[0].timestamp, side="buy", qty="1"),   # long entry
        make_order(bars[1].timestamp, side="sell", qty="1"),  # long exit
        make_order(bars[2].timestamp, side="sell", qty="1"),  # short entry
        make_order(bars[3].timestamp, side="buy", qty="1"),   # short cover
    ]

    result = sim.run(orders, bars)
    assert len(result.fills) == 4
    # Two trades each earn 10 with zero fees/slippage
    assert result.equity_curve[-1][1] == Decimal("1020")
    assert result.portfolio_history[-1] == Decimal("1020")
