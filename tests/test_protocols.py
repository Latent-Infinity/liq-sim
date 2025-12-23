"""Contract checks for simulation protocols (Phase 0 interfaces)."""

import polars as pl
import pytest

from liq.sim import protocols


def test_calibration_strategy_placeholder() -> None:
    class Dummy(protocols.CalibrationStrategy):
        def calibrate(self, scores: pl.Series, labels: pl.Series) -> dict:  # type: ignore[override]
            return {"scores": scores, "labels": labels}

    strat = Dummy()
    out = strat.calibrate(pl.Series([0.1]), pl.Series([1]))
    assert "scores" in out


def test_ev_threshold_selector_placeholder() -> None:
    class Dummy(protocols.EVThresholdSelector):
        def select(self, scores: pl.Series, labels: pl.Series) -> dict:  # type: ignore[override]
            return {"threshold": 0.5, "scores": scores, "labels": labels}

    selector = Dummy()
    out = selector.select(pl.Series([0.2]), pl.Series([0]))
    assert out["threshold"] == 0.5


def test_protocols_exist_for_funding_and_risk_caps() -> None:
    assert hasattr(protocols, "FundingModel")
    assert hasattr(protocols, "SlippageReporter")
    assert hasattr(protocols, "RiskCapPolicy")
