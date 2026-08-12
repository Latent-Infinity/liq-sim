"""Tests for the spot-futures basis-carry P&L engine."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from liq.sim.basis_carry import BasisCarryConfig
from liq.sim.basis_carry import simulate_basis_carry as _simulate_basis_carry

FREE = BasisCarryConfig(
    contract_multiplier=1.0,
    contracts=1,
    long_spot_financing_annual_rate=0.0,
    short_spot_borrow_annual_rate=0.0,
    futures_margin_fraction=0.0,
    futures_margin_financing_annual_rate=0.0,
    futures_fee_per_contract=0.0,
    futures_overnight_fee_per_contract=0.0,
    futures_slippage_bps=0.0,
    spot_fee_bps=0.0,
)


def _config(**overrides: float | int) -> BasisCarryConfig:
    params: dict[str, float | int] = {
        "contract_multiplier": 1.0,
        "contracts": 1,
        "long_spot_financing_annual_rate": 0.0,
        "short_spot_borrow_annual_rate": 0.0,
        "futures_margin_fraction": 0.0,
        "futures_margin_financing_annual_rate": 0.0,
        "futures_fee_per_contract": 0.0,
        "futures_overnight_fee_per_contract": 0.0,
        "futures_slippage_bps": 0.0,
        "spot_fee_bps": 0.0,
    }
    params.update(overrides)
    return BasisCarryConfig(**params)  # type: ignore[arg-type]


def simulate_basis_carry(
    spot_close: list[float],
    future_close: list[float],
    contract_id: list[str],
    config: BasisCarryConfig,
    *,
    observation_dates: list[date] | None = None,
    position_sign: list[int] | None = None,
    rebalance: list[bool] | None = None,
    settlement_fee: list[bool] | None = None,
):
    dates = observation_dates or [
        date(2024, 1, 2) + timedelta(days=i) for i in range(len(spot_close))
    ]
    return _simulate_basis_carry(
        dates,
        spot_close,
        future_close,
        contract_id,
        config,
        position_sign=position_sign,
        rebalance=rebalance,
        settlement_fee=settlement_fee,
    )


class TestGrossCapture:
    def test_converging_basis_is_captured(self) -> None:
        """Long spot / short future captures the basis as the future converges."""
        spot = [100.0, 100.0, 100.0]
        future = [105.0, 102.0, 100.0]  # basis 5 -> 0
        res = simulate_basis_carry(spot, future, ["A", "A", "A"], FREE)
        # cum gross == initial abs basis - final abs basis == 5 - 0
        assert res.gross_pnl == (0.0, 3.0, 2.0)
        assert res.total_net == pytest.approx(5.0)
        assert res.n_rolls == 0

    def test_widening_basis_loses(self) -> None:
        """The book loses when the basis widens against it (future rises vs spot)."""
        spot = [100.0, 100.0]
        future = [105.0, 108.0]  # basis 5 -> 8 (widening contango, against the book)
        res = simulate_basis_carry(spot, future, ["A", "A"], FREE)
        assert res.total_net == pytest.approx(-3.0)


class TestRollAccounting:
    def test_roll_never_differences_across_contracts(self) -> None:
        """The roll-gap between two contracts must NOT enter P&L (Finding 1)."""
        spot = [100.0, 100.0, 100.0, 100.0]
        # Contract A ends at 103; contract B opens at 130 (a 27-point roll gap).
        future = [105.0, 103.0, 130.0, 128.0]
        res = simulate_basis_carry(spot, future, ["A", "A", "B", "B"], FREE)
        # Day 2 is the roll: gross must be spot-mtm only (0.0), never -(130-103).
        assert res.gross_pnl[2] == 0.0
        assert res.gross_pnl == (0.0, 2.0, 0.0, 2.0)
        assert res.n_rolls == 1

    def test_roll_incurs_two_futures_sides(self) -> None:
        cfg = _config(futures_fee_per_contract=0.5)
        spot = [100.0, 100.0, 100.0]
        future = [105.0, 120.0, 118.0]
        res = simulate_basis_carry(spot, future, ["A", "B", "B"], cfg)
        # entry = 1 futures side (0.5); roll day = 2 futures sides (1.0)
        assert res.trade_cost[0] == pytest.approx(0.5)
        assert res.trade_cost[1] == pytest.approx(1.0)
        assert res.n_rolls == 1

    def test_direction_flip_on_roll_does_not_double_count_futures_sides(self) -> None:
        cfg = _config(futures_fee_per_contract=0.5)
        res = simulate_basis_carry(
            [100.0, 100.0],
            [105.0, 120.0],
            ["A", "B"],
            cfg,
            position_sign=[1, -1],
        )

        # Close the old future and open the new one: exactly two futures sides.
        assert res.trade_cost[1] == pytest.approx(1.0)


class TestCosts:
    def test_financing_reduces_net_below_gross(self) -> None:
        cfg = _config(long_spot_financing_annual_rate=0.05)
        spot = [100.0, 100.0]
        future = [105.0, 104.0]
        res = simulate_basis_carry(spot, future, ["A", "A"], cfg)
        assert res.long_spot_financing_cost[1] == pytest.approx(100.0 * 0.05 / 365.0)
        assert res.net_pnl[1] < res.gross_pnl[1]

    def test_daily_rebalance_adds_restrike_cost(self) -> None:
        cfg = _config(futures_fee_per_contract=0.25, spot_fee_bps=10.0)
        spot = [100.0, 100.0]
        future = [105.0, 104.0]
        res = simulate_basis_carry(spot, future, ["A", "A"], cfg, rebalance=[False, True])
        expected = 10.0 / 1e4 * 100.0 + 0.25  # one spot side + one futures side
        assert res.trade_cost[1] == pytest.approx(expected)

    def test_long_spot_and_short_spot_use_separate_rates(self) -> None:
        cfg = _config(
            long_spot_financing_annual_rate=0.05,
            short_spot_borrow_annual_rate=0.12,
        )
        long_result = simulate_basis_carry(
            [100.0, 100.0], [105.0, 105.0], ["A", "A"], cfg, position_sign=[1, 1]
        )
        short_result = simulate_basis_carry(
            [100.0, 100.0], [105.0, 105.0], ["A", "A"], cfg, position_sign=[-1, -1]
        )

        assert long_result.long_spot_financing_cost[1] == pytest.approx(100.0 * 0.05 / 365.0)
        assert long_result.short_spot_borrow_cost[1] == 0.0
        assert short_result.long_spot_financing_cost[1] == 0.0
        assert short_result.short_spot_borrow_cost[1] == pytest.approx(100.0 * 0.12 / 365.0)

    def test_act_365_accrues_over_calendar_gap(self) -> None:
        cfg = _config(long_spot_financing_annual_rate=0.05)
        result = simulate_basis_carry(
            [100.0, 100.0],
            [105.0, 105.0],
            ["A", "A"],
            cfg,
            observation_dates=[date(2024, 1, 5), date(2024, 1, 8)],
        )

        assert result.long_spot_financing_cost[1] == pytest.approx(100.0 * 0.05 * 3 / 365.0)

    def test_futures_margin_financing_is_separate(self) -> None:
        cfg = _config(
            futures_margin_fraction=0.25,
            futures_margin_financing_annual_rate=0.08,
        )
        result = simulate_basis_carry([100.0, 100.0], [120.0, 120.0], ["A", "A"], cfg)

        assert result.futures_margin_financing_cost[1] == pytest.approx(120.0 * 0.25 * 0.08 / 365.0)

    def test_overnight_fee_uses_explicit_settlement_flags(self) -> None:
        cfg = _config(contracts=2, futures_overnight_fee_per_contract=0.10)
        result = simulate_basis_carry(
            [100.0, 100.0, 100.0],
            [105.0, 105.0, 105.0],
            ["A", "A", "A"],
            cfg,
            settlement_fee=[False, True, False],
        )

        assert result.overnight_fee_cost == (0.0, 0.20, 0.0)

    def test_net_reconciles_every_cost_component(self) -> None:
        cfg = _config(
            long_spot_financing_annual_rate=0.05,
            futures_margin_fraction=0.25,
            futures_margin_financing_annual_rate=0.08,
            futures_fee_per_contract=0.50,
            futures_overnight_fee_per_contract=0.10,
        )
        result = simulate_basis_carry(
            [100.0, 101.0],
            [105.0, 104.0],
            ["A", "A"],
            cfg,
            settlement_fee=[False, True],
        )

        for i in range(2):
            expected = (
                result.gross_pnl[i]
                - result.long_spot_financing_cost[i]
                - result.short_spot_borrow_cost[i]
                - result.futures_margin_financing_cost[i]
                - result.overnight_fee_cost[i]
                - result.trade_cost[i]
            )
            assert result.net_pnl[i] == pytest.approx(expected)


class TestDirection:
    def test_short_basis_negates_pnl(self) -> None:
        spot = [100.0, 100.0, 100.0]
        future = [105.0, 102.0, 100.0]
        long_res = simulate_basis_carry(spot, future, ["A", "A", "A"], FREE)
        short_res = simulate_basis_carry(
            spot, future, ["A", "A", "A"], FREE, position_sign=[-1, -1, -1]
        )
        assert short_res.total_net == pytest.approx(-long_res.total_net)
        assert short_res.gross_pnl == (0.0, -3.0, -2.0)

    def test_flat_has_no_pnl_or_cost(self) -> None:
        cfg = _config(
            contract_multiplier=0.1,
            long_spot_financing_annual_rate=0.05,
            futures_fee_per_contract=0.35,
            futures_slippage_bps=1.0,
            spot_fee_bps=8.0,
        )
        spot = [100.0, 101.0, 102.0]
        future = [105.0, 104.0, 103.0]
        res = simulate_basis_carry(spot, future, ["A", "A", "A"], cfg, position_sign=[0, 0, 0])
        assert res.gross_pnl == (0.0, 0.0, 0.0)
        assert res.long_spot_financing_cost == (0.0, 0.0, 0.0)
        assert res.short_spot_borrow_cost == (0.0, 0.0, 0.0)
        assert res.futures_margin_financing_cost == (0.0, 0.0, 0.0)
        assert res.trade_cost == (0.0, 0.0, 0.0)
        assert res.total_net == 0.0

    def test_flip_trades_both_legs_twice(self) -> None:
        cfg = _config(futures_fee_per_contract=0.5, spot_fee_bps=10.0)
        spot = [100.0, 100.0]
        future = [105.0, 104.0]
        res = simulate_basis_carry(spot, future, ["A", "A"], cfg, position_sign=[1, -1])
        spot_side = 10.0 / 1e4 * 100.0  # 0.1
        fut_side = 0.5
        assert res.trade_cost[1] == pytest.approx(2 * (spot_side + fut_side))  # |-1 - 1| = 2

    def test_invalid_sign_raises(self) -> None:
        with pytest.raises(ValueError, match="position_sign"):
            simulate_basis_carry([1.0, 2.0], [1.0, 2.0], ["A", "A"], FREE, position_sign=[2, 0])


class TestLookAhead:
    def test_truncation_leaves_earlier_days_unchanged(self) -> None:
        """Each day's P&L uses only that day and the prior one (no look-ahead)."""
        cfg = _config(
            contract_multiplier=0.1,
            long_spot_financing_annual_rate=0.05,
            futures_fee_per_contract=0.35,
            futures_slippage_bps=1.0,
            spot_fee_bps=8.0,
        )
        spot = [100.0, 101.0, 99.0, 100.0, 102.0, 101.0]
        future = [104.0, 103.0, 130.0, 129.0, 128.0, 126.0]
        cid = ["A", "A", "B", "B", "B", "B"]
        sign = [1, 1, -1, -1, 0, 1]  # includes flips and a flat day
        full = simulate_basis_carry(spot, future, cid, cfg, position_sign=sign)
        for t in range(1, len(spot)):
            trunc = simulate_basis_carry(
                spot[: t + 1], future[: t + 1], cid[: t + 1], cfg, position_sign=sign[: t + 1]
            )
            assert trunc.net_pnl == full.net_pnl[: t + 1]


