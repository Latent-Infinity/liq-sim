from datetime import datetime, timezone
from decimal import Decimal
import random
from pathlib import Path

from liq.sim.checkpoint import SimulationCheckpoint, create_checkpoint
from liq.sim.config import ProviderConfig, SimulatorConfig
from liq.sim.simulator import Simulator
from liq.types import Bar, OrderRequest
from liq.types.enums import OrderSide, OrderType, TimeInForce


class RandomSlippage:
    def calculate(self, order, bar):
        return Decimal(str(random.random()))


def make_order(ts: datetime) -> OrderRequest:
    return OrderRequest(
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        time_in_force=TimeInForce.DAY,
        timestamp=ts,
    )


def make_bar(ts: datetime, price: str) -> Bar:
    return Bar(
        symbol="AAPL",
        timestamp=ts,
        open=Decimal(price),
        high=Decimal(price),
        low=Decimal(price),
        close=Decimal(price),
        volume=Decimal("100"),
    )


def test_checkpoint_round_trip(tmp_path: Path) -> None:
    cfg = ProviderConfig(
        name="coinbase",
        asset_classes=["crypto"],
        fee_model="ZeroCommission",
        slippage_model="VolumeWeighted",
    )
    sim_cfg = SimulatorConfig(min_order_delay_bars=0, initial_capital=Decimal("1000"), random_seed=123)
    sim = Simulator(provider_config=cfg, config=sim_cfg)
    sim.slippage_model = RandomSlippage()
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    orders = [make_order(ts)]
    bars = [make_bar(ts, "10")]
    result = sim.run(orders, bars)
    assert len(result.fills) == 1

    chk = sim.to_checkpoint(backtest_id="bt-1", config_hash="hash123")
    path = tmp_path / "chk.pkl"
    chk.save(path)

    loaded = SimulationCheckpoint.load(path, expected_config_hash="hash123")
    resumed = Simulator.from_checkpoint(loaded)
    assert resumed.account_state.cash == sim.account_state.cash
    assert resumed.peak_equity == sim.peak_equity


def test_checkpoint_hash_validation(tmp_path: Path) -> None:
    cfg = ProviderConfig(
        name="coinbase",
        asset_classes=["crypto"],
        fee_model="ZeroCommission",
        slippage_model="VolumeWeighted",
    )
    sim_cfg = SimulatorConfig(min_order_delay_bars=0, initial_capital=Decimal("1000"))
    sim = Simulator(provider_config=cfg, config=sim_cfg)
    chk = create_checkpoint(
        backtest_id="bt-1",
        config_hash="hash123",
        provider_config=cfg,
        simulator_config=sim_cfg,
        account_state=sim.account_state,
        current_day=None,
        peak_equity=sim.peak_equity,
        daily_start_equity=sim.daily_start_equity,
        kill_switch_engaged=False,
        active_brackets=[],
    )
    path = tmp_path / "chk.pkl"
    chk.save(path)
    try:
        SimulationCheckpoint.load(path, expected_config_hash="other")
    except ValueError:
        pass
    else:
        raise AssertionError("Expected config hash mismatch to raise")


def test_deterministic_seed_replay() -> None:
    cfg = ProviderConfig(
        name="coinbase",
        asset_classes=["crypto"],
        fee_model="ZeroCommission",
        slippage_model="VolumeWeighted",
    )
    sim_cfg = SimulatorConfig(min_order_delay_bars=0, initial_capital=Decimal("1000"), random_seed=999)
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    orders = [make_order(ts)]
    bars = [make_bar(ts, "10")]

    sim1 = Simulator(provider_config=cfg, config=sim_cfg)
    sim1.slippage_model = RandomSlippage()
    res1 = sim1.run(orders, bars)

    sim2 = Simulator(provider_config=cfg, config=sim_cfg)
    sim2.slippage_model = RandomSlippage()
    res2 = sim2.run(orders, bars)

    assert res1.fills[0].slippage == res2.fills[0].slippage
