"""Score calibration and EV-based threshold selection utilities."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from math import exp, isfinite, log

import polars as pl


@dataclass
class CalibrationResult:
    """Holds calibrated scores and parameters."""

    scores: pl.Series
    params: dict[str, float]


def _stable_sigmoid(value: float) -> float:
    if value >= 0.0:
        denominator = 1.0 + exp(-value)
        return 1.0 / denominator
    numerator = exp(value)
    return numerator / (1.0 + numerator)


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
        calibrated.append(_stable_sigmoid(logit / temp))
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


_TEMP_MIN = 0.5
_TEMP_MAX = 10.0


def _to_logit(probability: float) -> float:
    epsilon = 1e-6
    p = min(max(probability, epsilon), 1.0 - epsilon)
    return log(p / (1.0 - p))


def _mean_nll(logits: list[float], targets: list[int], temperature: float) -> float:
    temp = max(abs(temperature), 1e-6)
    eps = 1e-12
    total = 0.0
    for logit, y in zip(logits, targets, strict=True):
        p = min(max(_stable_sigmoid(logit / temp), eps), 1.0 - eps)
        total += -(y * log(p) + (1 - y) * log(1.0 - p))
    return total / len(targets)


def _fit_temperature(logits: list[float], targets: list[int]) -> float:
    """Temperature minimizing mean NLL, bounded to a sane range.

    Coarse log-spaced scan to bracket the minimum, then golden-section
    refinement. Bounding prevents a degenerate optimum from collapsing the
    sigmoid to a step function (T -> 0) or flattening it to 0.5 (T -> inf) —
    the failure mode of the previous ``temp = std(scores)`` heuristic.
    """
    lo, hi = _TEMP_MIN, _TEMP_MAX
    log_lo, log_hi = log(lo), log(hi)
    n_scan = 49
    best_t = 1.0
    best_nll = _mean_nll(logits, targets, 1.0)
    for i in range(n_scan):
        t = exp(log_lo + (log_hi - log_lo) * i / (n_scan - 1))
        nll = _mean_nll(logits, targets, t)
        if nll < best_nll:
            best_nll, best_t = nll, t

    step = (log_hi - log_lo) / (n_scan - 1)
    a = max(log_lo, log(best_t) - step)
    b = min(log_hi, log(best_t) + step)
    inv_phi = (5.0**0.5 - 1.0) / 2.0
    c = b - (b - a) * inv_phi
    d = a + (b - a) * inv_phi
    fc = _mean_nll(logits, targets, exp(c))
    fd = _mean_nll(logits, targets, exp(d))
    for _ in range(40):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - (b - a) * inv_phi
            fc = _mean_nll(logits, targets, exp(c))
        else:
            a, c, fc = c, d, fd
            d = a + (b - a) * inv_phi
            fd = _mean_nll(logits, targets, exp(d))
    refined = exp((a + b) / 2.0)
    if _mean_nll(logits, targets, refined) < best_nll:
        best_t = refined
    return float(min(max(best_t, lo), hi))


def temperature_scale(scores: pl.Series, labels: pl.Series) -> CalibrationResult:
    """Temperature-scale probability scores by fitting T to minimize NLL.

    Scores are treated as probabilities and scaled in logit space so calibration
    preserves ordering. The temperature is fit against the binary labels by
    minimizing mean negative log-likelihood over a bounded range (proper
    calibration objective), not derived from score dispersion. Inputs without
    two label classes are unidentifiable, so identity (T=1.0) is returned.
    """
    if scores.is_empty() or labels.is_empty():
        return CalibrationResult(scores=scores, params={"temperature": 1.0})
    targets = [int(round(float(v))) for v in labels.cast(pl.Float64)]
    logits = [_to_logit(float(v)) for v in scores.cast(pl.Float64)]
    m = min(len(targets), len(logits))
    targets, logits = targets[:m], logits[:m]
    if m == 0 or len(set(targets)) < 2:
        return CalibrationResult(scores=scores, params={"temperature": 1.0})
    temp = _fit_temperature(logits, targets)
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
