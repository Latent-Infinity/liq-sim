from decimal import Decimal
from pathlib import Path

import pytest

from liq.sim.config import (
    CalibrationConfig,
    EVThresholdConfig,
    FundingConfig,
    ProviderConfig,
    RiskCapsConfig,
    SimulatorConfig,
    SlippageReportingConfig,
)


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

    def test_nested_configs_present(self) -> None:
        cfg = SimulatorConfig()
        assert isinstance(cfg.calibration, CalibrationConfig)
        assert isinstance(cfg.ev_thresholds, EVThresholdConfig)
        assert isinstance(cfg.funding, FundingConfig)
        assert isinstance(cfg.slippage_reporting, SlippageReportingConfig)
        assert isinstance(cfg.risk_caps, RiskCapsConfig)

    def test_slippage_percentiles_validation(self) -> None:
        with pytest.raises(ValueError):
            SlippageReportingConfig(percentiles=[0, 101])
        cfg = SlippageReportingConfig(percentiles=[95, 50, 95])
        assert cfg.percentiles == [50, 95]

    def test_ev_threshold_validation(self) -> None:
        with pytest.raises(ValueError):
            EVThresholdConfig(min_precision=1.5)
        with pytest.raises(ValueError):
            EVThresholdConfig(min_recall=-0.1)
        cfg = EVThresholdConfig(min_trades=0, target_ev=0.2)
        assert cfg.min_trades == 0
        assert cfg.target_ev == 0.2

    def test_risk_caps_validation(self) -> None:
        with pytest.raises(ValueError):
            RiskCapsConfig(net_position_cap_pct=1.1)
        with pytest.raises(ValueError):
            RiskCapsConfig(pyramiding_layers=0)


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
