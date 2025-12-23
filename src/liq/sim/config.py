"""Configuration models for liq-sim."""

from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class CalibrationConfig(BaseModel):
    """Per-fold score calibration and EV thresholding configuration."""

    enabled: bool = False
    method: Literal["temperature", "platt"] = "temperature"


class EVThresholdConfig(BaseModel):
    """Expected-value-based threshold selection constraints."""

    enabled: bool = False
    min_precision: float | None = None
    min_recall: float | None = None
    min_trades: int | None = None
    target_ev: float | None = None

    @field_validator("min_precision", "min_recall", "target_ev")
    @classmethod
    def validate_fraction(cls, v: float | None) -> float | None:
        if v is None:
            return v
        if v <= 0 or v >= 1:
            raise ValueError("fractions must be in (0, 1)")
        return v

    @field_validator("min_trades")
    @classmethod
    def validate_min_trades(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if v < 0:
            raise ValueError("min_trades must be >= 0")
        return v


class FundingConfig(BaseModel):
    """Scenario-based funding configuration."""

    scenario: Literal["base", "elevated", "spike"] = "base"
    enabled: bool = False


class SlippageReportingConfig(BaseModel):
    """Slippage percentile reporting configuration."""

    percentiles: list[int] = Field(default_factory=lambda: [50, 75, 90, 95, 99])

    @field_validator("percentiles")
    @classmethod
    def validate_percentiles(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("percentiles must not be empty")
        if any(p <= 0 or p >= 100 for p in v):
            raise ValueError("percentiles must be between 1 and 99")
        return sorted(set(v))


class RiskCapsConfig(BaseModel):
    """Risk-cap configuration placeholders (net, pyramiding, equity floor, frequency)."""

    net_position_cap_pct: float | None = None
    pyramiding_layers: int | None = None
    equity_floor_pct: float | None = None
    frequency_cap_per_day: int | None = None

    @field_validator("net_position_cap_pct", "equity_floor_pct")
    @classmethod
    def validate_pct(cls, v: float | None) -> float | None:
        if v is None:
            return v
        if v <= 0 or v >= 1:
            raise ValueError("percentages must be in (0, 1)")
        return v

    @field_validator("pyramiding_layers", "frequency_cap_per_day")
    @classmethod
    def validate_positive_int(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if v <= 0:
            raise ValueError("integer limits must be > 0")
        return v


class SimulatorConfig(BaseModel):
    """Simulation configuration with PRD defaults."""

    initial_capital: Decimal = Decimal("10000")
    min_order_delay_bars: int = 1
    max_daily_loss_pct: float | None = None
    max_drawdown_pct: float | None = None
    max_position_pct: float = 0.25
    max_gross_leverage: float = 2.0
    benchmark_symbol: str | None = None
    checkpoint_interval: int = 0
    checkpoint_dir: Path = Path("./checkpoints")
    random_seed: int = 42
    log_level: str = "INFO"
    log_to_file: bool = False
    log_file_path: Path | None = None
    log_format: str = "text"  # "text" or "json"
    enable_survivorship_warning: bool = True
    survivorship_min_duration_days: int = 365
    enable_overfitting_warning: bool = True
    overfitting_param_trade_ratio: float = 0.1
    calibration: CalibrationConfig = Field(default_factory=CalibrationConfig)
    ev_thresholds: EVThresholdConfig = Field(default_factory=EVThresholdConfig)
    funding: FundingConfig = Field(default_factory=FundingConfig)
    slippage_reporting: SlippageReportingConfig = Field(default_factory=SlippageReportingConfig)
    risk_caps: RiskCapsConfig = Field(default_factory=RiskCapsConfig)

    @field_validator("min_order_delay_bars")
    @classmethod
    def validate_min_order_delay(cls, v: int) -> int:
        if v < 0:
            raise ValueError("min_order_delay_bars must be >= 0")
        return v

    @field_validator("max_position_pct")
    @classmethod
    def validate_max_position_pct(cls, v: float) -> float:
        if not 0 < v <= 1:
            raise ValueError("max_position_pct must be in (0, 1]")
        return v

    @field_validator("max_daily_loss_pct", "max_drawdown_pct")
    @classmethod
    def validate_pct_bounds(cls, v: float | None) -> float | None:
        if v is None:
            return v
        if v <= 0 or v >= 1:
            raise ValueError("percentage thresholds must be in (0, 1)")
        return v

    @field_validator("log_format")
    @classmethod
    def validate_log_format(cls, v: str) -> str:
        fmt = v.lower()
        if fmt not in {"text", "json"}:
            raise ValueError("log_format must be 'text' or 'json'")
        return fmt

    @model_validator(mode="after")
    def validate_checkpointing(self) -> "SimulatorConfig":
        if self.checkpoint_interval < 0:
            raise ValueError("checkpoint_interval must be >= 0")
        if self.log_to_file and self.log_file_path is None:
            raise ValueError("log_file_path is required when log_to_file is True")
        return self


class ProviderConfig(BaseModel):
    """Provider configuration as consumed by liq-sim."""

    name: str
    asset_classes: list[str]
    fee_model: str
    fee_params: dict[str, Any] = Field(default_factory=dict)
    slippage_model: str
    slippage_params: dict[str, Any] = Field(default_factory=dict)
    margin_type: str | None = None  # None, RegT, Portfolio, Leveraged
    initial_margin_rate: Decimal = Decimal("1.0")
    maintenance_margin_rate: Decimal = Decimal("1.0")
    short_enabled: bool = False
    borrow_rate_annual: Decimal | None = None
    locate_required: bool = False
    settlement_days: int = 0
    pdt_enabled: bool = False
    pdt_min_equity: Decimal = Decimal("25000")
    account_currency: str = "USD"

    @field_validator("initial_margin_rate", "maintenance_margin_rate")
    @classmethod
    def validate_margin_rate(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("margin rates must be > 0")
        return v

    @field_validator("settlement_days")
    @classmethod
    def validate_settlement_days(cls, v: int) -> int:
        if v < 0:
            raise ValueError("settlement_days must be >= 0")
        return v

    @field_validator("asset_classes")
    @classmethod
    def validate_asset_classes(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("asset_classes must not be empty")
        return v
