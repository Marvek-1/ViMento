"""Engine-level regression coverage for the paper_session.py <-> ledger wiring.

Reproduces the two audited funding_live failures directly:
  - DOGE-USDT, trailing_stop exit (book.json cash lagged expected by
    -$200.06 -- margin was never released because it was never reserved).
  - BTC-USDT, max_hold_expired exit (book.json cash jumped +$603.55 ahead
    of expected for the same underlying reason).

Both are now impossible by construction: _check_risk_exits only detects,
_execute_close_intent is the only code path that settles cash, and it's
backed by accounting.futures_ledger's invariant-checked Decimal kernel.
"""

from __future__ import annotations

import copy

import pytest

import paper_session
from paper_session import CloseIntent, LedgerSide


def _session(fee_rate=0.0005, slippage_rate=0.0003, leverage=2.0) -> dict:
    return {
        "symbols": ["DOGE-USDT", "BTC-USDT"],
        "fee_rate": fee_rate,
        "slippage_rate": slippage_rate,
        "risk_config": {
            "leverage": leverage,
            "margin_mode": "isolated",
            "take_profit_pct": 0.05,
            "stop_loss_pct": 0.03,
            "trailing_stop_pct": 0.02,
            "max_hold_hours": 48.0,
        },
    }


def _book_with_open_position(symbol: str, *, qty: float, entry_price: float, margin: float, leverage: float, direction: int, entry_time: str) -> dict:
    return {
        "positions": {symbol: qty if direction > 0 else -qty},
        "cash_remaining": 10000.0 - margin,
        "reserved_margin": margin,
        "last_rebalance_time": entry_time,
        "position_metadata": {
            symbol: paper_session._init_position_metadata(
                symbol, qty, entry_price, entry_time,
                direction=direction, leverage=leverage, margin_mode="isolated",
                liquidation_buffer_pct=0.10, margin=margin,
            )
        },
    }


# ── audited regressions ────────────────────────────────────────────────


def test_doge_trailing_stop_audited_regression(tmp_path):
    """paper_sessions/funding_live trade #5: DOGE-USDT SELL, trailing_stop.
    Entry notional ~$200.06 at leverage 2 -> margin ~$100.03. The bug
    credited only net_pnl on this exit, silently losing the ~$100 margin.
    The fixed executor must release margin + net_pnl, exactly like every
    other close reason.
    """
    session = _session(leverage=2.0)
    entry_price = 0.06948083799999999
    qty = 2879.355024474518
    margin = (qty * entry_price) / 2.0  # leverage 2
    book = _book_with_open_position(
        "DOGE-USDT", qty=qty, entry_price=entry_price, margin=margin,
        leverage=2.0, direction=1, entry_time="2026-07-23T21:53:12.859375+00:00",
    )
    cash_before = book["cash_remaining"]

    intent = CloseIntent(symbol="DOGE-USDT", quantity=qty, reason="trailing_stop", mark_price=0.0686)
    trade = paper_session._execute_close_intent(session, book, tmp_path, intent, "2026-07-24T13:05:55.763076+00:00")

    # Margin must be released -- this is exactly the ~$200 that vanished
    # in the audited bug.
    assert trade["margin"] == pytest.approx(margin, rel=1e-6)
    assert book["cash_remaining"] == pytest.approx(cash_before + margin + trade["net_pnl"], rel=1e-9)
    assert book["reserved_margin"] == pytest.approx(0.0, abs=1e-6)
    assert "DOGE-USDT" not in book["positions"]


def test_btc_max_hold_audited_regression(tmp_path):
    """paper_sessions/funding_live trade #13: BTC-USDT BUY, max_hold_expired,
    covering a short opened ~5.7 days earlier. The bug's asymmetric
    accounting produced a spurious +$603.55 jump. The fixed executor must
    produce exactly margin_release + net_pnl, matching every other exit.
    """
    session = _session(leverage=2.0)
    entry_price = 64191.8367
    qty = 0.003115
    margin = (qty * entry_price) / 2.0
    book = _book_with_open_position(
        "BTC-USDT", qty=qty, entry_price=entry_price, margin=margin,
        leverage=2.0, direction=-1, entry_time="2026-07-24T19:33:42.403648+00:00",
    )
    cash_before = book["cash_remaining"]

    intent = CloseIntent(symbol="BTC-USDT", quantity=qty, reason="max_hold_expired", mark_price=64858.3517)
    trade = paper_session._execute_close_intent(session, book, tmp_path, intent, "2026-07-30T12:20:40.763444+00:00")

    assert trade["margin"] == pytest.approx(margin, rel=1e-6)
    assert book["cash_remaining"] == pytest.approx(cash_before + margin + trade["net_pnl"], rel=1e-9)
    assert book["reserved_margin"] == pytest.approx(0.0, abs=1e-6)


# ── detection does not mutate financial state ──────────────────────────


def test_risk_detection_does_not_mutate_state(tmp_path):
    session = _session()
    book = _book_with_open_position(
        "DOGE-USDT", qty=1000.0, entry_price=0.10, margin=50.0,
        leverage=2.0, direction=1, entry_time="2026-07-01T00:00:00+00:00",
    )
    before = copy.deepcopy(book)

    intents = paper_session._check_risk_exits(session, book, {"DOGE-USDT": 0.0965}, "2026-07-01T01:00:00+00:00", tmp_path)

    assert len(intents) == 1  # stop_loss should have fired
    assert intents[0].reason == "stop_loss"
    # Detection must not touch cash/margin/positions/fees -- only intents
    # are produced; only high/low-water-mark bookkeeping may change.
    assert book["cash_remaining"] == before["cash_remaining"]
    assert book["reserved_margin"] == before["reserved_margin"]
    assert book["positions"] == before["positions"]
    assert book["position_metadata"]["DOGE-USDT"]["margin"] == before["position_metadata"]["DOGE-USDT"]["margin"]


