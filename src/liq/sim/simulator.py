"""Core simulator event loop skeleton."""

from __future__ import annotations

import logging
import random
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from liq.core import Bar, Fill, OrderRequest, PortfolioState

from liq.sim.accounting import AccountState
from liq.sim.brackets import BracketState, create_brackets, process_brackets
from liq.sim.checkpoint import SimulationCheckpoint, create_checkpoint
from liq.sim.config import ProviderConfig, SimulatorConfig
from liq.sim.funding_model import funding_charge, slippage_percentiles
from liq.sim.risk_caps import (
    enforce_equity_floor,
    enforce_frequency_cap,
    enforce_net_position_cap,
    enforce_pyramiding_limit,
)
from liq.sim.constraints import (
    ConstraintViolation,
    check_buying_power,
    check_kill_switch,
    check_margin,
    check_pdt,
    check_position_limit,
    check_short_permission,
)
from liq.sim.execution import match_order
from liq.sim.fx import convert_to_usd
from liq.sim.providers import fee_model_from_config, slippage_model_from_config
from liq.sim.validation import assert_no_lookahead, ensure_order_eligible

logger = logging.getLogger(__name__)


@dataclass
class RejectedOrder:
    """Record of an order rejected due to constraint violation."""

    order: OrderRequest
    reason: str
    timestamp: datetime


@dataclass
class SimulationResult:
    fills: list[Fill]
    portfolio_history: list[Decimal]  # equity per bar (legacy alias)
    equity_curve: list[tuple[datetime, Decimal]]
    portfolio_states: list[PortfolioState]
    slippage_stats: dict[str, float] = field(default_factory=dict)
    funding_charged: Decimal = Decimal("0")
    rejected_orders: list[RejectedOrder] = field(default_factory=list)


