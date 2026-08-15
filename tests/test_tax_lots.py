"""Tax-lot selection and cross-account wash-sale tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from liq.core import Fill
from liq.core.enums import OrderSide

from liq.sim.tax_lots import AccountFill, TaxLotLedger


def _fill(
    sequence: int,
    *,
    side: str,
    quantity: str,
    price: str,
    day: int,
    symbol: str = "SPY",
    commission: str = "0",
) -> Fill:
    return Fill(
        fill_id=UUID(int=sequence),
        client_order_id=UUID(int=10_000 + sequence),
        symbol=symbol,
        side=OrderSide(side),
        quantity=Decimal(quantity),
        price=Decimal(price),
        commission=Decimal(commission),
        timestamp=datetime(2024, 1, day, 21, tzinfo=UTC),
    )


def _account_fill(sequence: int, account: str = "taxable", **kwargs: str | int) -> AccountFill:
    return AccountFill(account=account, fill=_fill(sequence, **kwargs))


def test_hifo_harvests_highest_basis_lot_first() -> None:
    ledger = TaxLotLedger(wash_sale_accounts={"taxable"})
    ledger.apply(_account_fill(1, side="buy", quantity="10", price="100", day=1))
    ledger.apply(_account_fill(2, side="buy", quantity="10", price="120", day=2))
    ledger.apply(_account_fill(3, side="sell", quantity="10", price="110", day=3))

    report = ledger.finalize()
    assert len(report.realizations) == 1
    assert report.realizations[0].cost_basis == Decimal("1200")
    assert report.realizations[0].realized_pnl == Decimal("-100")
    # The still-open lower-basis lot is also a pre-sale replacement inside the
    # 30-day window, so the selected loss carries into its basis.
    assert report.realizations[0].disallowed_loss == Decimal("100")
    assert report.open_lots[0].basis_per_share == Decimal("110")


def test_long_term_gain_is_selected_before_short_term_gain() -> None:
    ledger = TaxLotLedger(wash_sale_accounts={"taxable"})
    ledger.apply(
        AccountFill(
            account="taxable",
            fill=Fill(
                fill_id=UUID(int=1),
                client_order_id=UUID(int=10_001),
                symbol="SPY",
                side=OrderSide.BUY,
                quantity=Decimal("1"),
                price=Decimal("90"),
                commission=Decimal("0"),
                timestamp=datetime(2022, 1, 1, 21, tzinfo=UTC),
            ),
        )
    )
    ledger.apply(_account_fill(2, side="buy", quantity="1", price="100", day=2))
    ledger.apply(_account_fill(3, side="sell", quantity="1", price="110", day=3))

    realization = ledger.finalize().realizations[0]
    assert realization.character == "long_term"
    assert realization.cost_basis == Decimal("90")


def test_future_cross_account_purchase_disallows_loss_and_carries_basis() -> None:
    ledger = TaxLotLedger(wash_sale_accounts={"taxable", "retirement"})
    ledger.apply(_account_fill(1, side="buy", quantity="10", price="100", day=1))
    ledger.apply(_account_fill(2, side="sell", quantity="10", price="90", day=10))
    ledger.apply(
        _account_fill(
            3,
            account="retirement",
            side="buy",
            quantity="10",
            price="91",
            day=20,
        )
    )

    report = ledger.finalize()
    realization = report.realizations[0]
    assert realization.realized_pnl == Decimal("-100")
    assert realization.allowed_gain_loss == Decimal("0")
    assert realization.disallowed_loss == Decimal("100")
    assert report.open_lots[0].account == "retirement"
    assert report.open_lots[0].basis_per_share == Decimal("101")
    assert report.open_lots[0].holding_period_start.isoformat() == "2024-01-01"


def test_partial_replacement_only_disallows_matched_quantity() -> None:
    ledger = TaxLotLedger(wash_sale_accounts={"taxable", "retirement"})
    ledger.apply(_account_fill(1, side="buy", quantity="10", price="100", day=1))
    ledger.apply(_account_fill(2, side="sell", quantity="10", price="90", day=10))
    ledger.apply(
        _account_fill(
            3,
            account="retirement",
            side="buy",
            quantity="4",
            price="90",
            day=20,
        )
    )

    realization = ledger.finalize().realizations[0]
    assert realization.allowed_gain_loss == Decimal("-60")
    assert realization.disallowed_loss == Decimal("40")
    assert ledger.open_quantity("SPY") == Decimal("4")


def test_prior_open_purchase_inside_window_is_a_replacement() -> None:
    ledger = TaxLotLedger(wash_sale_accounts={"taxable", "retirement"})
    ledger.apply(_account_fill(1, side="buy", quantity="10", price="100", day=1))
    ledger.apply(
        _account_fill(
            2,
            account="retirement",
            side="buy",
            quantity="5",
            price="95",
            day=5,
        )
    )
    ledger.apply(_account_fill(3, side="sell", quantity="10", price="90", day=10))

    report = ledger.finalize()
    assert report.realizations[0].disallowed_loss == Decimal("50")
    replacement = next(lot for lot in report.open_lots if lot.account == "retirement")
    assert replacement.basis_per_share == Decimal("105")


def test_purchase_outside_window_does_not_disallow_loss() -> None:
    ledger = TaxLotLedger(wash_sale_accounts={"taxable", "retirement"})
    ledger.apply(_account_fill(1, side="buy", quantity="1", price="100", day=1))
    ledger.apply(_account_fill(2, side="sell", quantity="1", price="90", day=10))
    february = Fill(
        fill_id=UUID(int=3),
        client_order_id=UUID(int=10_003),
        symbol="SPY",
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        price=Decimal("80"),
        commission=Decimal("0"),
        timestamp=datetime(2024, 2, 11, 21, tzinfo=UTC),
    )
    ledger.apply(AccountFill(account="retirement", fill=february))

    realization = ledger.finalize().realizations[0]
    assert realization.allowed_gain_loss == Decimal("-10")
    assert realization.disallowed_loss == Decimal("0")


def test_commissions_enter_buy_basis_and_reduce_sale_proceeds() -> None:
    ledger = TaxLotLedger(wash_sale_accounts={"taxable"})
    ledger.apply(
        _account_fill(
            1,
            side="buy",
            quantity="2",
            price="100",
            day=1,
            commission="2",
        )
    )
    ledger.apply(
        _account_fill(
            2,
            side="sell",
            quantity="2",
            price="110",
            day=3,
            commission="2",
        )
    )

    realization = ledger.finalize().realizations[0]
    assert realization.cost_basis == Decimal("202")
    assert realization.proceeds == Decimal("218")
    assert realization.realized_pnl == Decimal("16")


def test_rejects_short_sale_duplicate_fill_and_unknown_account() -> None:
    ledger = TaxLotLedger(wash_sale_accounts={"taxable"})
    sell = _account_fill(1, side="sell", quantity="1", price="100", day=1)
    with pytest.raises(ValueError, match="short sales"):
        ledger.apply(sell)

    buy = _account_fill(2, side="buy", quantity="1", price="100", day=1)
    ledger.apply(buy)
    with pytest.raises(ValueError, match="duplicate fill"):
        ledger.apply(buy)

    with pytest.raises(ValueError, match="wash-sale domain"):
        ledger.apply(
            _account_fill(
                3,
                account="external",
                side="buy",
                quantity="1",
                price="100",
                day=2,
            )
        )
