"""Generic spot-futures basis-carry P&L accounting.

A dollar-neutral cash-and-carry book against the front-month **dated** futures
contract, rolled on a calendar schedule. Direction is per-day (``position_sign``):
long-basis in contango, short-basis in backwardation, flat otherwise. The P&L is
the basis converging toward zero at settlement, net of financing and trade/roll
costs.

Prices MUST be the unadjusted per-contract closes. A back-adjusted continuous
series (e.g. TradeStation ``@MBT``) folds roll gaps into the price and corrupts
the basis. The engine enforces this structurally: it never differences the futures
leg across a contract change, so a roll gap can never enter P&L.

Look-ahead safe: each day's P&L depends only on that day's and the prior day's
inputs. Terminal close-out cost is the caller's concern and is not baked in, so
truncating the series leaves earlier days' P&L unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from math import isfinite


@dataclass(frozen=True)
class BasisCarryConfig:
    """Fixed book and cost parameters for one basis-carry cell."""

    contract_multiplier: float  # underlying units per futures contract (e.g. 0.1)
    contracts: int  # number of futures contracts held (hedge size)
    long_spot_financing_annual_rate: float
    short_spot_borrow_annual_rate: float
    futures_margin_fraction: float
    futures_margin_financing_annual_rate: float
    futures_fee_per_contract: float  # $ per contract per side (commission + exchange)
    futures_overnight_fee_per_contract: float  # $ per open contract per settlement
    futures_slippage_bps: float  # bps on futures notional per side
    spot_fee_bps: float  # bps on spot notional per side

    def __post_init__(self) -> None:
        if not isfinite(self.contract_multiplier) or self.contract_multiplier <= 0:
            raise ValueError("contract_multiplier must be positive and finite")
        if (
            isinstance(self.contracts, bool)
            or not isinstance(self.contracts, int)
            or self.contracts <= 0
        ):
            raise ValueError("contracts must be positive")
        if not isfinite(self.futures_margin_fraction) or not 0 <= self.futures_margin_fraction <= 1:
            raise ValueError("futures_margin_fraction must be finite and between 0 and 1")
        nonnegative = (
            "long_spot_financing_annual_rate",
            "short_spot_borrow_annual_rate",
            "futures_margin_financing_annual_rate",
            "futures_fee_per_contract",
            "futures_overnight_fee_per_contract",
            "futures_slippage_bps",
            "spot_fee_bps",
        )
        for field_name in nonnegative:
            value = getattr(self, field_name)
            if not isfinite(value) or value < 0:
                raise ValueError(f"{field_name} must be non-negative and finite")


@dataclass(frozen=True)
class BasisCarryResult:
    """Per-day P&L decomposition (aligned to the input rows) plus totals."""

    gross_pnl: tuple[float, ...]
    long_spot_financing_cost: tuple[float, ...]
    short_spot_borrow_cost: tuple[float, ...]
    futures_margin_financing_cost: tuple[float, ...]
    overnight_fee_cost: tuple[float, ...]
    trade_cost: tuple[float, ...]
    net_pnl: tuple[float, ...]
    total_net: float
    n_rolls: int


def _futures_cost_per_side(price: float, config: BasisCarryConfig) -> float:
    notional = config.contracts * config.contract_multiplier * price
    return (
        config.futures_fee_per_contract * config.contracts
        + config.futures_slippage_bps / 1e4 * notional
    )


def _spot_cost_per_side(price: float, qty: float, config: BasisCarryConfig) -> float:
    return config.spot_fee_bps / 1e4 * (qty * price)


def simulate_basis_carry(
    observation_dates: Sequence[date],
    spot_close: Sequence[float],
    future_close: Sequence[float],
    contract_id: Sequence[str],
    config: BasisCarryConfig,
    *,
    position_sign: Sequence[int] | None = None,
    rebalance: Sequence[bool] | None = None,
    settlement_fee: Sequence[bool] | None = None,
) -> BasisCarryResult:
    """Daily net P&L of a spot/front-future basis-carry book.

    The book is dollar-neutral in the underlying: ``+1`` = long spot / short future
    (cash-and-carry, for contango), ``-1`` = the reverse (for backwardation), ``0``
    = flat. Trade cost scales with the change in direction (``|Δsign|`` legs), which
    uniformly covers entry (from flat), a flip, or going flat.

    Args:
        observation_dates: strictly increasing valuation dates. Financing uses
            ACT/365 calendar-day accrual between adjacent observations.
        spot_close: daily spot close, one row per session.
        future_close: daily close of ``contract_id[i]`` (the held front month).
        contract_id: the futures contract held each day; a change marks a roll.
        config: book and cost parameters.
        position_sign: per-day book direction in ``{-1, 0, +1}`` (default all +1).
            ``position_sign[i]`` is the direction held *during* day ``i`` and must be
            decided from information no later than day ``i-1`` (the caller's job).
        rebalance: optional per-day flags; on a rebalance day with no direction
            change and no roll, the hedge is re-struck (one spot + one futures side).
        settlement_fee: per-day flags indicating that the configured futures
            overnight fee applies to each open contract on that settlement date.

    Returns:
        A ``BasisCarryResult`` with per-day gross, financing, overnight, trade,
        and net P&L components.
    """
    n = len(spot_close)
    if not (len(observation_dates) == len(future_close) == len(contract_id) == n):
        raise ValueError(
            "observation_dates, spot_close, future_close, contract_id must be equal length"
        )
    if position_sign is not None and len(position_sign) != n:
        raise ValueError("position_sign must match the input length")
    if rebalance is not None and len(rebalance) != n:
        raise ValueError("rebalance must match the input length")
    if settlement_fee is not None and len(settlement_fee) != n:
        raise ValueError("settlement_fee must match the input length")
    if n == 0:
        return BasisCarryResult((), (), (), (), (), (), (), 0.0, 0)

    if any(observation_dates[i] <= observation_dates[i - 1] for i in range(1, n)):
        raise ValueError("observation_dates must be strictly increasing")
    if any(not isfinite(price) or price <= 0 for price in (*spot_close, *future_close)):
        raise ValueError("spot_close and future_close must contain positive finite prices")
    if any(not identifier for identifier in contract_id):
        raise ValueError("contract_id values must be non-empty")

    signs = list(position_sign) if position_sign is not None else [1] * n
    if any(s not in (-1, 0, 1) for s in signs):
        raise ValueError("position_sign values must be -1, 0, or 1")

    qty = config.contracts * config.contract_multiplier
    gross = [0.0] * n
    long_spot_financing = [0.0] * n
    short_spot_borrow = [0.0] * n
    futures_margin_financing = [0.0] * n
    overnight = [0.0] * n
    trade = [0.0] * n
    n_rolls = 0
    prev_sign = 0

    for i in range(n):
        sign_i = signs[i]
        spot_side = _spot_cost_per_side(spot_close[i], qty, config)
        fut_side = _futures_cost_per_side(future_close[i], config)
        rolled = False
        if i >= 1:
            elapsed_days = (observation_dates[i] - observation_dates[i - 1]).days
            spot_mtm = qty * (spot_close[i] - spot_close[i - 1])
            if contract_id[i] == contract_id[i - 1]:
                fut_mtm = -qty * (future_close[i] - future_close[i - 1])
            else:
                # Roll boundary: the two rows are different contracts. Never difference
                # across them -- that would inject the roll gap (the back-adjustment
                # artifact). The held futures leg is rolled at cost.
                fut_mtm = 0.0
                rolled = True
                n_rolls += 1
                if prev_sign != 0:
                    trade[i] += _futures_cost_per_side(future_close[i - 1], config)
                if sign_i != 0:
                    trade[i] += fut_side
            gross[i] = sign_i * (spot_mtm + fut_mtm)
            if sign_i > 0:
                long_spot_financing[i] = (
                    qty
                    * spot_close[i - 1]
                    * config.long_spot_financing_annual_rate
                    * elapsed_days
                    / 365.0
                )
            elif sign_i < 0:
                short_spot_borrow[i] = (
                    qty
                    * spot_close[i - 1]
                    * config.short_spot_borrow_annual_rate
                    * elapsed_days
                    / 365.0
                )
            futures_margin_financing[i] = (
                abs(sign_i)
                * qty
                * future_close[i - 1]
                * config.futures_margin_fraction
                * config.futures_margin_financing_annual_rate
                * elapsed_days
                / 365.0
            )
            if (
                rebalance is not None
                and rebalance[i]
                and sign_i == prev_sign
                and sign_i != 0
                and contract_id[i] == contract_id[i - 1]
            ):
                trade[i] += spot_side + fut_side
        # Entry / flip / flat: trade both legs in proportion to the direction
        # change. At a roll, futures close/open sides were counted explicitly
        # above; only the spot direction change remains here.
        direction_change = abs(sign_i - prev_sign)
        trade[i] += direction_change * (spot_side if rolled else spot_side + fut_side)
        if settlement_fee is not None and settlement_fee[i] and sign_i != 0:
            overnight[i] = config.contracts * config.futures_overnight_fee_per_contract
        prev_sign = sign_i

    net = [
        gross[i]
        - long_spot_financing[i]
        - short_spot_borrow[i]
        - futures_margin_financing[i]
        - overnight[i]
        - trade[i]
        for i in range(n)
    ]
    return BasisCarryResult(
        gross_pnl=tuple(gross),
        long_spot_financing_cost=tuple(long_spot_financing),
        short_spot_borrow_cost=tuple(short_spot_borrow),
        futures_margin_financing_cost=tuple(futures_margin_financing),
        overnight_fee_cost=tuple(overnight),
        trade_cost=tuple(trade),
        net_pnl=tuple(net),
        total_net=float(sum(net)),
        n_rolls=n_rolls,
    )
