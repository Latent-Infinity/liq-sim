"""Minimal long-only tax-lot accounting over canonical execution fills.

The ledger extends simulation accounting with the fields needed by Curve-F:
account labels, HIFO/specific-lot sale selection, holding-period character, and
same-symbol wash-sale basis carry across the configured account domain. It is
deliberately narrow: short sales and replacement-security equivalence are out
of scope until a frozen substantially-identical mapping exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from liq.core import Fill
from liq.core.enums import OrderSide

TaxCharacter = Literal["short_term", "long_term"]
_WASH_WINDOW = timedelta(days=30)


@dataclass(frozen=True)
class AccountFill:
    """A canonical fill labeled with its account in the wash-sale domain."""

    account: str
    fill: Fill


@dataclass(frozen=True)
class TaxLot:
    """Open tax lot after selection and wash-sale basis adjustments."""

    lot_id: str
    symbol: str
    account: str
    open_date: date
    holding_period_start: date
    quantity: Decimal
    basis_per_share: Decimal

    @property
    def cost_basis(self) -> Decimal:
        return self.quantity * self.basis_per_share


@dataclass(frozen=True)
class TaxRealization:
    """Closed-lot tax record with the currently deductible amount separated."""

    sale_id: str
    lot_id: str
    symbol: str
    account: str
    sale_date: date
    quantity: Decimal
    proceeds: Decimal
    cost_basis: Decimal
    realized_pnl: Decimal
    character: TaxCharacter
    disallowed_loss: Decimal

    @property
    def allowed_gain_loss(self) -> Decimal:
        return self.realized_pnl + self.disallowed_loss


@dataclass(frozen=True)
class TaxLotReport:
    """Final closed realizations and open lots after pending wash matches."""

    realizations: tuple[TaxRealization, ...]
    open_lots: tuple[TaxLot, ...]


@dataclass
class _OpenLot:
    lot_id: str
    symbol: str
    account: str
    open_date: date
    holding_period_start: date
    quantity: Decimal
    basis_per_share: Decimal
    wash_capacity: Decimal

    def public(self) -> TaxLot:
        return TaxLot(
            lot_id=self.lot_id,
            symbol=self.symbol,
            account=self.account,
            open_date=self.open_date,
            holding_period_start=self.holding_period_start,
            quantity=self.quantity,
            basis_per_share=self.basis_per_share,
        )


@dataclass
class _Realization:
    sale_id: str
    lot_id: str
    symbol: str
    account: str
    sale_date: date
    quantity: Decimal
    proceeds: Decimal
    cost_basis: Decimal
    realized_pnl: Decimal
    character: TaxCharacter
    source_holding_start: date
    loss_per_share: Decimal
    unmatched_loss_quantity: Decimal
    disallowed_loss: Decimal = Decimal("0")

    def public(self) -> TaxRealization:
        return TaxRealization(
            sale_id=self.sale_id,
            lot_id=self.lot_id,
            symbol=self.symbol,
            account=self.account,
            sale_date=self.sale_date,
            quantity=self.quantity,
            proceeds=self.proceeds,
            cost_basis=self.cost_basis,
            realized_pnl=self.realized_pnl,
            character=self.character,
            disallowed_loss=self.disallowed_loss,
        )


class TaxLotLedger:
    """Chronological HIFO ledger with 30-day cross-account wash-sale matching.

    The account set is the complete active wash-sale domain. Every applied fill
    must belong to it, which fails closed if an execution is accidentally left
    outside the cross-account check. Same-symbol matching is exact because no
    replacement-security mapping is authorized.
    """

    def __init__(self, *, wash_sale_accounts: set[str] | frozenset[str]) -> None:
        if not wash_sale_accounts or any(not account.strip() for account in wash_sale_accounts):
            raise ValueError("wash_sale_accounts must name the complete non-empty domain")
        self._accounts = frozenset(wash_sale_accounts)
        self._lots: list[_OpenLot] = []
        self._realizations: list[_Realization] = []
        self._fill_ids: set[str] = set()
        self._last_timestamp = None
        self._segment = 0

    def apply(self, account_fill: AccountFill) -> None:
        """Apply one chronological fill and update lots and pending wash losses."""
        account, fill = account_fill.account, account_fill.fill
        if account not in self._accounts:
            raise ValueError(f"account {account!r} is outside the configured wash-sale domain")
        fill_id = str(fill.fill_id)
        if fill_id in self._fill_ids:
            raise ValueError(f"duplicate fill: {fill_id}")
        if self._last_timestamp is not None and fill.timestamp < self._last_timestamp:
            raise ValueError("tax-lot fills must be applied in chronological order")
        self._fill_ids.add(fill_id)
        self._last_timestamp = fill.timestamp

        if fill.side == OrderSide.BUY:
            self._apply_buy(account, fill)
        else:
            self._apply_sell(account, fill)

    def open_quantity(self, symbol: str, *, account: str | None = None) -> Decimal:
        """Return current long quantity for one symbol, optionally one account."""
        return sum(
            (
                lot.quantity
                for lot in self._lots
                if lot.symbol == symbol and (account is None or lot.account == account)
            ),
            Decimal("0"),
        )

    def finalize(self) -> TaxLotReport:
        """Return immutable records after all future 30-day purchases are known."""
        realizations = tuple(realization.public() for realization in self._realizations)
        lots = tuple(
            lot.public()
            for lot in sorted(
                self._lots,
                key=lambda item: (item.symbol, item.account, item.open_date, item.lot_id),
            )
        )
        return TaxLotReport(realizations=realizations, open_lots=lots)

    def _apply_buy(self, account: str, fill: Fill) -> None:
        opened = fill.timestamp.date()
        basis = (fill.price * fill.quantity + fill.commission) / fill.quantity
        lot = _OpenLot(
            lot_id=str(fill.fill_id),
            symbol=fill.symbol,
            account=account,
            open_date=opened,
            holding_period_start=opened,
            quantity=fill.quantity,
            basis_per_share=basis,
            wash_capacity=fill.quantity,
        )
        self._lots.append(lot)

        pending = sorted(
            (
                realization
                for realization in self._realizations
                if realization.symbol == fill.symbol
                and realization.unmatched_loss_quantity > 0
                and realization.sale_date <= opened <= realization.sale_date + _WASH_WINDOW
            ),
            key=lambda item: (item.sale_date, item.sale_id, item.lot_id),
        )
        for realization in pending:
            if lot.wash_capacity <= 0:
                break
            self._match_replacement(realization, lot)

    def _apply_sell(self, account: str, fill: Fill) -> None:
        available = self.open_quantity(fill.symbol, account=account)
        if fill.quantity > available:
            raise ValueError(
                "short sales are outside the minimal tax-lot ledger: "
                f"sell {fill.quantity} exceeds open {available} for {fill.symbol}"
            )
        sale_date = fill.timestamp.date()
        net_price = (fill.price * fill.quantity - fill.commission) / fill.quantity
        remaining = fill.quantity
        candidates = sorted(
            (
                lot
                for lot in self._lots
                if lot.symbol == fill.symbol and lot.account == account and lot.quantity > 0
            ),
            key=lambda lot: self._selection_key(lot, net_price, sale_date),
        )
        new_realizations: list[_Realization] = []
        for lot in candidates:
            if remaining <= 0:
                break
            quantity = min(remaining, lot.quantity)
            realization = self._close_lot(fill, lot, quantity, net_price, sale_date)
            new_realizations.append(realization)
            self._realizations.append(realization)
            lot.quantity -= quantity
            lot.wash_capacity = min(lot.wash_capacity, lot.quantity)
            remaining -= quantity
        self._lots = [lot for lot in self._lots if lot.quantity > 0]

        # A pre-sale purchase counts only when its shares remain open after this
        # sale. Matching after lot removal prevents the disposed shares from
        # incorrectly replacing themselves.
        for realization in new_realizations:
            if realization.unmatched_loss_quantity <= 0:
                continue
            replacements = sorted(
                (
                    lot
                    for lot in self._lots
                    if lot.symbol == realization.symbol
                    and sale_date - _WASH_WINDOW <= lot.open_date <= sale_date
                    and lot.wash_capacity > 0
                ),
                key=lambda lot: (lot.open_date, lot.lot_id),
            )
            for replacement in replacements:
                if realization.unmatched_loss_quantity <= 0:
                    break
                self._match_replacement(realization, replacement)

    @staticmethod
    def _selection_key(lot: _OpenLot, sale_price: Decimal, sale_date: date) -> tuple:
        is_loss = sale_price < lot.basis_per_share
        is_long_term = (sale_date - lot.holding_period_start).days > 365
        if is_loss:
            priority = 0  # harvest losses first, then HIFO
        elif is_long_term:
            priority = 1  # avoid short-term gains
        else:
            priority = 2
        return (priority, -lot.basis_per_share, lot.open_date, lot.lot_id)

    @staticmethod
    def _close_lot(
        fill: Fill,
        lot: _OpenLot,
        quantity: Decimal,
        net_price: Decimal,
        sale_date: date,
    ) -> _Realization:
        proceeds = net_price * quantity
        basis = lot.basis_per_share * quantity
        pnl = proceeds - basis
        character: TaxCharacter = (
            "long_term" if (sale_date - lot.holding_period_start).days > 365 else "short_term"
        )
        loss_per_share = max(Decimal("0"), -pnl / quantity)
        return _Realization(
            sale_id=str(fill.fill_id),
            lot_id=lot.lot_id,
            symbol=fill.symbol,
            account=lot.account,
            sale_date=sale_date,
            quantity=quantity,
            proceeds=proceeds,
            cost_basis=basis,
            realized_pnl=pnl,
            character=character,
            source_holding_start=lot.holding_period_start,
            loss_per_share=loss_per_share,
            unmatched_loss_quantity=quantity if pnl < 0 else Decimal("0"),
        )

    def _match_replacement(self, realization: _Realization, lot: _OpenLot) -> None:
        quantity = min(realization.unmatched_loss_quantity, lot.wash_capacity)
        if quantity <= 0:
            return
        loss = realization.loss_per_share * quantity
        realization.unmatched_loss_quantity -= quantity
        realization.disallowed_loss += loss

        if quantity == lot.quantity:
            lot.basis_per_share += realization.loss_per_share
            lot.holding_period_start = min(
                lot.holding_period_start,
                realization.source_holding_start,
            )
            lot.wash_capacity = Decimal("0")
            return

        # Keep uniform basis/holding-period records by splitting a partial match.
        lot.quantity -= quantity
        lot.wash_capacity -= quantity
        self._segment += 1
        self._lots.append(
            _OpenLot(
                lot_id=f"{lot.lot_id}:wash{self._segment}",
                symbol=lot.symbol,
                account=lot.account,
                open_date=lot.open_date,
                holding_period_start=min(
                    lot.holding_period_start,
                    realization.source_holding_start,
                ),
                quantity=quantity,
                basis_per_share=lot.basis_per_share + realization.loss_per_share,
                wash_capacity=Decimal("0"),
            )
        )


__all__ = [
    "AccountFill",
    "TaxCharacter",
    "TaxLot",
    "TaxLotLedger",
    "TaxLotReport",
    "TaxRealization",
]
