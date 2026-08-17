"""Regression coverage for tools/paper_trade_attribution.py.

This tool now drives real research conclusions (did rebalancing help or
hurt relative to buy-hold), so its arithmetic gets the same test rigor as
the accounting guard it builds on -- particularly the active-return
decomposition, which had a real bug (an incomplete formula produced a
nonzero "residual" on every real session before this was caught and fixed).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import paper_session as ps

_TOOL_PATH = Path(__file__).resolve().parents[2] / "tools" / "paper_trade_attribution.py"
_spec = importlib.util.spec_from_file_location("paper_trade_attribution", _TOOL_PATH)
pta = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(pta)


def _build_two_symbol_session(tmp_path, monkeypatch, *, rebalance_prices=None):
    """A tiny, fully deterministic 2-symbol session: enter equal-weight,
    then force one rebalance at known prices, so every downstream number is
    hand-verifiable."""
    symbols = ["AAA-USDT", "BBB-USDT"]
    entry_prices = {"AAA-USDT": 10.0, "BBB-USDT": 10.0}
    monkeypatch.setattr(ps, "fetch_last_prices", lambda s: {sym: entry_prices[sym] for sym in s})
    session_dir = tmp_path / "test_session"
    ps.start_session(
        session_dir, symbols, initial_cash=100.0, rebalance_interval_hours=1.0, fee_rate=0.01,
    )
    if rebalance_prices:
        ps.rebalance_if_due(session_dir, force=True, prices=rebalance_prices, now="2026-01-01T01:00:00+00:00")
    return session_dir


def test_buy_hold_nav_starts_equal_to_entry_equity(tmp_path, monkeypatch) -> None:
    session_dir = _build_two_symbol_session(tmp_path, monkeypatch)
    data = pta.load_session_data(session_dir)
    curve = pta.build_equity_comparison(data)
    assert curve[0]["strategy_nav"] == pytest.approx(curve[0]["buy_hold_nav"])
    assert curve[0]["cash_nav"] == pytest.approx(100.0)


def test_buy_hold_nav_diverges_only_after_rebalance(tmp_path, monkeypatch) -> None:
    # AAA doubles, BBB halves -- a real rebalance will sell AAA/buy BBB,
    # which a static buy-hold never does.
    session_dir = _build_two_symbol_session(
        tmp_path, monkeypatch, rebalance_prices={"AAA-USDT": 20.0, "BBB-USDT": 5.0},
    )
    data = pta.load_session_data(session_dir)
    curve = pta.build_equity_comparison(data)
    # Equal-dollar-weighted buy-hold of +100%/-50% legs nets to the average
    # of the two returns: (1.0 + -0.5) / 2 = +25% on the original $99.01
    # invested (post entry-fee) -- an exact, hand-computable number.
    assert curve[-1]["buy_hold_nav"] == pytest.approx(curve[0]["buy_hold_nav"] * 1.25, abs=1e-6)
    # The strategy, having rebalanced, must differ from its own buy-hold twin.
    assert curve[-1]["strategy_nav"] != pytest.approx(curve[-1]["buy_hold_nav"])


def test_active_return_decomposition_identity_holds(tmp_path, monkeypatch) -> None:
    """realized_alpha + unrealized_drift - turnover_drag must equal
    active_return_dollars exactly (by construction) -- this is the identity
    whose omitted unrealized_drift term produced a spurious nonzero
    "residual" on every real session before the fix."""
    session_dir = _build_two_symbol_session(
        tmp_path, monkeypatch, rebalance_prices={"AAA-USDT": 15.0, "BBB-USDT": 8.0},
    )
    data = pta.load_session_data(session_dir)
    rows = pta.build_trade_attribution(data)
    curve = pta.build_equity_comparison(data)
    attribution = pta.benchmark_attribution(data, rows, curve)

    decomp = attribution["active_return_decomposition"]
    reconstructed = (
        decomp["realized_alpha_from_closed_trades"]
        + decomp["unrealized_allocation_drift"]
        - decomp["turnover_drag"]
    )
    assert reconstructed == pytest.approx(attribution["active_return_dollars"], abs=1e-9)


def test_ledger_integrity_check_passes_on_a_healthy_session(tmp_path, monkeypatch) -> None:
    session_dir = _build_two_symbol_session(
        tmp_path, monkeypatch, rebalance_prices={"AAA-USDT": 12.0, "BBB-USDT": 9.0},
    )
    data = pta.load_session_data(session_dir)
    rows = pta.build_trade_attribution(data)
    curve = pta.build_equity_comparison(data)
    attribution = pta.benchmark_attribution(data, rows, curve)

    check = attribution["ledger_integrity_check"]
    assert check["within_tolerance"] is True
    assert check["residual"] == pytest.approx(0.0, abs=1e-6)


def test_ledger_integrity_check_flags_a_tampered_book(tmp_path, monkeypatch) -> None:
    """A book.json cash_remaining that disagrees with what trades.jsonl
    implies must be flagged, not silently accepted -- this is the one
    genuinely independent check in the tool."""
    session_dir = _build_two_symbol_session(
        tmp_path, monkeypatch, rebalance_prices={"AAA-USDT": 12.0, "BBB-USDT": 9.0},
    )
    book = ps._load_book(session_dir)
    book["cash_remaining"] = float(book["cash_remaining"]) + 5.0  # corrupt it
    (session_dir / "book.json").write_text(__import__("json").dumps(book), encoding="utf-8")

    data = pta.load_session_data(session_dir)
    rows = pta.build_trade_attribution(data)
    curve = pta.build_equity_comparison(data)
    attribution = pta.benchmark_attribution(data, rows, curve)

    check = attribution["ledger_integrity_check"]
    assert check["within_tolerance"] is False
    assert check["residual"] == pytest.approx(-5.0, abs=1e-6)


def test_interpretation_labels_match_the_sign_of_active_return(tmp_path, monkeypatch) -> None:
    # A no-op "rebalance" (force=True but prices unchanged) should be
    # classified as contributing little.
    session_dir = _build_two_symbol_session(
        tmp_path, monkeypatch, rebalance_prices={"AAA-USDT": 10.0, "BBB-USDT": 10.0},
    )
    data = pta.load_session_data(session_dir)
    rows = pta.build_trade_attribution(data)
    curve = pta.build_equity_comparison(data)
    attribution = pta.benchmark_attribution(data, rows, curve)
    assert attribution["interpretation"] == "rebalancing_contributed_little"
