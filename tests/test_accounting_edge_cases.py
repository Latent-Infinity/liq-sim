"""Tests for accounting edge cases including FX conversion and settlement.

Following TDD: Tests verify accounting behavior with FX rates and borrow costs.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from liq.core import Fill, OrderSide

from liq.sim.accounting import AccountState, PositionLot, PositionRecord


def make_fill(
    symbol: str,
    side: OrderSide,
    quantity: str,
    price: str,
    ts: datetime,
    commission: str = "0",
) -> Fill:
    """Create a fill for testing."""
    return Fill(
        fill_id=uuid4(),
        client_order_id=uuid4(),
        symbol=symbol,
        side=side,
        quantity=Decimal(quantity),
        price=Decimal(price),
        commission=Decimal(commission),
        slippage=Decimal("0"),
        realized_pnl=None,
        timestamp=ts,
    )


class TestFXConversionInAccounting:
    """Tests for FX conversion in accounting operations."""

    def test_fx_conversion_on_buy_fill(self) -> None:
        """Buy fill with FX symbol should convert notional correctly."""
        account = AccountState(cash=Decimal("10000"))
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # EUR_USD position - buying EUR
        fill = make_fill("EUR-USD", OrderSide.BUY, "1000", "1.10", t0)
        fx_rates = {"EUR_USD": Decimal("1.10")}

        account.apply_fill(fill, fx_rates=fx_rates)

        # 1000 EUR * 1.10 USD/EUR = $1100 USD
        # Cash reduced by $1100
        assert account.cash == Decimal("8900")

    def test_fx_conversion_on_sell_fill_with_settlement(self) -> None:
        """Sell fill with FX should convert and settle correctly."""
        account = AccountState(cash=Decimal("10000"))
        account.positions["EUR-USD"] = PositionRecord(
            lots=[
                PositionLot(
                    quantity=Decimal("1000"),
                    entry_price=Decimal("1.08"),
                    entry_time=datetime(2024, 1, 1, tzinfo=UTC),
                )
            ],
            realized_pnl=Decimal("0"),
        )
        t0 = datetime(2024, 1, 2, tzinfo=UTC)
        fill = make_fill("EUR-USD", OrderSide.SELL, "1000", "1.10", t0)
        fx_rates = {"EUR_USD": Decimal("1.10")}

        realized = account.apply_fill(fill, settlement_days=2, fx_rates=fx_rates)

        # Proceeds = 1000 * 1.10 = 1100 USD
        # Goes to unsettled due to settlement_days > 0
        assert account.unsettled_cash == Decimal("1100")
        assert len(account.settlement_queue) == 1
        # Realized P&L: (1.10 - 1.08) * 1000 = 20 (before FX conversion)
        # With FX conversion applied
        assert realized > 0

    def test_fx_rate_missing_uses_raw_value(self) -> None:
        """Missing FX rate should use raw values with warning (not raise)."""
        account = AccountState(cash=Decimal("10000"))
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        fill = make_fill("GBP-USD", OrderSide.BUY, "1000", "1.25", t0)
        # Provide rates but NOT for GBP_USD
        fx_rates = {"EUR_USD": Decimal("1.10")}

        # Should not raise - logs warning and uses raw value
        account.apply_fill(fill, fx_rates=fx_rates)

        # Notional: 1000 * 1.25 = 1250 (raw, no conversion)
        assert account.cash == Decimal("8750")


class TestBorrowCostInAccounting:
    """Tests for borrow cost application on short positions."""

    def test_borrow_cost_applied_on_short(self) -> None:
        """Short position should have borrow cost applied."""
        account = AccountState(cash=Decimal("10000"))
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        # Short sell
        fill = make_fill("AAPL", OrderSide.SELL, "100", "150", t0)
        borrow_rate = Decimal("0.05")  # 5% annual

        account.apply_fill(fill, borrow_rate_annual=borrow_rate)

        # Position is now short 100 shares
        assert account.positions["AAPL"].net_quantity == Decimal("-100")
        # Borrow cost was deducted from cash
        # Cash = 10000 + (100 * 150) - borrow_cost
        # borrow_cost = (100 * 150 * 0.05) / 365 ~ 2.05
        assert account.cash < Decimal("25000")
        assert account.cash > Decimal("24997")

    def test_borrow_cost_with_fx_symbol(self) -> None:
        """Borrow cost on FX short should convert properly."""
        account = AccountState(cash=Decimal("10000"))
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        fill = make_fill("EUR-USD", OrderSide.SELL, "1000", "1.10", t0)
        fx_rates = {"EUR_USD": Decimal("1.10")}
        borrow_rate = Decimal("0.02")

        account.apply_fill(fill, borrow_rate_annual=borrow_rate, fx_rates=fx_rates)

        # Short position in EUR-USD
        assert account.positions["EUR-USD"].net_quantity == Decimal("-1000")


class TestSettlementQueue:
    """Tests for settlement queue processing."""

    def test_settlement_released_when_due(self) -> None:
        """Settlement should release to cash when time is reached."""
        account = AccountState(cash=Decimal("10000"))
        account.positions["AAPL"] = PositionRecord(
            lots=[
                PositionLot(
                    quantity=Decimal("100"),
                    entry_price=Decimal("100"),
                    entry_time=datetime(2024, 1, 1, tzinfo=UTC),
                )
            ],
            realized_pnl=Decimal("0"),
        )
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        t2 = datetime(2024, 1, 3, tzinfo=UTC)

        # Sell with 2-day settlement
        fill = make_fill("AAPL", OrderSide.SELL, "100", "110", t0)
        account.apply_fill(fill, settlement_days=2)

        # Cash unchanged, unsettled has proceeds
        assert account.unsettled_cash == Decimal("11000")
        initial_cash = account.cash

        # Process settlement at day 3 (release_time = t0 + 2 days)
        account.process_settlement(t2)

        # Cash now includes proceeds
        assert account.cash == initial_cash + Decimal("11000")
        assert account.unsettled_cash == Decimal("0")
        assert len(account.settlement_queue) == 0

    def test_settlement_not_released_before_due(self) -> None:
        """Settlement should not release before release time."""
        account = AccountState(cash=Decimal("10000"))
        account.positions["AAPL"] = PositionRecord(
            lots=[
                PositionLot(
                    quantity=Decimal("100"),
                    entry_price=Decimal("100"),
                    entry_time=datetime(2024, 1, 1, tzinfo=UTC),
                )
            ],
            realized_pnl=Decimal("0"),
        )
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        t1 = datetime(2024, 1, 2, tzinfo=UTC)

        fill = make_fill("AAPL", OrderSide.SELL, "100", "110", t0)
        account.apply_fill(fill, settlement_days=2)
        initial_cash = account.cash

        # Process at day 2 (before release at day 3)
        account.process_settlement(t1)

        # Cash unchanged, still unsettled
        assert account.cash == initial_cash
        assert account.unsettled_cash == Decimal("11000")
        assert len(account.settlement_queue) == 1

    def test_multiple_settlements_on_same_day(self) -> None:
        """Multiple settlements due on same day should all release."""
        account = AccountState(cash=Decimal("10000"))
        account.positions["AAPL"] = PositionRecord(
            lots=[
                PositionLot(
                    quantity=Decimal("200"),
                    entry_price=Decimal("100"),
                    entry_time=datetime(2024, 1, 1, tzinfo=UTC),
                )
            ],
            realized_pnl=Decimal("0"),
        )
        t0 = datetime(2024, 1, 1, 9, 0, tzinfo=UTC)
        t0_later = datetime(2024, 1, 1, 14, 0, tzinfo=UTC)
        # Settlement time is t0 + 2 days, so need to process at/after day 3, 9:00
        t3 = datetime(2024, 1, 3, 15, 0, tzinfo=UTC)

        # Two sells on same day, both settle day 3
        fill1 = make_fill("AAPL", OrderSide.SELL, "100", "105", t0)
        account.apply_fill(fill1, settlement_days=2)
        fill2 = make_fill("AAPL", OrderSide.SELL, "100", "107", t0_later)
        account.apply_fill(fill2, settlement_days=2)

        assert len(account.settlement_queue) == 2
        assert account.unsettled_cash == Decimal("21200")  # 10500 + 10700

        # Process on day 3 at 15:00 (after both release times)
        account.process_settlement(t3)

        assert account.unsettled_cash == Decimal("0")
        assert len(account.settlement_queue) == 0


class TestDailySwapApplication:
    """Tests for daily swap/financing cost application."""

    def test_swap_applied_to_long_position(self) -> None:
        """Long position should pay swap if rate is positive."""

        account = AccountState(cash=Decimal("10000"))
        account.positions["AAPL"] = PositionRecord(
            lots=[
                PositionLot(
                    quantity=Decimal("100"),
                    entry_price=Decimal("150"),
                    entry_time=datetime(2024, 1, 1, tzinfo=UTC),
                )
            ],
            realized_pnl=Decimal("0"),
        )
        # Wednesday at 5pm ET = roll time
        roll_time = datetime(2024, 1, 3, 22, 0, tzinfo=UTC)

        swap_rates = {"AAPL": Decimal("0.001")}  # 0.1% daily
        marks = {"AAPL": Decimal("155")}

        account.apply_daily_swap(roll_time, swap_rates, marks)

        # Long pays swap: notional * rate * multiplier (3x on Wed)
        # 100 * 155 * 0.001 * 3 = 46.5
        assert account.cash < Decimal("10000")
        assert account.last_swap_time == roll_time

    def test_swap_not_applied_twice_same_day(self) -> None:
        """Swap should only apply once per day."""
        account = AccountState(cash=Decimal("10000"))
        account.positions["AAPL"] = PositionRecord(
            lots=[
                PositionLot(
                    quantity=Decimal("100"),
                    entry_price=Decimal("150"),
                    entry_time=datetime(2024, 1, 1, tzinfo=UTC),
                )
            ],
            realized_pnl=Decimal("0"),
        )
        roll_time = datetime(2024, 1, 3, 22, 0, tzinfo=UTC)
        swap_rates = {"AAPL": Decimal("0.001")}
        marks = {"AAPL": Decimal("155")}

        # Apply once
        account.apply_daily_swap(roll_time, swap_rates, marks)
        cash_after_first = account.cash

        # Apply again same day
        roll_time_later = datetime(2024, 1, 3, 23, 0, tzinfo=UTC)
        account.apply_daily_swap(roll_time_later, swap_rates, marks)

        # Cash unchanged
        assert account.cash == cash_after_first

    def test_swap_skips_zero_quantity_position(self) -> None:
        """Swap should not apply to zero quantity positions."""
        account = AccountState(cash=Decimal("10000"))
        account.positions["AAPL"] = PositionRecord(
            lots=[],
            realized_pnl=Decimal("100"),  # Has realized but no open position
        )
        roll_time = datetime(2024, 1, 3, 22, 0, tzinfo=UTC)
        swap_rates = {"AAPL": Decimal("0.001")}
        marks = {"AAPL": Decimal("155")}

        account.apply_daily_swap(roll_time, swap_rates, marks)

        # Cash unchanged
        assert account.cash == Decimal("10000")

    def test_swap_short_receives_when_positive_rate(self) -> None:
        """Short position should receive swap when rate is positive (simplified)."""
        account = AccountState(cash=Decimal("10000"))
        account.positions["AAPL"] = PositionRecord(
            lots=[
                PositionLot(
                    quantity=Decimal("-100"),  # Short position
                    entry_price=Decimal("150"),
                    entry_time=datetime(2024, 1, 1, tzinfo=UTC),
                )
            ],
            realized_pnl=Decimal("0"),
        )
        roll_time = datetime(2024, 1, 3, 22, 0, tzinfo=UTC)
        swap_rates = {"AAPL": Decimal("0.001")}
        marks = {"AAPL": Decimal("155")}

        account.apply_daily_swap(roll_time, swap_rates, marks)

        # Short receives: cash increases
        assert account.cash > Decimal("10000")


class TestPositionRecordEdgeCases:
    """Tests for position record edge cases."""

    def test_close_partial_fifo(self) -> None:
        """Closing partial position should use FIFO."""
        rec = PositionRecord(
            lots=[
                PositionLot(
                    quantity=Decimal("100"),
                    entry_price=Decimal("100"),
                    entry_time=datetime(2024, 1, 1, tzinfo=UTC),
                ),
                PositionLot(
                    quantity=Decimal("100"),
                    entry_price=Decimal("110"),
                    entry_time=datetime(2024, 1, 2, tzinfo=UTC),
                ),
            ],
            realized_pnl=Decimal("0"),
        )
        t0 = datetime(2024, 1, 3, tzinfo=UTC)
        fill = make_fill("AAPL", OrderSide.SELL, "50", "120", t0)

        realized = rec.apply_fill(fill)

        # Closed 50 from first lot at $100, sold at $120 = +$1000 P&L
        assert realized == Decimal("1000")
        assert rec.lots[0].quantity == Decimal("50")
        assert rec.lots[1].quantity == Decimal("100")

    def test_close_exact_lot_removes_lot(self) -> None:
        """Closing exact lot quantity should remove the lot."""
        rec = PositionRecord(
            lots=[
                PositionLot(
                    quantity=Decimal("100"),
                    entry_price=Decimal("100"),
                    entry_time=datetime(2024, 1, 1, tzinfo=UTC),
                ),
            ],
            realized_pnl=Decimal("0"),
        )
        t0 = datetime(2024, 1, 2, tzinfo=UTC)
        fill = make_fill("AAPL", OrderSide.SELL, "100", "110", t0)

        realized = rec.apply_fill(fill)

        assert realized == Decimal("1000")
        assert len(rec.lots) == 0
        assert rec.net_quantity == Decimal("0")

    def test_remaining_idx_after_partial_close(self) -> None:
        """After partial close, remaining lot should stay in list."""
        rec = PositionRecord(
            lots=[
                PositionLot(
                    quantity=Decimal("100"),
                    entry_price=Decimal("100"),
                    entry_time=datetime(2024, 1, 1, tzinfo=UTC),
                ),
            ],
            realized_pnl=Decimal("0"),
        )
        t0 = datetime(2024, 1, 2, tzinfo=UTC)
        fill = make_fill("AAPL", OrderSide.SELL, "30", "110", t0)

        rec.apply_fill(fill)

        # Lot should still exist with reduced quantity
        assert len(rec.lots) == 1
        assert rec.lots[0].quantity == Decimal("70")


class TestPortfolioStateConversion:
    """Tests for portfolio state conversion edge cases."""

    def test_portfolio_state_with_fx_conversion(self) -> None:
        """Portfolio state should convert positions with FX rates."""
        account = AccountState(cash=Decimal("10000"))
        account.positions["EUR-USD"] = PositionRecord(
            lots=[
                PositionLot(
                    quantity=Decimal("1000"),
                    entry_price=Decimal("1.08"),
                    entry_time=datetime(2024, 1, 1, tzinfo=UTC),
                )
            ],
            realized_pnl=Decimal("0"),
        )
        t0 = datetime(2024, 1, 2, tzinfo=UTC)
        marks = {"EUR-USD": Decimal("1.10")}
        fx_rates = {"EUR_USD": Decimal("1.10")}

        state = account.to_portfolio_state(marks, t0, fx_rates)

        # Position value: 1000 * 1.10 = 1100 USD
        assert state.positions["EUR-USD"].quantity == Decimal("1000")
        # Equity: cash + position value
        assert state.equity == Decimal("11100")

    def test_portfolio_state_missing_fx_uses_raw(self) -> None:
        """Missing FX rate should use raw mark value."""
        account = AccountState(cash=Decimal("10000"))
        account.positions["GBP-USD"] = PositionRecord(
            lots=[
                PositionLot(
                    quantity=Decimal("1000"),
                    entry_price=Decimal("1.25"),
                    entry_time=datetime(2024, 1, 1, tzinfo=UTC),
                )
            ],
            realized_pnl=Decimal("0"),
        )
        t0 = datetime(2024, 1, 2, tzinfo=UTC)
        marks = {"GBP-USD": Decimal("1.27")}
        # No FX rate for GBP_USD
        fx_rates = {"EUR_USD": Decimal("1.10")}

        state = account.to_portfolio_state(marks, t0, fx_rates)

        # Uses raw values
        assert state.positions["GBP-USD"].quantity == Decimal("1000")
        # Equity: 10000 + 1000 * 1.27 = 11270
        assert state.equity == Decimal("11270")
