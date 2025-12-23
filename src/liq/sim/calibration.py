"""Score calibration and EV-based threshold selection utilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import polars as pl


@dataclass
class CalibrationResult:
    """Holds calibrated scores and parameters."""

    scores: pl.Series
    params: dict[str, float]


def temperature_scale(scores: pl.Series, labels: pl.Series) -> CalibrationResult:
    """Apply simple temperature scaling to scores (binary labels).

    This is a placeholder implementation that rescales scores to [0,1]
    using a fitted temperature parameter on mean calibration error.
    """
    if scores.is_empty() or labels.is_empty():
        return CalibrationResult(scores=scores, params={"temperature": 1.0})
    # naive temperature: inverse of std to shrink extremes
    temp = float(max(scores.std() or 1.0, 1e-6))
    calibrated = (scores / temp).clip(0.0, 1.0)
    return CalibrationResult(scores=calibrated, params={"temperature": temp})


@dataclass
class ThresholdDiagnostics:
    """Threshold search result with constraints and EV."""

    threshold: float
    expected_value: float
    precision: float
    recall: float
    trades: int
    constraints_satisfied: bool


def ev_threshold_search(
    scores: pl.Series,
    labels: pl.Series,
    *,
    min_precision: float | None = None,
    min_recall: float | None = None,
    min_trades: int | None = None,
    target_ev: float | None = None,
    grid: Iterable[float] | None = None,
) -> ThresholdDiagnostics:
    """Find threshold maximizing EV under optional constraints."""
    if scores.is_empty() or labels.is_empty():
        return ThresholdDiagnostics(
            threshold=0.5,
            expected_value=0.0,
            precision=0.0,
            recall=0.0,
            trades=0,
            constraints_satisfied=False,
        )
    thresholds = list(grid) if grid is not None else [x / 100 for x in range(5, 100, 5)]
    best = None
    best_ev = float("-inf")

    for th in thresholds:
        preds = scores >= th
        tp = int(((preds) & (labels == 1)).sum())
        fp = int(((preds) & (labels == 0)).sum())
        fn = int(((~preds) & (labels == 1)).sum())
        trades = tp + fp
        precision = tp / trades if trades else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        ev = precision  # placeholder: using precision as proxy for EV

        constraints = True
        if min_precision is not None and precision < min_precision:
            constraints = False
        if min_recall is not None and recall < min_recall:
            constraints = False
        if min_trades is not None and trades < min_trades:
            constraints = False
        if target_ev is not None and ev < target_ev:
            constraints = False

        if constraints and ev > best_ev:
            best_ev = ev
            best = ThresholdDiagnostics(
                threshold=th,
                expected_value=ev,
                precision=precision,
                recall=recall,
                trades=trades,
                constraints_satisfied=True,
            )

    if best is None:
        # fallback to default threshold
        return ThresholdDiagnostics(
            threshold=0.5,
            expected_value=0.0,
            precision=0.0,
            recall=0.0,
            trades=0,
            constraints_satisfied=False,
        )
    return best
