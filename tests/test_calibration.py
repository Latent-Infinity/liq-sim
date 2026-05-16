from typing import cast

import polars as pl

from liq.sim.calibration import (
    CalibrationResult,
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
