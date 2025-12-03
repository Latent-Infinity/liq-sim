from decimal import Decimal
from pathlib import Path

import pytest

from liq.sim.config import ProviderConfig, SimulatorConfig


class TestSimulatorConfig:
    def test_defaults(self) -> None:
        cfg = SimulatorConfig()
        assert cfg.initial_capital == Decimal("10000")
        assert cfg.min_order_delay_bars == 1
        assert cfg.max_position_pct == 0.25
        assert cfg.checkpoint_dir == Path("./checkpoints")

    def test_invalid_max_position_pct(self) -> None:
        with pytest.raises(ValueError):
            SimulatorConfig(max_position_pct=1.5)

    def test_invalid_max_daily_loss_pct(self) -> None:
        with pytest.raises(ValueError):
            SimulatorConfig(max_daily_loss_pct=1.2)

    def test_valid_loss_pct_allows_value(self) -> None:
        cfg = SimulatorConfig(max_daily_loss_pct=0.05, max_drawdown_pct=0.2)
        assert cfg.max_daily_loss_pct == 0.05
        assert cfg.max_drawdown_pct == 0.2

    def test_log_file_required_when_enabled(self) -> None:
        with pytest.raises(ValueError):
            SimulatorConfig(log_to_file=True)

    def test_log_format_validation(self) -> None:
        with pytest.raises(ValueError):
            SimulatorConfig(log_format="xml")


class TestProviderConfig:
    def test_requires_asset_classes(self) -> None:
        with pytest.raises(ValueError):
            ProviderConfig(
                name="coinbase",
                asset_classes=[],
                fee_model="TieredMakerTaker",
                slippage_model="VolumeWeighted",
            )

    def test_negative_settlement_rejected(self) -> None:
        with pytest.raises(ValueError):
            ProviderConfig(
                name="coinbase",
                asset_classes=["crypto"],
                fee_model="TieredMakerTaker",
                slippage_model="VolumeWeighted",
                settlement_days=-1,
            )

    def test_margin_rates_positive(self) -> None:
        with pytest.raises(ValueError):
            ProviderConfig(
                name="coinbase",
                asset_classes=["crypto"],
                fee_model="TieredMakerTaker",
                slippage_model="VolumeWeighted",
                initial_margin_rate=Decimal("-1"),
            )
