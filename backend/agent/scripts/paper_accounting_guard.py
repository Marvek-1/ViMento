"""Fail-closed valuation and accounting guards for paper trading.

This module is dependency-free so it can be unit-tested without importing
ccxt, the API server, or the mutable paper-session runtime.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isclose, isfinite
from typing import Any, Literal, Mapping, Sequence


AccountingState = Literal["OK", "DEFERRED", "ERROR"]


class PriceSnapshotError(RuntimeError):
    """Raised before ledger mutation when a mark snapshot is incomplete."""

    def __init__(
        self,
        *,
        missing_symbols: Sequence[str] = (),
        invalid_symbols: Sequence[str] = (),
    ) -> None:
        self.missing_symbols = tuple(sorted(set(missing_symbols)))
        self.invalid_symbols = tuple(sorted(set(invalid_symbols)))
        details: list[str] = []
        if self.missing_symbols:
            details.append(f"missing={list(self.missing_symbols)}")
        if self.invalid_symbols:
            details.append(f"invalid={list(self.invalid_symbols)}")
        super().__init__("incomplete price snapshot: " + ", ".join(details))


@dataclass(frozen=True)
class AccountingDecision:
    state: AccountingState
    reason: str
    residual: float | None
    tolerance: float | None
    stale_mark_symbols: tuple[str, ...] = ()
    position_differences: dict[str, dict[str, float]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_price_snapshot(
    symbols: Sequence[str],
    prices: Mapping[str, Any],
) -> dict[str, float]:
    """Return finite, strictly positive prices for every configured symbol.

    Extra prices are ignored. Missing, non-numeric, NaN, infinite, zero, and
    negative values all fail before any position, cash, trade, or mark mutation.
    """
    missing: list[str] = []
    invalid: list[str] = []
    normalized: dict[str, float] = {}

    for symbol in symbols:
        if symbol not in prices:
            missing.append(symbol)
            continue
        value = prices[symbol]
        if isinstance(value, bool):
            invalid.append(symbol)
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            invalid.append(symbol)
            continue
        if not isfinite(numeric) or numeric <= 0.0:
            invalid.append(symbol)
            continue
        normalized[symbol] = numeric

    if missing or invalid:
        raise PriceSnapshotError(
            missing_symbols=missing,
            invalid_symbols=invalid,
        )
    return normalized


def position_ledger_differences(
    book_positions: Mapping[str, Any],
    by_symbol: Mapping[str, Mapping[str, Any]],
    *,
    abs_tolerance: float = 1e-12,
    rel_tolerance: float = 1e-9,
) -> dict[str, dict[str, float]]:
    """Compare mutable book quantities with quantities reconstructed from trades."""
    symbols = set(book_positions) | set(by_symbol)
    differences: dict[str, dict[str, float]] = {}

    for symbol in sorted(symbols):
        book_qty = float(book_positions.get(symbol, 0.0) or 0.0)
        trade_qty = float(by_symbol.get(symbol, {}).get("open_qty", 0.0) or 0.0)
        if not isclose(
            book_qty,
            trade_qty,
            abs_tol=abs_tolerance,
            rel_tol=rel_tolerance,
        ):
            differences[symbol] = {
                "book_qty": book_qty,
                "trade_qty": trade_qty,
                "difference": book_qty - trade_qty,
            }
    return differences


def assess_accounting(
    *,
    configured_symbols: Sequence[str],
    initial_cash: float,
    equity: float,
    realized_pnl: float,
    unrealized_pnl: float | None,
    stale_mark_symbols: Sequence[str] = (),
    position_differences: Mapping[str, Mapping[str, float]] | None = None,
    abs_tolerance: float = 1e-6,
    rel_tolerance: float = 1e-9,
) -> AccountingDecision:
    """Classify an accounting check as valid, indeterminate, or corrupted.

    DEFERRED means the valuation evidence is incomplete. It must not freeze a
    session. ERROR is reserved for a fully-valued numerical violation or a
    deterministic ledger/configuration mismatch.
    """
    configured = set(configured_symbols)
    stale = tuple(sorted(set(stale_mark_symbols)))
    diffs = dict(position_differences or {})

    if diffs:
        return AccountingDecision(
            state="ERROR",
            reason="POSITION_LEDGER_MISMATCH",
            residual=None,
            tolerance=None,
            stale_mark_symbols=stale,
            position_differences=diffs,
        )

    unconfigured_stale = tuple(symbol for symbol in stale if symbol not in configured)
    if unconfigured_stale:
        return AccountingDecision(
            state="ERROR",
            reason="LEDGER_SYMBOL_MISMATCH",
            residual=None,
            tolerance=None,
            stale_mark_symbols=unconfigured_stale,
        )

    if stale:
        return AccountingDecision(
            state="DEFERRED",
            reason="INCOMPLETE_PRICE_SNAPSHOT",
            residual=None,
            tolerance=None,
            stale_mark_symbols=stale,
        )

    if unrealized_pnl is None:
        return AccountingDecision(
            state="DEFERRED",
            reason="UNAVAILABLE_UNREALIZED_PNL",
            residual=None,
            tolerance=None,
        )

    values = (initial_cash, equity, realized_pnl, unrealized_pnl)
    if not all(isfinite(float(value)) for value in values):
        return AccountingDecision(
            state="ERROR",
            reason="NON_FINITE_ACCOUNTING_VALUE",
            residual=None,
            tolerance=None,
        )

    residual = float(equity) - (
        float(initial_cash) + float(realized_pnl) + float(unrealized_pnl)
    )
    tolerance = max(float(abs_tolerance), abs(float(equity)) * float(rel_tolerance))

    if abs(residual) <= tolerance:
        return AccountingDecision(
            state="OK",
            reason="RECONCILED",
            residual=residual,
            tolerance=tolerance,
        )

    return AccountingDecision(
        state="ERROR",
        reason="SELF_FINANCING_RESIDUAL",
        residual=residual,
        tolerance=tolerance,
    )
