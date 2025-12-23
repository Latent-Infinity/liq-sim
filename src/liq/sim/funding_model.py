"""Funding model scenarios and slippage reporting utilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class FundingScenario:
    """Represents a funding rate scenario."""

    name: str
    annual_rate: float  # expressed as decimal (e.g., 0.05 = 5% annual)


SCENARIOS: dict[str, FundingScenario] = {
    "base": FundingScenario(name="base", annual_rate=0.03),
    "elevated": FundingScenario(name="elevated", annual_rate=0.08),
    "spike": FundingScenario(name="spike", annual_rate=0.15),
}


def funding_charge(notional: float, days: float, scenario: str) -> float:
    """Compute funding charge for a notional over days under a named scenario."""
    scen = SCENARIOS.get(scenario, SCENARIOS["base"])
    daily_rate = scen.annual_rate / 365.0
    return notional * daily_rate * days


def slippage_percentiles(samples: Sequence[float], percentiles: Sequence[int]) -> dict[str, float]:
    """Return percentile stats for slippage samples."""
    if not samples:
        return {f"p{p}": 0.0 for p in percentiles}
    arr = np.array(samples, dtype=float)
    result = {}
    for p in percentiles:
        result[f"p{p}"] = float(np.percentile(arr, p))
    return result
