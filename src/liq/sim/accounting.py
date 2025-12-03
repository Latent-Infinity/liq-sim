"""Accounting utilities: positions (FIFO), settlement, and portfolio snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

from liq.types import Fill, PortfolioState, Position


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

    def apply_fill(
        self,
        fill: Fill,
        *,
        settlement_days: int = 0,
    ) -> Decimal:
        """Apply a fill and return realized P&L for this fill."""
        symbol_rec = self.positions.setdefault(fill.symbol, PositionRecord())
        realized = symbol_rec.apply_fill(fill)

        notional = fill.price * fill.quantity
        total_cost = notional + fill.commission

        if fill.side.value == "buy":
            self.cash -= total_cost
        else:
            proceeds = notional - fill.commission
            if settlement_days > 0:
                release_time = fill.timestamp + timedelta(days=settlement_days)
                self.settlement_queue.append(SettlementEntry(amount=proceeds, release_time=release_time))
                self.unsettled_cash += proceeds
            else:
                self.cash += proceeds
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

    def to_portfolio_state(self, marks: dict[str, Decimal], timestamp: datetime) -> PortfolioState:
        """Convert to an immutable PortfolioState using provided mark prices."""
        positions: dict[str, Position] = {}
        total_realized = Decimal("0")
        equity = self.cash + self.unsettled_cash
        for symbol, rec in self.positions.items():
            qty = rec.net_quantity
            mark = marks.get(symbol, rec.avg_entry_price)
            positions[symbol] = Position(
                symbol=symbol,
                quantity=qty,
                average_price=rec.avg_entry_price,
                realized_pnl=rec.realized_pnl,
                timestamp=timestamp,
                current_price=mark,
            )
            total_realized += rec.realized_pnl
            equity += qty * mark

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
