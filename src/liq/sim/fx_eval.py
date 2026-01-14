"""FX evaluation helpers for standard reporting."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any


def summarize_fx_performance(
    equity_curve: Iterable[float],
    periods_per_year: int = 252,
) -> dict[str, float]:
    """Summarize equity curve performance metrics.

    Args:
        equity_curve: Iterable of equity values over time.
        periods_per_year: Periods per year for annualization (default 252).

    Returns:
        Dictionary with total return, sharpe, sortino, max_drawdown.
    """
    equity = list(equity_curve)
    if len(equity) < 2:
        return {
            "total_return": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "max_drawdown": 0.0,
        }

    returns = _pct_returns(equity)
    total_return = (equity[-1] / equity[0]) - 1 if equity[0] != 0 else 0.0
    sharpe = _annualized_sharpe(returns, periods_per_year)
    sortino = _annualized_sortino(returns, periods_per_year)
    max_dd = _max_drawdown(equity)

    return {
        "total_return": total_return,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_dd,
    }


def turnover_from_positions(
    positions: Iterable[float],
) -> float:
    """Compute turnover as average absolute change in position size.

    Args:
        positions: Iterable of position sizes (normalized).

    Returns:
        Average absolute delta per period.
    """
    pos = list(positions)
    if len(pos) < 2:
        return 0.0
    deltas = [abs(curr - prev) for prev, curr in zip(pos, pos[1:])]
    return sum(deltas) / len(deltas)


def _pct_returns(equity: list[float]) -> list[float]:
    returns = []
    for prev, curr in zip(equity, equity[1:]):
        if prev == 0:
            returns.append(0.0)
        else:
            returns.append((curr / prev) - 1)
    return returns


def _annualized_sharpe(returns: list[float], periods_per_year: int) -> float:
    if not returns:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    std = math.sqrt(variance)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(periods_per_year)


def _annualized_sortino(returns: list[float], periods_per_year: int) -> float:
    if not returns:
        return 0.0
    mean = sum(returns) / len(returns)
    downside = [min(0.0, r) for r in returns]
    downside_var = sum(r**2 for r in downside) / len(returns)
    downside_std = math.sqrt(downside_var)
    if downside_std == 0:
        return 0.0
    return (mean / downside_std) * math.sqrt(periods_per_year)


def _max_drawdown(equity: list[float]) -> float:
    peak = equity[0]
    max_dd = 0.0
    for value in equity:
        if value > peak:
            peak = value
        drawdown = (peak - value) / peak if peak != 0 else 0.0
        if drawdown > max_dd:
            max_dd = drawdown
    return max_dd
