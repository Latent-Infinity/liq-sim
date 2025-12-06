from datetime import datetime, timezone
from decimal import Decimal
import random
from pathlib import Path

import pytest

from liq.sim.checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    CheckpointFormatError,
    SimulationCheckpoint,
    create_checkpoint,
)
from liq.sim.config import ProviderConfig, SimulatorConfig
from liq.sim.simulator import Simulator
from liq.core import Bar, OrderRequest
from liq.core.enums import OrderSide, OrderType, TimeInForce


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


def test_checkpoint_corrupted_file(tmp_path: Path) -> None:
    """Corrupted/truncated msgpack files should raise CheckpointFormatError."""
    path = tmp_path / "corrupted.msgpack"
    path.write_bytes(b"\x82\xa3foo")  # Incomplete msgpack
    with pytest.raises(CheckpointFormatError, match="Failed to decode"):
        SimulationCheckpoint.load(path)


def test_checkpoint_wrong_format_pickle(tmp_path: Path) -> None:
    """Legacy pickle files should be rejected with clear error message."""
    path = tmp_path / "legacy.pkl"
    # Pickle magic bytes
    path.write_bytes(b"\x80\x04\x95\x00\x00\x00\x00")
    with pytest.raises(CheckpointFormatError, match="legacy pickle format"):
        SimulationCheckpoint.load(path)


def test_checkpoint_invalid_type(tmp_path: Path) -> None:
    """Non-dict msgpack content should raise CheckpointFormatError."""
    import msgspec

    path = tmp_path / "invalid.msgpack"
    path.write_bytes(msgspec.msgpack.encode([1, 2, 3]))  # List instead of dict
    with pytest.raises(CheckpointFormatError, match="expected dict"):
        SimulationCheckpoint.load(path)


def test_checkpoint_schema_version_present(tmp_path: Path) -> None:
    """Checkpoint should include schema version field."""
    cfg = ProviderConfig(
        name="coinbase",
        asset_classes=["crypto"],
        fee_model="ZeroCommission",
        slippage_model="VolumeWeighted",
    )
    sim_cfg = SimulatorConfig(min_order_delay_bars=0, initial_capital=Decimal("1000"))
    sim = Simulator(provider_config=cfg, config=sim_cfg)
    chk = sim.to_checkpoint(backtest_id="bt-1", config_hash="hash123")

    assert chk.schema_version == CHECKPOINT_SCHEMA_VERSION

    path = tmp_path / "chk.msgpack"
    chk.save(path)
    loaded = SimulationCheckpoint.load(path)
    assert loaded.schema_version == CHECKPOINT_SCHEMA_VERSION


def test_checkpoint_decimal_precision(tmp_path: Path) -> None:
    """Decimal values should maintain precision through serialization."""
    cfg = ProviderConfig(
        name="coinbase",
        asset_classes=["crypto"],
        fee_model="ZeroCommission",
        slippage_model="VolumeWeighted",
    )
    # Use a high-precision decimal
    precise_capital = Decimal("123456.78901234567890")
    sim_cfg = SimulatorConfig(min_order_delay_bars=0, initial_capital=precise_capital)
    sim = Simulator(provider_config=cfg, config=sim_cfg)

    chk = sim.to_checkpoint(backtest_id="bt-1", config_hash="hash123")
    path = tmp_path / "chk.msgpack"
    chk.save(path)

    loaded = SimulationCheckpoint.load(path)
    resumed = Simulator.from_checkpoint(loaded)
    # Check cash matches (initial capital flows to cash)
    assert resumed.account_state.cash == precise_capital


def test_checkpoint_rng_state_preserved(tmp_path: Path) -> None:
    """RNG state should survive serialization round-trip."""
    cfg = ProviderConfig(
        name="coinbase",
        asset_classes=["crypto"],
        fee_model="ZeroCommission",
        slippage_model="VolumeWeighted",
    )
    sim_cfg = SimulatorConfig(min_order_delay_bars=0, initial_capital=Decimal("1000"), random_seed=42)
    sim = Simulator(provider_config=cfg, config=sim_cfg)

    # Generate some random values to advance RNG state
    _ = [random.random() for _ in range(10)]
    expected_next = random.random()

    # Reset and re-advance to same state
    random.seed(42)
    _ = [random.random() for _ in range(10)]

    # Save checkpoint (captures current RNG state)
    chk = sim.to_checkpoint(backtest_id="bt-1", config_hash="hash123")
    path = tmp_path / "chk.msgpack"
    chk.save(path)

    # Mess up RNG state
    random.seed(999)

    # Load and restore
    loaded = SimulationCheckpoint.load(path)
    loaded.restore_random_state()

    # Should get same next value
    actual_next = random.random()
    assert actual_next == expected_next