# ── every exit reason shares the same settlement ───────────────────────


@pytest.mark.parametrize(
    "reason",
    ["funding_z_exit", "take_profit", "stop_loss", "trailing_stop", "max_hold_expired", "liquidation"],
)
def test_close_reason_produces_identical_settlement(tmp_path, reason):
    session = _session()

    def make_book():
        return _book_with_open_position(
            "BTC-USDT", qty=0.01, entry_price=65000.0, margin=325.0,
            leverage=2.0, direction=1, entry_time="2026-07-01T00:00:00+00:00",
        )

    book_a = make_book()
    book_b = make_book()

    intent = CloseIntent(symbol="BTC-USDT", quantity=0.01, reason=reason, mark_price=64000.0)
    trade_a = paper_session._execute_close_intent(session, book_a, tmp_path, intent, "2026-07-02T00:00:00+00:00")
    trade_b = paper_session._execute_close_intent(session, book_b, tmp_path, CloseIntent(
        symbol="BTC-USDT", quantity=0.01, reason="a_different_reason_label", mark_price=64000.0,
    ), "2026-07-02T00:00:00+00:00")

    for key in ("qty", "price", "notional", "fee_paid", "gross_pnl", "net_pnl", "margin"):
        assert trade_a[key] == pytest.approx(trade_b[key], rel=1e-9)
    assert book_a["cash_remaining"] == pytest.approx(book_b["cash_remaining"], rel=1e-9)
    assert book_a["reserved_margin"] == pytest.approx(book_b["reserved_margin"], rel=1e-9)


def test_identical_close_inputs_produce_identical_output(tmp_path):
    session = _session()

    def run_once():
        book = _book_with_open_position(
            "BTC-USDT", qty=0.02, entry_price=65000.0, margin=650.0,
            leverage=2.0, direction=-1, entry_time="2026-07-01T00:00:00+00:00",
        )
        intent = CloseIntent(symbol="BTC-USDT", quantity=0.02, reason="stop_loss", mark_price=66000.0)
        trade = paper_session._execute_close_intent(session, book, tmp_path, intent, "2026-07-02T00:00:00+00:00")
        return trade, book["cash_remaining"], book["reserved_margin"]

    results = [run_once() for _ in range(5)]
    assert len(set(str(r) for r in results)) == 1


# ── invariant / error handling ──────────────────────────────────────────


def test_failed_close_writes_nothing(tmp_path):
    """Closing more than the open quantity must raise before `book` is
    touched at all -- the ledger validates fully in-memory before
    _execute_close_intent applies anything back to book.
    """
    session = _session()
    book = _book_with_open_position(
        "BTC-USDT", qty=0.01, entry_price=65000.0, margin=325.0,
        leverage=2.0, direction=1, entry_time="2026-07-01T00:00:00+00:00",
    )
    before = copy.deepcopy(book)

    intent = CloseIntent(symbol="BTC-USDT", quantity=0.05, reason="manual", mark_price=64000.0)
    with pytest.raises(ValueError):
        paper_session._execute_close_intent(session, book, tmp_path, intent, "2026-07-02T00:00:00+00:00")

    assert book == before


def test_failed_open_writes_nothing(tmp_path):
    session = _session()
    book = {
        "positions": {},
        "cash_remaining": 1.0,  # not enough for any position
        "reserved_margin": 0.0,
        "last_rebalance_time": "2026-07-01T00:00:00+00:00",
        "position_metadata": {},
    }
    before = copy.deepcopy(book)

    with pytest.raises(ValueError):
        paper_session._execute_open_position(
            session, book, "BTC-USDT", LedgerSide.LONG, 1000.0, 65000.0,
            "2026-07-01T00:00:00+00:00", 2.0, "isolated", 0.10, reason="test",
        )

    assert book == before


# ── margin bookkeeping invariant ────────────────────────────────────────


def test_reserved_margin_equals_position_margin_total_after_open_and_close(tmp_path):
    session = _session()
    book = {
        "positions": {},
        "cash_remaining": 10000.0,
        "reserved_margin": 0.0,
        "last_rebalance_time": "2026-07-01T00:00:00+00:00",
        "position_metadata": {},
    }

    paper_session._execute_open_position(
        session, book, "BTC-USDT", LedgerSide.LONG, 1000.0, 65000.0,
        "2026-07-01T00:00:00+00:00", 2.0, "isolated", 0.10, reason="funding_z_long z=-2.0",
    )
    paper_session._execute_open_position(
        session, book, "DOGE-USDT", LedgerSide.SHORT, 500.0, 0.10,
        "2026-07-01T00:00:00+00:00", 2.0, "isolated", 0.10, reason="funding_z_short z=2.0",
    )

    expected_reserved = sum(m["margin"] for m in book["position_metadata"].values())
    assert book["reserved_margin"] == pytest.approx(expected_reserved, rel=1e-9)

    intent = CloseIntent(symbol="BTC-USDT", quantity=book["position_metadata"]["BTC-USDT"]["qty"], reason="funding_z_exit z=0.1", mark_price=65100.0)
    paper_session._execute_close_intent(session, book, tmp_path, intent, "2026-07-02T00:00:00+00:00")

    expected_reserved = sum(m["margin"] for m in book["position_metadata"].values())
    assert book["reserved_margin"] == pytest.approx(expected_reserved, rel=1e-9)
    assert "BTC-USDT" not in book["position_metadata"]