class TestFrozenFixture:
    def test_regression_pins_exact_series(self) -> None:
        cfg = _config(
            contract_multiplier=0.1,
            contracts=2,
            long_spot_financing_annual_rate=0.05,
            futures_fee_per_contract=0.35,
            futures_slippage_bps=1.0,
            spot_fee_bps=8.0,
        )
        spot = [40000.0, 40500.0, 40200.0]
        future = [40600.0, 40450.0, 40250.0]
        res = simulate_basis_carry(spot, future, ["MBTZ24", "MBTZ24", "MBTZ24"], cfg)
        qty = 0.2  # 2 contracts * 0.1
        # entry cost: spot 8bps on 0.2*40000 + futures (0.35*2 + 1bp on 0.2*40600)
        exp_entry = 8.0 / 1e4 * (qty * 40000.0) + (0.35 * 2 + 1.0 / 1e4 * (qty * 40600.0))
        assert res.trade_cost[0] == pytest.approx(exp_entry)
        # day1 gross = 0.2*((40500-40000) - (40450-40600)) = 0.2*(500 + 150) = 130.0
        assert res.gross_pnl[1] == pytest.approx(130.0)
        assert res.long_spot_financing_cost[1] == pytest.approx(qty * 40000.0 * 0.05 / 365.0)
        # day2 gross = 0.2*((40200-40500) - (40250-40450)) = 0.2*(-300 + 200) = -20.0
        assert res.gross_pnl[2] == pytest.approx(-20.0)
        assert res.n_rolls == 0