@dataclass
class Simulator:
    """Simplified simulator to process orders over bars."""

    provider_config: ProviderConfig
    config: SimulatorConfig = field(default_factory=SimulatorConfig)
    account_state: AccountState = field(
        default_factory=lambda: AccountState(cash=Decimal("0"))
    )
    peak_equity: Decimal = Decimal("0")
    daily_start_equity: Decimal = Decimal("0")
    kill_switch_engaged: bool = False
    current_day: datetime | None = None
    active_brackets: list[BracketState] = field(default_factory=list)
    trades_today: int = 0
    starting_equity: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        self.fee_model = fee_model_from_config(self.provider_config)
        self.slippage_model = slippage_model_from_config(self.provider_config)
        if self.account_state.cash == 0 and self.config.initial_capital:
            self.account_state.cash = self.config.initial_capital
        self.account_state.account_currency = self.provider_config.account_currency
        random.seed(self.config.random_seed)
        # initialize peak/daily to starting equity
        init_equity = self.account_state.cash + self.account_state.unsettled_cash
        self.peak_equity = init_equity
        self.daily_start_equity = init_equity
        self.starting_equity = init_equity
        if self.provider_config.pdt_enabled and self.account_state.day_trades_remaining is None:
            # Simplified PDT counter (3 day trades default)
            self.account_state.day_trades_remaining = 3

    def _mark_in_account_ccy(self, price: Decimal, symbol: str, fx_rates: dict[str, Decimal] | None) -> Decimal:
        """Convert a mark to account currency when possible."""
        if fx_rates and self.account_state.account_currency == "USD":
            pair = symbol.replace("-", "_")
            if "_" not in pair:
                return price
            try:
                return Decimal(convert_to_usd(price, pair, fx_rates))
            except KeyError:
                return price
        return price

    def to_checkpoint(self, backtest_id: str, config_hash: str) -> SimulationCheckpoint:
        """Create a checkpoint snapshot of current simulator state."""
        return create_checkpoint(
            backtest_id=backtest_id,
            config_hash=config_hash,
            provider_config=self.provider_config,
            simulator_config=self.config,
            account_state=self.account_state,
            current_day=self.current_day,
            peak_equity=self.peak_equity,
            daily_start_equity=self.daily_start_equity,
            kill_switch_engaged=self.kill_switch_engaged,
            active_brackets=self.active_brackets,
        )

    @classmethod
    def from_checkpoint(cls, checkpoint: SimulationCheckpoint) -> Simulator:
        """Rehydrate a Simulator from a checkpoint."""
        checkpoint.restore_random_state()
        sim = cls(
            provider_config=checkpoint.provider_config,
            config=checkpoint.simulator_config,
            account_state=checkpoint.account_state,
        )
        sim.current_day = checkpoint.current_day
        sim.peak_equity = checkpoint.peak_equity
        sim.daily_start_equity = checkpoint.daily_start_equity
        sim.kill_switch_engaged = checkpoint.kill_switch_engaged
        sim.active_brackets = checkpoint.active_brackets
        return sim

    def run(
        self,
        orders: Sequence[OrderRequest],
        bars: Sequence[Bar],
        min_delay_bars: int | None = None,
        fx_rates: dict[str, Decimal] | None = None,
        swap_rates: dict[str, Decimal] | None = None,
    ) -> SimulationResult:
        min_delay = min_delay_bars if min_delay_bars is not None else self.config.min_order_delay_bars
        fills: list[Fill] = []
        equity_curve: list[tuple[datetime, Decimal]] = []
        portfolio_states: list[PortfolioState] = []
        rejected_orders: list[RejectedOrder] = []
        funding_total = Decimal("0")
        slippage_samples: list[float] = []

        logger.info(
            "Simulation started",
            extra={
                "order_count": len(orders),
                "bar_count": len(bars),
                "min_delay_bars": min_delay,
                "provider": self.provider_config.name,
                "initial_capital": str(self.config.initial_capital) if self.config.initial_capital else None,
            },
        )

        # Precompute first eligible bar index for each order and sort once (activation by bar index).
        pending: deque[tuple[int, OrderRequest]] = deque()
        for order in orders:
            origin_idx = 0
            for idx, bar in enumerate(bars):
                if bar.timestamp >= order.timestamp:
                    origin_idx = idx
                    break
            pending.append((origin_idx, order))
        pending = deque(sorted(pending, key=lambda x: x[0]))
        active_orders: list[OrderRequest] = []
        became_eligible: dict[int, bool] = {}

        for bar_idx, bar in enumerate(bars):
            # daily reset
            if self.current_day is None or bar.timestamp.date() != self.current_day.date():
                # set daily start to current equity snapshot
                marks = dict.fromkeys(self.account_state.positions.keys(), bar.open)
                snapshot = self.account_state.to_portfolio_state(
                    marks=marks, timestamp=bar.timestamp, fx_rates=fx_rates
                )
                self.daily_start_equity = snapshot.equity
                self.current_day = bar.timestamp
                self.trades_today = 0

            self.account_state.process_settlement(bar.timestamp)
            # apply daily swaps if applicable (for providers with financing)
            if swap_rates:
                marks_for_swaps = dict.fromkeys(self.account_state.positions.keys(), bar.close)
                self.account_state.apply_daily_swap(
                    bar.timestamp, swap_rates=swap_rates, marks=marks_for_swaps, fx_rates=fx_rates
                )
            # funding charges per day when enabled
            if self.config.funding.enabled:
                for symbol, pos in self.account_state.positions.items():
                    if pos.net_quantity == 0:
                        continue
                    mark = bar.close
                    notional = abs(pos.net_quantity * mark)
                    charge = Decimal(str(funding_charge(float(notional), days=1, scenario=self.config.funding.scenario)))
                    if pos.net_quantity > 0:
                        self.account_state.cash -= charge
                        pos.realized_pnl -= charge
                    else:
                        self.account_state.cash += charge
                        pos.realized_pnl += charge
                    funding_total += charge
            # compute equity snapshot at bar open for drawdown/daily loss checks
            marks_open = dict.fromkeys(self.account_state.positions.keys(), bar.open)
            snapshot_open = self.account_state.to_portfolio_state(
                marks=marks_open, timestamp=bar.timestamp, fx_rates=fx_rates
            )
            current_equity = snapshot_open.equity
            if current_equity <= 0:
                # Floor equity at zero to avoid negative equity artifacts
                current_equity = Decimal("0")
                snapshot_open = snapshot_open.model_copy(update={"equity": current_equity})
                # Hard stop: no trading with non-positive equity
                equity_curve.append((bar.timestamp, current_equity))
                portfolio_states.append(snapshot_open)
                logger.warning(
                    "Equity non-positive; halting simulation",
                    extra={"equity": str(current_equity), "timestamp": bar.timestamp.isoformat()},
                )
                break
            # update peak
            if current_equity > self.peak_equity:
                self.peak_equity = current_equity
            # kill-switch checks
            if self.config.max_drawdown_pct is not None:
                if current_equity < self.peak_equity * (Decimal("1") - Decimal(str(self.config.max_drawdown_pct))):
                    self.kill_switch_engaged = True
            if self.config.max_daily_loss_pct is not None:
                if current_equity < self.daily_start_equity * (Decimal("1") - Decimal(str(self.config.max_daily_loss_pct))):
                    self.kill_switch_engaged = True

            # Activate newly eligible orders for this bar
            while pending and pending[0][0] <= bar_idx:
                origin_idx, order = pending[0]
                # honor min_delay by leaving in pending until eligible
                if bar_idx - origin_idx < min_delay:
                    break
                pending.popleft()
                assert_no_lookahead(order.timestamp, bar.timestamp)
                became_eligible[id(order)] = True
                active_orders.append(order)

            executed_orders: list[OrderRequest] = []
            # Mark cache per symbol; portfolio snapshot recomputed per order to reflect intra-bar fills.
            mark_cache: dict[str, Decimal] = {}
            for order in list(active_orders):
                mark_for_constraints = mark_cache.get(order.symbol)
                if mark_for_constraints is None:
                    mark_for_constraints = self._mark_in_account_ccy(bar.open, order.symbol, fx_rates)
                    mark_cache[order.symbol] = mark_for_constraints
                # Fresh snapshot using current account state (after any earlier fills this bar)
                pre_marks = dict.fromkeys(self.account_state.positions.keys(), bar.open)
                portfolio_snapshot = self.account_state.to_portfolio_state(
                    marks=pre_marks, timestamp=bar.timestamp, fx_rates=fx_rates
                )
                # Risk caps: net exposure, equity floor, frequency, pyramiding
                net_exposure = sum(
                    (abs(p.market_value) for p in portfolio_snapshot.positions.values()), Decimal("0")
                )
                if not enforce_net_position_cap(
                    net_exposure, portfolio_snapshot.equity, self.config.risk_caps.net_position_cap_pct
                ):
                    rejected_orders.append(RejectedOrder(order=order, reason="Net position cap", timestamp=bar.timestamp))
                    continue
                if not enforce_equity_floor(
                    portfolio_snapshot.equity, self.config.risk_caps.equity_floor_pct, self.starting_equity
                ):
                    rejected_orders.append(RejectedOrder(order=order, reason="Equity floor breached", timestamp=bar.timestamp))
                    continue
                if not enforce_frequency_cap(self.trades_today, self.config.risk_caps.frequency_cap_per_day):
                    rejected_orders.append(RejectedOrder(order=order, reason="Frequency cap reached", timestamp=bar.timestamp))
                    continue
                if not enforce_pyramiding_limit(
                    current_layers=1, max_layers=self.config.risk_caps.pyramiding_layers
                ):
                    rejected_orders.append(RejectedOrder(order=order, reason="Pyramiding cap", timestamp=bar.timestamp))
                    continue
                # Kill-switch: block exposure-increasing (buys) when engaged
                try:
                    check_kill_switch(self.kill_switch_engaged, order)
                except ConstraintViolation as e:
                    rejected_orders.append(RejectedOrder(
                        order=order,
                        reason=e.message,
                        timestamp=bar.timestamp,
                    ))
                    logger.debug(
                        "Order rejected: kill-switch engaged",
                        extra={
                            "order_id": str(order.client_order_id),
                            "symbol": order.symbol,
                            "reason": e.message,
                        },
                    )
                    continue
                # PDT: detect if this order would be a day trade (flat after trade same day)
                is_day_trade = False
                pre_pos = self.account_state.positions.get(order.symbol)
                pre_qty = pre_pos.net_quantity if pre_pos else Decimal("0")
                if order.timestamp.date() == bar.timestamp.date():
                    if pre_qty > 0 and str(order.side).lower().endswith("sell"):
                        is_day_trade = (pre_qty - order.quantity) <= 0
                    elif pre_qty < 0 and str(order.side).lower().endswith("buy"):
                        is_day_trade = (pre_qty + order.quantity) >= 0
                try:
                    check_position_limit(
                        order,
                        portfolio_snapshot,
                        max_position_pct=self.config.max_position_pct,
                        mark_price=mark_for_constraints,
                    )
                    check_buying_power(order, portfolio_snapshot, mark_price=mark_for_constraints)
                    check_margin(
                        order,
                        portfolio_snapshot,
                        mark_price=mark_for_constraints,
                        initial_margin_rate=self.provider_config.initial_margin_rate,
                    )
                    from liq.sim.constraints import check_gross_leverage

                    check_gross_leverage(
                        order,
                        portfolio_snapshot,
                        mark_price=mark_for_constraints,
                        max_gross_leverage=self.config.max_gross_leverage,
                    )
                    check_short_permission(
                        order,
                        portfolio_snapshot,
                        short_enabled=self.provider_config.short_enabled,
                        locate_required=self.provider_config.locate_required,
                    )
                    check_pdt(portfolio_snapshot, is_day_trade=is_day_trade)
                except ConstraintViolation as e:
                    rejected_orders.append(RejectedOrder(
                        order=order,
                        reason=e.message,
                        timestamp=bar.timestamp,
                    ))
                    logger.debug(
                        "Order rejected: constraint violation",
                        extra={
                            "order_id": str(order.client_order_id),
                            "symbol": order.symbol,
                            "side": str(order.side),
                            "quantity": str(order.quantity),
                            "reason": e.message,
                        },
                    )
                    continue

                slippage = self.slippage_model.calculate(order, bar)
                # naive maker/taker heuristic: limits with price away from open are maker
                is_maker = order.order_type.name == "LIMIT" and (
                    (order.side.value == "buy" and order.limit_price and order.limit_price < bar.open)
                    or (order.side.value == "sell" and order.limit_price and order.limit_price > bar.open)
                )
                fill = match_order(
                    order,
                    bar,
                    slippage=slippage,
                    commission=self.fee_model.calculate(order, bar.open, is_maker=is_maker),
                    provider=self.provider_config.name,
                    timestamp=bar.timestamp,
                )
                if fill:
                    slippage_samples.append(float(slippage))
                    executed_orders.append(order)
                    if is_day_trade and self.account_state.day_trades_remaining is not None:
                        self.account_state.day_trades_remaining = max(
                            0, self.account_state.day_trades_remaining - 1
                        )
                    self.trades_today += 1
                    realized = self.account_state.apply_fill(
                        fill,
                        settlement_days=self.provider_config.settlement_days,
                        borrow_rate_annual=self.provider_config.borrow_rate_annual,
                        fx_rates=fx_rates,
                    )
                    fills.append(fill.model_copy(update={"realized_pnl": realized}))
                    logger.debug(
                        "Order filled",
                        extra={
                            "order_id": str(order.client_order_id),
                            "symbol": fill.symbol,
                            "side": fill.side.value,
                            "quantity": str(fill.quantity),
                            "price": str(fill.price),
                            "commission": str(fill.commission),
                            "realized_pnl": str(realized),
                        },
                    )
                    bracket = create_brackets(fill.price, order)
                    if bracket.stop_loss or bracket.take_profit:
                        self.active_brackets.append(bracket)

            # remove executed
            active_orders = [o for o in active_orders if o not in executed_orders]

            # process active brackets (eligible starting next bar)
            remaining_brackets: list[BracketState] = []
            for bracket in self.active_brackets:
                trigger, _ = process_brackets(bracket, bar_high=bar.high, bar_low=bar.low)
                if trigger:
                    trigger_type = "stop_loss" if trigger == bracket.stop_loss else "take_profit"
                    logger.debug(
                        "Bracket triggered",
                        extra={
                            "parent_id": bracket.parent_id,
                            "trigger_type": trigger_type,
                            "symbol": trigger.symbol,
                            "side": trigger.side.value,
                            "bar_high": str(bar.high),
                            "bar_low": str(bar.low),
                        },
                    )
                    slippage = self.slippage_model.calculate(trigger, bar)
                    fill = match_order(
                        trigger,
                        bar,
                        slippage=slippage,
                        commission=self.fee_model.calculate(trigger, bar.open, is_maker=False),
                        provider=self.provider_config.name,
                        timestamp=bar.timestamp,
                    )
                    if fill:
                        realized = self.account_state.apply_fill(
                            fill,
                            settlement_days=self.provider_config.settlement_days,
                            borrow_rate_annual=self.provider_config.borrow_rate_annual,
                            fx_rates=fx_rates,
                        )
                        fills.append(fill.model_copy(update={"realized_pnl": realized}))
                        slippage_samples.append(float(slippage))
                        self.trades_today += 1
                else:
                    remaining_brackets.append(bracket)
            self.active_brackets = remaining_brackets
            # DAY orders expire at bar close only after they've been eligible once
            if active_orders:
                active_orders = [
                    o
                    for o in active_orders
                    if not (
                        o.time_in_force.name == "DAY"
                        and o not in executed_orders
                        and became_eligible.get(id(o), False)
                    )
                ]
            # record equity (cash + unsettled + mark to bar close for now)
            marks = dict.fromkeys(self.account_state.positions.keys(), bar.close)
            portfolio = self.account_state.to_portfolio_state(marks=marks, timestamp=bar.timestamp, fx_rates=fx_rates)
            equity_curve.append((bar.timestamp, portfolio.equity))
            portfolio_states.append(portfolio)

        portfolio_history = [eq for _, eq in equity_curve]

        final_equity = equity_curve[-1][1] if equity_curve else Decimal("0")
        logger.info(
            "Simulation completed",
            extra={
                "fill_count": len(fills),
                "rejected_count": len(rejected_orders),
                "final_equity": str(final_equity),
                "bar_count_processed": len(bars),
            },
        )
        return SimulationResult(
            fills=fills,
            portfolio_history=portfolio_history,
            equity_curve=equity_curve,
            portfolio_states=portfolio_states,
            slippage_stats=slippage_percentiles(slippage_samples, self.config.slippage_reporting.percentiles),
            funding_charged=funding_total,
            rejected_orders=rejected_orders,
        )

    def _aggregate_bars(self, bars: Sequence[Bar], window_minutes: int) -> list[Bar]:  # pragma: no cover (optional guarded mode)
        """Aggregate bars into larger windows (e.g., 5m) for simulation."""
        aggregated: list[Bar] = []
        window_seconds = window_minutes * 60
        start_idx = 0
        while start_idx < len(bars):
            start_bar = bars[start_idx]
            window_end_ts = start_bar.timestamp.timestamp() + window_seconds
            window_bars: list[Bar] = []
            idx = start_idx
            while idx < len(bars) and bars[idx].timestamp.timestamp() < window_end_ts:
                window_bars.append(bars[idx])
                idx += 1
            if not window_bars:
                break
            aggregated.append(
                Bar(
                    symbol=window_bars[0].symbol,
                    timestamp=window_bars[-1].timestamp,
                    open=window_bars[0].open,
                    high=max(b.high for b in window_bars),
                    low=min(b.low for b in window_bars),
                    close=window_bars[-1].close,
                    volume=sum(b.volume for b in window_bars),
                )
            )
            start_idx = idx
        return aggregated

    def _intra_bar_feasible(self, order: OrderRequest, agg_bar: Bar, original_bars: Sequence[Bar]) -> bool:  # pragma: no cover
        """Check if an order could have filled within the aggregated bar using underlying 1m bars."""
        # Identify window of original bars that make up this aggregated bar.
        window: list[Bar] = []
        if len(original_bars) < 2:
            return True
        # infer base delta from data spacing
        base_delta = original_bars[1].timestamp - original_bars[0].timestamp
        window_start = agg_bar.timestamp - base_delta * 5
        for b in original_bars:
            if window_start <= b.timestamp <= agg_bar.timestamp:
                window.append(b)
        if not window:
            return True

        # Simple feasibility: did price cross the trigger side within the window?
        if order.side.value == "buy":
            # For stop/limit BUY, require high to reach trigger; for market we assume fill possible.
            if order.order_type.name in {"STOP", "STOP_LIMIT"} and order.stop_price is not None:
                return any(b.high >= order.stop_price for b in window)
            return any(True for _ in window)
        if order.side.value == "sell":
            if order.order_type.name in {"STOP", "STOP_LIMIT"} and order.stop_price is not None:
                return any(b.low <= order.stop_price for b in window)
            return any(True for _ in window)
        return True


def ensure_eligible(order_idx: int, current_idx: int, min_delay: int) -> bool:
    """Helper to wrap ensure_order_eligible raising into bool."""
    try:
        ensure_order_eligible(order_bar_index=order_idx, current_bar_index=current_idx, min_delay_bars=min_delay)
        return True
    except Exception:
        return False
