"""Accounting utilities: positions (FIFO), settlement, and portfolio snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

from liq.types import Fill, PortfolioState, Position
from liq.sim.fx import convert_to_usd
from liq.sim.financing import borrow_cost, daily_swap, swap_applicable, swap_multiplier_for_weekday


@dataclass
class PositionLot:
    """Single lot with entry price and time."""

    quantity: Decimal  # positive for long, negative for short
    entry_price: Decimal
    entry_time: datetime


@dataclass
class SettlementEntry:
    """Proceeds awaiting settlement."""

    amount: Decimal
    release_time: datetime


@dataclass
class PositionRecord:
    """Tracks lots and realized P&L for a symbol."""

    lots: List[PositionLot] = field(default_factory=list)
    realized_pnl: Decimal = Decimal("0")

    @property
    def net_quantity(self) -> Decimal:
        return sum(l.quantity for l in self.lots)

    @property
    def avg_entry_price(self) -> Decimal:
        net_qty = self.net_quantity
        if net_qty == 0:
            return Decimal("0")
        weighted = sum(l.entry_price * l.quantity for l in self.lots)
        return weighted / net_qty

    def apply_fill(self, fill: Fill) -> Decimal:
        """Apply a fill to lots and return realized P&L from this fill."""
        remaining = fill.quantity
        realized = Decimal("0")

        # Determine direction: sells reduce long or increase short; buys reduce short or increase long.
        if fill.side.value == "sell":
            # First close existing long lots
            remaining, realized_close = self._consume_lots(
                remaining, fill.price, is_closing_long=True
            )
            realized += realized_close
            # Any remaining becomes new short exposure
            if remaining > 0:
                self.lots.append(
                    PositionLot(quantity=-remaining, entry_price=fill.price, entry_time=fill.timestamp)
                )
        else:  # buy
            # Close shorts first
            remaining, realized_close = self._consume_lots(
                remaining, fill.price, is_closing_long=False
            )
            realized += realized_close
            # Remaining increases long exposure
            if remaining > 0:
                self.lots.append(
                    PositionLot(quantity=remaining, entry_price=fill.price, entry_time=fill.timestamp)
                )

        self.realized_pnl += realized
        return realized

    def _consume_lots(
        self,
        quantity: Decimal,
        fill_price: Decimal,
        *,
        is_closing_long: bool,
    ) -> tuple[Decimal, Decimal]:
        """Consume lots FIFO and return (remaining_quantity, realized_pnl_delta)."""
        realized = Decimal("0")
        idx = 0
        while quantity > 0 and idx < len(self.lots):
            lot = self.lots[idx]
            if is_closing_long and lot.quantity <= 0:
                idx += 1
                continue
            if not is_closing_long and lot.quantity >= 0:
                idx += 1
                continue

            close_qty = min(quantity, abs(lot.quantity))
            if is_closing_long:
                pnl = (fill_price - lot.entry_price) * close_qty
                lot.quantity -= close_qty
            else:
                pnl = (lot.entry_price - fill_price) * close_qty
                lot.quantity += close_qty  # lot.quantity is negative; adding reduces abs
            realized += pnl
            quantity -= close_qty

            if lot.quantity == 0:
                self.lots.pop(idx)
            else:
                idx += 1
        return quantity, realized


@dataclass
class AccountState:
    """Mutable account state for the simulation."""

    cash: Decimal
    unsettled_cash: Decimal = Decimal("0")
    positions: Dict[str, PositionRecord] = field(default_factory=dict)
    settlement_queue: List[SettlementEntry] = field(default_factory=list)
    day_trades_remaining: Optional[int] = None
    account_currency: str = "USD"
    last_swap_time: datetime | None = None

    def apply_fill(
        self,
        fill: Fill,
        *,
        settlement_days: int = 0,
        borrow_rate_annual: Decimal | None = None,
        fx_rates: dict[str, Decimal] | None = None,
    ) -> Decimal:
        """Apply a fill and return realized P&L for this fill."""
        symbol_rec = self.positions.setdefault(fill.symbol, PositionRecord())
        symbol_key = fill.symbol.replace("-", "_")
        realized_trade_ccy = symbol_rec.apply_fill(fill)
        realized = realized_trade_ccy

        notional = fill.price * fill.quantity
        notional_account_ccy = notional
        if fx_rates and self.account_currency == "USD" and "_" in symbol_key:
            try:
                notional_account_ccy = convert_to_usd(notional, symbol_key, fx_rates)
            except KeyError:
                notional_account_ccy = notional

        total_cost = notional_account_ccy + fill.commission

        if fill.side.value == "buy":
            self.cash -= total_cost
        else:
            proceeds = notional_account_ccy - fill.commission
            if settlement_days > 0:
                release_time = fill.timestamp + timedelta(days=settlement_days)
                self.settlement_queue.append(SettlementEntry(amount=proceeds, release_time=release_time))
                self.unsettled_cash += proceeds
            else:
                self.cash += proceeds
        # borrow cost for shorts accrued daily if configured
        if borrow_rate_annual and symbol_rec.net_quantity < 0:
            # accrue cost immediately for simplicity; production would do daily accrual
            borrow_mark = fill.price
            if fx_rates and self.account_currency == "USD" and "_" in symbol_key:
                try:
                    borrow_mark = convert_to_usd(fill.price, symbol_key, fx_rates)
                except KeyError:
                    borrow_mark = fill.price
            cost = borrow_cost(abs(symbol_rec.net_quantity) * borrow_mark, borrow_rate_annual)
            self.cash -= cost
        # FX conversion hook to keep realized P&L in account currency
        if fx_rates and self.account_currency == "USD" and "_" in symbol_key:
            try:
                realized_converted = convert_to_usd(realized_trade_ccy, symbol_key, fx_rates)
                if realized_converted != realized_trade_ccy:
                    # adjust stored realized to account currency
                    symbol_rec.realized_pnl += realized_converted - realized_trade_ccy
                realized = realized_converted
            except KeyError:
                # leave as-is if rate missing
                realized = realized_trade_ccy
        return realized

    def process_settlement(self, current_time: datetime) -> None:
        """Release settled cash from the queue."""
        remaining_queue = []
        for entry in self.settlement_queue:
            if current_time >= entry.release_time:
                self.unsettled_cash -= entry.amount
                self.cash += entry.amount
            else:
                remaining_queue.append(entry)
        self.settlement_queue = remaining_queue

    def apply_daily_swap(
        self,
        current_time: datetime,
        swap_rates: dict[str, Decimal],
        marks: dict[str, Decimal],
        fx_rates: dict[str, Decimal] | None = None,
    ) -> None:
        """Apply financing swaps at roll time using provided swap rates per symbol."""
        if not swap_applicable(current_time):
            return
        if self.last_swap_time and self.last_swap_time.date() == current_time.date():
            return
        for symbol, rec in self.positions.items():
            if rec.net_quantity == 0:
                continue
            rate = swap_rates.get(symbol)
            if rate is None:
                continue
            mark = marks.get(symbol)
            if mark is None:
                continue
            mark_ccy = mark
            if fx_rates and self.account_currency == "USD" and "_" in symbol.replace("-", "_"):
                try:
                    mark_ccy = convert_to_usd(mark, symbol.replace("-", "_"), fx_rates)
                except KeyError:
                    mark_ccy = mark
            multiplier = swap_multiplier_for_weekday(current_time)
            notional = abs(rec.net_quantity) * mark_ccy
            cost = daily_swap(notional, rate) * multiplier
            # longs pay if rate positive; shorts receive if negative (simplified)
            if rec.net_quantity > 0:
                self.cash -= cost
                rec.realized_pnl -= cost
            else:
                self.cash += cost
                rec.realized_pnl += cost
        self.last_swap_time = current_time

    def to_portfolio_state(
        self,
        marks: dict[str, Decimal],
        timestamp: datetime,
        fx_rates: dict[str, Decimal] | None = None,
    ) -> PortfolioState:
        """Convert to an immutable PortfolioState using provided mark prices."""
        positions: dict[str, Position] = {}
        total_realized = Decimal("0")
        equity = self.cash + self.unsettled_cash
        for symbol, rec in self.positions.items():
            qty = rec.net_quantity
            mark = marks.get(symbol, rec.avg_entry_price)
            # Convert mark and cost basis to account currency if FX provided
            mark_notional = qty * mark
            cost_notional = qty * rec.avg_entry_price
            if fx_rates and self.account_currency == "USD" and "_" in symbol.replace("-", "_"):
                symbol_key = symbol.replace("-", "_")
                try:
                    mark_notional = convert_to_usd(mark_notional, symbol_key, fx_rates)
                except KeyError:
                    pass
                try:
                    cost_notional = convert_to_usd(cost_notional, symbol_key, fx_rates)
                except KeyError:
                    pass
            if qty != 0:
                mark_for_state = mark_notional / qty
                avg_price_state = cost_notional / qty
            else:
                mark_for_state = mark
                avg_price_state = rec.avg_entry_price
            positions[symbol] = Position(
                symbol=symbol,
                quantity=qty,
                average_price=avg_price_state,
                realized_pnl=rec.realized_pnl,
                timestamp=timestamp,
                current_price=mark_for_state,
            )
            total_realized += rec.realized_pnl
            equity += mark_notional

        return PortfolioState(
            cash=self.cash,
            unsettled_cash=self.unsettled_cash,
            positions=positions,
            realized_pnl=total_realized,
            buying_power=None,
            margin_used=None,
            day_trades_remaining=self.day_trades_remaining,
            timestamp=timestamp,
            # Override equity with signed mark-to-market
            equity=equity,
        )