class TestValidation:
    def test_mismatched_lengths_raise(self) -> None:
        with pytest.raises(ValueError, match="equal length"):
            simulate_basis_carry([1.0, 2.0], [1.0], ["A", "A"], FREE)

    def test_empty_series_is_zero(self) -> None:
        res = simulate_basis_carry([], [], [], FREE)
        assert res.total_net == 0.0
        assert res.net_pnl == ()

    def test_dates_must_match_and_increase(self) -> None:
        with pytest.raises(ValueError, match="equal length"):
            _simulate_basis_carry([date(2024, 1, 2)], [1.0, 2.0], [1.0, 2.0], ["A", "A"], FREE)
        with pytest.raises(ValueError, match="strictly increasing"):
            simulate_basis_carry(
                [1.0, 2.0],
                [1.0, 2.0],
                ["A", "A"],
                FREE,
                observation_dates=[date(2024, 1, 2), date(2024, 1, 2)],
            )

    def test_settlement_flags_must_match(self) -> None:
        with pytest.raises(ValueError, match="settlement_fee"):
            simulate_basis_carry([1.0, 2.0], [1.0, 2.0], ["A", "A"], FREE, settlement_fee=[True])

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("contract_multiplier", 0.0),
            ("contracts", 0),
            ("long_spot_financing_annual_rate", -0.01),
            ("short_spot_borrow_annual_rate", -0.01),
            ("futures_margin_fraction", 1.01),
            ("futures_margin_financing_annual_rate", -0.01),
            ("futures_fee_per_contract", -0.01),
            ("futures_overnight_fee_per_contract", -0.01),
            ("futures_slippage_bps", -0.01),
            ("spot_fee_bps", -0.01),
            ("long_spot_financing_annual_rate", float("nan")),
        ],
    )
    def test_invalid_config_is_rejected(self, field: str, value: float | int) -> None:
        with pytest.raises(ValueError, match=field):
            _config(**{field: value})
