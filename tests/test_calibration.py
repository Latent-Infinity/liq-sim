from typing import cast

import polars as pl
import pytest

from liq.sim.calibration import (
    CalibrationResult,
    apply_temperature_scale,
    build_threshold_grid_from_scores,
    ev_threshold_search,
    temperature_scale,
)


def test_temperature_scale_returns_params() -> None:
    scores = pl.Series([0.1, 0.5, 0.9])
    labels = pl.Series([0, 1, 1])
    res = temperature_scale(scores, labels)
    assert isinstance(res, CalibrationResult)
    assert "temperature" in res.params
    assert res.scores.len() == scores.len()


def test_temperature_scale_preserves_probability_order_without_saturation() -> None:
    scores = pl.Series([0.2, 0.5, 0.8])
    labels = pl.Series([0, 1, 1])

    res = temperature_scale(scores, labels)
    values = res.scores.to_list()

    assert all(0.0 <= score <= 1.0 for score in values)
    assert values == sorted(values)
    assert len(set(values)) == len(values)
    assert values != [1.0, 1.0, 1.0]


def test_temperature_scale_does_not_clip_varied_probability_scores_to_one() -> None:
    scores = pl.Series([0.42, 0.51, 0.63, 0.74])
    labels = pl.Series([0, 0, 1, 1])

    res = temperature_scale(scores, labels)

    assert cast(float, res.scores.min()) < 1.0
    assert cast(float, res.scores.std()) > 0.0


def test_apply_temperature_scale_handles_extreme_logits_without_overflow() -> None:
    scores = pl.Series([1e-300, 1e-12, 0.5, 1.0 - 1e-12, 1.0 - 1e-300])

    calibrated = apply_temperature_scale(scores, temperature=1e-6)
    values = calibrated.to_list()

    assert all(0.0 <= value <= 1.0 for value in values)
    assert values == sorted(values)


def _nll(scores: pl.Series, labels: pl.Series, temp: float) -> float:
    import math

    cal = apply_temperature_scale(scores, temp).to_list()
    ys = labels.to_list()
    eps = 1e-12
    total = 0.0
    for c, y in zip(cal, ys, strict=True):
        c = min(max(c, eps), 1.0 - eps)
        total += -(y * math.log(c) + (1 - y) * math.log(1.0 - c))
    return total / len(ys)


def _clustered_calibrated_dataset() -> tuple[pl.Series, pl.Series]:
    """Production-like: ~250 tightly-clustered, roughly-calibrated probs.

    Raw std ~0.058 — the regime where the old ``temp = std(scores)``
    heuristic collapses to a near-step function (T ~ 0.06).
    """
    import random

    rng = random.Random(0)
    n = 250
    probs = [0.40 + 0.20 * (i / (n - 1)) for i in range(n)]  # 0.40..0.60
    labels = [1 if rng.random() < p else 0 for p in probs]
    return pl.Series("score", probs), pl.Series(labels)


def test_temperature_scale_fits_by_nll_not_std_heuristic() -> None:
    scores, labels = _clustered_calibrated_dataset()
    std_temp = float(cast(float, scores.std()))

    res = temperature_scale(scores, labels)
    fitted_temp = res.params["temperature"]

    # The fit must not be the std heuristic, and must not be lower NLL than it.
    assert fitted_temp != pytest.approx(std_temp, abs=1e-3)
    assert _nll(scores, labels, fitted_temp) <= _nll(scores, labels, std_temp) + 1e-9
    # Fit beats the degenerate saturating temperature too.
    assert _nll(scores, labels, fitted_temp) <= _nll(scores, labels, 0.05) + 1e-9


def test_temperature_scale_does_not_saturate_tightly_clustered_scores() -> None:
    scores, labels = _clustered_calibrated_dataset()
    raw_std = float(cast(float, scores.std()))

    res = temperature_scale(scores, labels)
    cal = res.scores.to_list()
    cal_std = float(cast(float, res.scores.std()))

    # Temperature floored to a sane value (the old heuristic gave ~0.058).
    assert res.params["temperature"] >= 0.5
    # Roughly-calibrated probs => fitted T near 1 => calibrated ~ raw, NOT a
    # 0/1 step function (saturation would blow std toward ~0.45).
    assert cal_std < 0.25
    assert cal_std == pytest.approx(raw_std, abs=0.10)
    # Ranking is preserved (monotone in raw score).
    paired = sorted(zip(scores.to_list(), cal, strict=True))
    assert [c for _, c in paired] == sorted(c for _, c in paired)
    # Not collapsed to the {~0, ~1} extremes.
    assert sum(1 for c in cal if 0.05 < c < 0.95) > len(cal) // 2


def test_temperature_scale_single_class_labels_falls_back_to_identity() -> None:
    scores = pl.Series([0.42, 0.51, 0.63, 0.74])
    labels = pl.Series([1, 1, 1, 1])

    res = temperature_scale(scores, labels)

    # No class contrast => calibration is unidentifiable; identity (T=1) is the
    # safe, information-preserving fallback (must NOT push T->0).
    assert res.params["temperature"] == 1.0
    assert res.scores.to_list() == pytest.approx(scores.to_list(), abs=1e-9)


def test_temperature_scale_empty_inputs_return_identity() -> None:
    res = temperature_scale(pl.Series([], dtype=pl.Float64), pl.Series([], dtype=pl.Int64))
    assert res.params["temperature"] == 1.0
    assert res.scores.is_empty()


def test_build_threshold_grid_from_scores_uses_quantiles() -> None:
    scores = pl.Series([0.1, 0.2, 0.4, 0.8])

    grid = build_threshold_grid_from_scores(
        scores,
        quantiles=[0.0, 0.5, 1.0],
        minimum=0.05,
        maximum=0.95,
        round_decimals=3,
    )

    assert grid == [0.1, 0.3, 0.8]


def test_build_threshold_grid_from_scores_clamps_and_deduplicates() -> None:
    scores = pl.Series([0.01, 0.01, 0.5, 1.2])

    grid = build_threshold_grid_from_scores(
        scores,
        quantiles=[0.0, 0.5, 1.0],
        minimum=0.05,
        maximum=0.95,
        round_decimals=2,
    )

    assert grid == [0.05, 0.26, 0.95]


def test_build_threshold_grid_from_scores_handles_empty() -> None:
    grid = build_threshold_grid_from_scores(pl.Series([], dtype=pl.Float64))

    assert grid == []


def test_ev_threshold_search_respects_constraints() -> None:
    scores = pl.Series([0.9, 0.8, 0.2, 0.1])
    labels = pl.Series([1, 1, 0, 0])
    diag = ev_threshold_search(scores, labels, min_precision=0.5, min_recall=0.5, min_trades=1)
    assert diag.constraints_satisfied is True
    assert 0 < diag.threshold < 1


def test_ev_threshold_search_prefers_higher_threshold_when_ev_ties() -> None:
    scores = pl.Series([0.9, 0.8])
    labels = pl.Series([1, 1])

    diag = ev_threshold_search(scores, labels, grid=[0.5, 0.85], min_trades=1)

    assert diag.threshold == 0.85
    assert diag.precision == 1.0
    assert diag.trades == 1


def test_ev_threshold_search_handles_empty() -> None:
    diag = ev_threshold_search(pl.Series([], dtype=pl.Float64), pl.Series([], dtype=pl.Int64))
    assert diag.constraints_satisfied is False
