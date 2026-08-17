"""Canonical Decimal-based futures accounting kernel.

Single source of truth for every cash/margin mutation a paper futures
position can undergo. Built in response to a forensic audit of
paper_sessions/funding_live that found `_check_risk_exits`-triggered closes
(trailing_stop, max_hold_expired) applied a *different* cash-settlement
formula than signal-driven closes (funding_z_exit) -- entries spent full
notional (spot-style), but those particular exits only credited the P&L
delta, silently leaking or fabricating cash on every such exit. See
docs/forensics/funding_live_audit.md (or the audit conversation) for the
exact trade-by-trade reconciliation.

Futures reserve margin; they do not perform spot-style sale-proceeds
accounting. The invariant this module enforces on every mutation:

    open:  wallet_after - wallet_before == -entry_fee
    close: wallet_after - wallet_before == gross_pnl - exit_fee + funding_cashflow

All amounts are Decimal, constructed from str/int -- never from float, since
Decimal(some_float) preserves the float's binary-approximation error rather
than the intended decimal value.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from enum import Enum
from typing import Final, Optional, Union

DECIMAL_CONTEXT: Final = Context(prec=50, rounding=ROUND_HALF_EVEN)

CASH_QUANTUM: Final = Decimal("0.00000001")
ZERO: Final = Decimal("0")


def dec(value: Union[Decimal, str, int]) -> Decimal:
    """Convert exact application values to Decimal.

    Floats are rejected: Decimal(float_value) preserves the float's binary
    approximation rather than the intended decimal value.
    """
    if isinstance(value, bool):
        raise TypeError("Boolean is not a valid financial amount")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (str, int)):
        return Decimal(value)
    raise TypeError(f"Financial values must be Decimal, str, or int; got {type(value).__name__}")


def money(value: Union[Decimal, str, int]) -> Decimal:
    with localcontext(DECIMAL_CONTEXT):
        return dec(value).quantize(CASH_QUANTUM)


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"

    @property
    def sign(self) -> Decimal:
        return Decimal("1") if self is Side.LONG else Decimal("-1")


@dataclass(frozen=True)
class Account:
    available_cash: Decimal
    reserved_margin: Decimal
    realized_pnl: Decimal = ZERO
    fees_paid: Decimal = ZERO
    funding_net: Decimal = ZERO

    @property
    def wallet_balance(self) -> Decimal:
        return money(self.available_cash + self.reserved_margin)


@dataclass(frozen=True)
class Position:
    position_id: str
    symbol: str
    side: Side
    quantity: Decimal
    entry_price: Decimal
    leverage: Decimal
    margin_reserved: Decimal
    accrued_funding: Decimal = ZERO


@dataclass(frozen=True)
class OpenResult:
    account: Account
    position: Position
    entry_notional: Decimal
    entry_fee: Decimal


@dataclass(frozen=True)
class CloseResult:
    account: Account
    remaining_position: Optional[Position]
    closed_quantity: Decimal
    exit_notional: Decimal
    released_margin: Decimal
    gross_pnl: Decimal
    exit_fee: Decimal
    funding_cashflow: Decimal
    net_pnl: Decimal


class AccountingInvariantError(RuntimeError):
    pass


def open_position(
    *,
    account: Account,
    position_id: str,
    symbol: str,
    side: Side,
    quantity: Union[Decimal, str, int],
    execution_price: Union[Decimal, str, int],
    leverage: Union[Decimal, str, int],
    fee_rate: Union[Decimal, str, int],
) -> OpenResult:
    with localcontext(DECIMAL_CONTEXT):
        q = dec(quantity)
        price = dec(execution_price)
        lev = dec(leverage)
        rate = dec(fee_rate)

        if q <= ZERO:
            raise ValueError("quantity must be positive")
        if price <= ZERO:
            raise ValueError("execution_price must be positive")
        if lev < Decimal("1"):
            raise ValueError("leverage must be at least 1")
        if rate < ZERO:
            raise ValueError("fee_rate cannot be negative")

        entry_notional = money(q * price)
        initial_margin = money(entry_notional / lev)
        entry_fee = money(entry_notional * rate)
        required_cash = money(initial_margin + entry_fee)

        if account.available_cash < required_cash:
            raise ValueError(
                f"insufficient available cash: need {required_cash}, have {account.available_cash}"
            )

        before_wallet = account.wallet_balance

        new_account = replace(
            account,
            available_cash=money(account.available_cash - required_cash),
            reserved_margin=money(account.reserved_margin + initial_margin),
            fees_paid=money(account.fees_paid + entry_fee),
        )

        wallet_delta = money(new_account.wallet_balance - before_wallet)
        expected_delta = money(-entry_fee)
        if wallet_delta != expected_delta:
            raise AccountingInvariantError(
                f"open wallet conservation failed: actual={wallet_delta}, expected={expected_delta}"
            )

        position = Position(
            position_id=position_id,
            symbol=symbol,
            side=side,
            quantity=q,
            entry_price=price,
            leverage=lev,
            margin_reserved=initial_margin,
        )

        return OpenResult(
            account=new_account,
            position=position,
            entry_notional=entry_notional,
            entry_fee=entry_fee,
        )


def close_position(
    *,
    account: Account,
    position: Position,
    close_quantity: Union[Decimal, str, int],
    execution_price: Union[Decimal, str, int],
    fee_rate: Union[Decimal, str, int],
) -> CloseResult:
    """Canonical settlement path for every close reason.

    TP, SL, trailing-stop, max-hold, signal exit, liquidation, and manual
    paper close must all call this function -- the exact bug this module
    fixes was two different closing formulas depending on which code path
    triggered the exit.
    """
    with localcontext(DECIMAL_CONTEXT):
        q = dec(close_quantity)
        exit_price = dec(execution_price)
        rate = dec(fee_rate)

        if q <= ZERO:
            raise ValueError("close_quantity must be positive")
        if q > position.quantity:
            raise ValueError("close_quantity exceeds open quantity")
        if exit_price <= ZERO:
            raise ValueError("execution_price must be positive")
        if rate < ZERO:
            raise ValueError("fee_rate cannot be negative")

        full_close = q == position.quantity
        ratio = q / position.quantity

        released_margin = position.margin_reserved if full_close else money(position.margin_reserved * ratio)
        funding_cashflow = position.accrued_funding if full_close else money(position.accrued_funding * ratio)

        gross_pnl = money(position.side.sign * q * (exit_price - position.entry_price))
        exit_notional = money(q * exit_price)
        exit_fee = money(exit_notional * rate)

        available_credit = money(released_margin + gross_pnl - exit_fee + funding_cashflow)

        before_wallet = account.wallet_balance

        new_account = replace(
            account,
            available_cash=money(account.available_cash + available_credit),
            reserved_margin=money(account.reserved_margin - released_margin),
            realized_pnl=money(account.realized_pnl + gross_pnl),
            fees_paid=money(account.fees_paid + exit_fee),
            funding_net=money(account.funding_net + funding_cashflow),
        )

        expected_wallet_delta = money(gross_pnl - exit_fee + funding_cashflow)
        actual_wallet_delta = money(new_account.wallet_balance - before_wallet)
        if actual_wallet_delta != expected_wallet_delta:
            raise AccountingInvariantError(
                f"close wallet conservation failed: actual={actual_wallet_delta}, expected={expected_wallet_delta}"
            )

        if new_account.reserved_margin < ZERO:
            raise AccountingInvariantError(f"negative reserved margin: {new_account.reserved_margin}")

        if full_close:
            remaining_position = None
        else:
            remaining_position = replace(
                position,
                quantity=position.quantity - q,
                margin_reserved=money(position.margin_reserved - released_margin),
                accrued_funding=money(position.accrued_funding - funding_cashflow),
            )

        return CloseResult(
            account=new_account,
            remaining_position=remaining_position,
            closed_quantity=q,
            exit_notional=exit_notional,
            released_margin=released_margin,
            gross_pnl=gross_pnl,
            exit_fee=exit_fee,
            funding_cashflow=funding_cashflow,
            net_pnl=money(gross_pnl - exit_fee + funding_cashflow),
        )


def apply_slippage(
    *,
    mark_price: Union[Decimal, str, int],
    action: str,
    slippage_bps: Union[Decimal, str, int],
) -> tuple[Decimal, Decimal]:
    """Slippage modifies execution price before fees/P&L are computed.

    Returns (execution_price, slippage_cost) -- slippage_cost is the
    per-unit price impact, not a total cash amount, so callers can report
    it alongside notional in an audit trail.
    """
    if action not in {"buy", "sell"}:
        raise ValueError("action must be buy or sell")
    with localcontext(DECIMAL_CONTEXT):
        price = dec(mark_price)
        bps = dec(slippage_bps)
        fraction = bps / Decimal("10000")
        execution_price = money(price * (Decimal("1") + fraction) if action == "buy" else price * (Decimal("1") - fraction))
        slippage_cost = money(execution_price - price) if action == "buy" else money(price - execution_price)
        return execution_price, slippage_cost


def settle_funding(
    *,
    account: Account,
    position: Position,
    mark_price: Union[Decimal, str, int],
    funding_rate: Union[Decimal, str, int],
) -> tuple[Account, Position, Decimal]:
    """funding_cashflow = -signed_quantity * mark_price * funding_rate.

    Positive funding: longs pay, shorts receive. Negative funding: shorts
    pay, longs receive.
    """
    with localcontext(DECIMAL_CONTEXT):
        mark = dec(mark_price)
        rate = dec(funding_rate)
        signed_quantity = position.side.sign * position.quantity
        cashflow = money(-signed_quantity * mark * rate)

        updated_account = replace(
            account,
            available_cash=money(account.available_cash + cashflow),
            funding_net=money(account.funding_net + cashflow),
        )
        updated_position = replace(
            position,
            accrued_funding=money(position.accrued_funding + cashflow),
        )
        return updated_account, updated_position, cashflow


def assert_account_invariants(account: Account, positions: list[Position]) -> None:
    expected_reserved = money(sum((p.margin_reserved for p in positions), ZERO))
    if account.reserved_margin != expected_reserved:
        raise AccountingInvariantError(
            f"reserved-margin mismatch: account={account.reserved_margin}, positions={expected_reserved}"
        )
    if account.available_cash < ZERO:
        raise AccountingInvariantError(f"negative available cash: {account.available_cash}")
    if account.reserved_margin < ZERO:
        raise AccountingInvariantError(f"negative reserved margin: {account.reserved_margin}")
