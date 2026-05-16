"""Score calibration and EV-based threshold selection utilities."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from math import exp, isfinite, log
from typing import Any, cast

import polars as pl


@dataclass
class CalibrationResult:
    """Holds calibrated scores and parameters."""

    scores: pl.Series
    params: dict[str, float]


def apply_temperature_scale(scores: pl.Series, temperature: float) -> pl.Series:
    """Apply temperature scaling to probability-like scores in logit space."""
    if scores.is_empty():
        return scores

    temp = max(abs(float(temperature)), 1e-6)
    epsilon = 1e-6
    calibrated = []
    for raw_score in scores.cast(pl.Float64):
        probability = min(max(float(raw_score), epsilon), 1.0 - epsilon)
        logit = log(probability / (1.0 - probability))
        calibrated.append(1.0 / (1.0 + exp(-(logit / temp))))
    return pl.Series(scores.name, calibrated)


def build_threshold_grid_from_scores(
    scores: pl.Series,
    *,
    quantiles: Iterable[float] | None = None,
    minimum: float = 0.05,
    maximum: float = 0.95,
    round_decimals: int = 4,
) -> list[float]:
    """Build sorted threshold candidates from score quantiles.

    Empty or non-finite score inputs return an empty grid so callers can fall
    back to the static default grid used by ``ev_threshold_search``.
    """
    if scores.is_empty():
        return []

    q_values = list(quantiles) if quantiles is not None else [0.5, 0.6, 0.7, 0.8, 0.9, 0.95]
    if not q_values:
        return []

    values = sorted(
        float(value)
        for value in scores.cast(pl.Float64).drop_nulls().to_list()
        if isfinite(float(value))
    )
    if not values:
        return []

    lower = float(min(minimum, maximum))
    upper = float(max(minimum, maximum))
    decimals = max(0, int(round_decimals))
    grid: set[float] = set()
    last_idx = len(values) - 1
    for raw_quantile in q_values:
        quantile = min(max(float(raw_quantile), 0.0), 1.0)
        position = quantile * last_idx
        left_idx = int(position)
        right_idx = min(left_idx + 1, last_idx)
        weight = position - left_idx
        candidate = values[left_idx] * (1.0 - weight) + values[right_idx] * weight
        candidate = min(max(candidate, lower), upper)
        grid.add(round(candidate, decimals))

    return sorted(grid)


def temperature_scale(scores: pl.Series, labels: pl.Series) -> CalibrationResult:
    """Apply simple temperature scaling to probability scores (binary labels).

    Scores are treated as probabilities and scaled in logit space so calibration
    preserves ordering without collapsing varied probabilities through clipping.
    """
    if scores.is_empty() or labels.is_empty():
        return CalibrationResult(scores=scores, params={"temperature": 1.0})
    score_std = cast(Any, scores.std())
    temp = float(max(score_std or 1.0, 1e-6))
    calibrated = apply_temperature_scale(scores, temp)
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

        if constraints and (
            ev > best_ev
            or (ev == best_ev and ev > 0.0 and best is not None and th > best.threshold)
        ):
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
