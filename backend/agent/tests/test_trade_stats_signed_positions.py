"""Regression coverage for compute_trade_stats' signed-position accounting.

The previous version treated every SELL as closing a long against a
weighted-average cost basis that starts at 0.0. Fine for a long-only
strategy, but a SELL that actually opens a short from flat has no long to
close -- the old code priced it against a fabricated $0 cost basis and
booked the entire notional as a fake realized gain. That's exactly what
happened to funding_live's first BTC-USDT trade (a real production
session): a SELL opening a 2x short was reported as a $199.84 win.

These tests build synthetic trade sequences (not real Binance data) to pin
down every branch of the signed-position replay: opens, adds, partial
closes, full closes, and direction flips, on both the long and short side,
plus the two independent validators that would have caught the original
defect even though the portfolio-level equity identity still balanced.
"""

from __future__ import annotations

import pytest

import paper_session as ps
from paper_accounting_guard import validate_trade_closing_attribution


def _trade(symbol, side, qty, price, fee=0.0, ts="2026-01-01T00:00:00+00:00"):
    return {
        "timestamp": ts, "symbol": symbol, "side": side, "qty": qty, "price": price,
        "notional": qty * price, "fee_paid": fee, "reason": "test",
    }


# 1. SELL from flat opens a short and realizes nothing.
def test_sell_from_flat_opens_short_and_realizes_nothing():
    stats = ps.compute_trade_stats([_trade("BTC-USDT", "SELL", 1.0, 100.0)])
    trade = stats["trades"][0]
    assert trade["position_effect"] == "OPEN_SHORT"
    assert trade["closed_qty"] == 0.0
    assert trade["opened_qty"] == 1.0
    assert trade["realized_pnl"] is None
    assert stats["by_symbol"]["BTC-USDT"]["open_qty"] == pytest.approx(-1.0)
    assert stats["overall"]["win_count"] == 0
    assert stats["overall"]["loss_count"] == 0


# 2. BUY from flat opens a long and realizes nothing.
def test_buy_from_flat_opens_long_and_realizes_nothing():
    stats = ps.compute_trade_stats([_trade("AAA", "BUY", 1.0, 100.0)])
    trade = stats["trades"][0]
    assert trade["position_effect"] == "OPEN_LONG"
    assert trade["closed_qty"] == 0.0
    assert trade["realized_pnl"] is None
    assert stats["by_symbol"]["AAA"]["open_qty"] == pytest.approx(1.0)


# 3. Profitable long close.
def test_profitable_long_close():
    trades = [_trade("AAA", "BUY", 1.0, 100.0), _trade("AAA", "SELL", 1.0, 110.0)]
    stats = ps.compute_trade_stats(trades)
    close = stats["trades"][1]
    assert close["position_effect"] == "CLOSE_LONG"
    assert close["gross_pnl"] == pytest.approx(10.0)
    assert close["net_pnl"] == pytest.approx(10.0)
    assert stats["overall"]["win_count"] == 1


# 4. Losing long close.
def test_losing_long_close():
    trades = [_trade("AAA", "BUY", 1.0, 100.0), _trade("AAA", "SELL", 1.0, 90.0)]
    stats = ps.compute_trade_stats(trades)
    close = stats["trades"][1]
    assert close["gross_pnl"] == pytest.approx(-10.0)
    assert stats["overall"]["loss_count"] == 1


# 5. Profitable short cover (short at 100, cover at 90 -> +10/unit).
def test_profitable_short_cover():
    trades = [_trade("BTC-USDT", "SELL", 1.0, 100.0), _trade("BTC-USDT", "BUY", 1.0, 90.0)]
    stats = ps.compute_trade_stats(trades)
    cover = stats["trades"][1]
    assert cover["position_effect"] == "CLOSE_SHORT"
    assert cover["gross_pnl"] == pytest.approx(10.0)
    assert stats["overall"]["win_count"] == 1
    assert stats["by_symbol"]["BTC-USDT"]["open_qty"] == pytest.approx(0.0)


# 6. Losing short cover (short at 100, cover at 110 -> -10/unit).
def test_losing_short_cover():
    trades = [_trade("BTC-USDT", "SELL", 1.0, 100.0), _trade("BTC-USDT", "BUY", 1.0, 110.0)]
    stats = ps.compute_trade_stats(trades)
    cover = stats["trades"][1]
    assert cover["gross_pnl"] == pytest.approx(-10.0)
    assert stats["overall"]["loss_count"] == 1


# 7. Partial long close preserves remaining average entry.
def test_partial_long_close_preserves_remaining_avg_entry():
    trades = [
        _trade("AAA", "BUY", 2.0, 100.0),
        _trade("AAA", "SELL", 1.0, 120.0),
    ]
    stats = ps.compute_trade_stats(trades)
    close = stats["trades"][1]
    assert close["position_effect"] == "REDUCE_LONG"
    assert close["closed_qty"] == pytest.approx(1.0)
    assert close["gross_pnl"] == pytest.approx(20.0)  # 1 * (120-100)
    row = stats["by_symbol"]["AAA"]
    assert row["open_qty"] == pytest.approx(1.0)
    assert row["avg_cost"] == pytest.approx(100.0)  # unchanged for the remaining unit


# 8. Partial short cover preserves remaining average entry.
def test_partial_short_cover_preserves_remaining_avg_entry():
    trades = [
        _trade("BTC-USDT", "SELL", 2.0, 100.0),
        _trade("BTC-USDT", "BUY", 1.0, 90.0),
    ]
    stats = ps.compute_trade_stats(trades)
    cover = stats["trades"][1]
    assert cover["position_effect"] == "REDUCE_SHORT"
    assert cover["closed_qty"] == pytest.approx(1.0)
    row = stats["by_symbol"]["BTC-USDT"]
    assert row["open_qty"] == pytest.approx(-1.0)
    assert row["avg_cost"] == pytest.approx(100.0)


# 9. Long-to-short flip realizes only the closed long quantity.
def test_long_to_short_flip_realizes_only_closed_portion():
    trades = [
        _trade("AAA", "BUY", 1.0, 100.0),
        _trade("AAA", "SELL", 3.0, 110.0),  # closes the 1 long, opens a 2-short
    ]
    stats = ps.compute_trade_stats(trades)
    flip = stats["trades"][1]
    assert flip["position_effect"] == "FLIP_LONG_TO_SHORT"
    assert flip["closed_qty"] == pytest.approx(1.0)
    assert flip["opened_qty"] == pytest.approx(2.0)
    assert flip["gross_pnl"] == pytest.approx(10.0)  # only the closed unit
    row = stats["by_symbol"]["AAA"]
    assert row["open_qty"] == pytest.approx(-2.0)
    assert row["avg_cost"] == pytest.approx(110.0)  # new short entered at execution price


# 10. Short-to-long flip realizes only the covered short quantity.
def test_short_to_long_flip_realizes_only_covered_portion():
    trades = [
        _trade("BTC-USDT", "SELL", 1.0, 100.0),
        _trade("BTC-USDT", "BUY", 3.0, 90.0),  # covers the 1 short, opens a 2-long
    ]
    stats = ps.compute_trade_stats(trades)
    flip = stats["trades"][1]
    assert flip["position_effect"] == "FLIP_SHORT_TO_LONG"
    assert flip["closed_qty"] == pytest.approx(1.0)
    assert flip["opened_qty"] == pytest.approx(2.0)
    assert flip["gross_pnl"] == pytest.approx(10.0)
    row = stats["by_symbol"]["BTC-USDT"]
    assert row["open_qty"] == pytest.approx(2.0)
    assert row["avg_cost"] == pytest.approx(90.0)


# 11. Same-direction short additions calculate the correct weighted entry.
def test_same_direction_short_additions_weighted_entry():
    trades = [
        _trade("BTC-USDT", "SELL", 1.0, 100.0),
        _trade("BTC-USDT", "SELL", 1.0, 120.0),
    ]
    stats = ps.compute_trade_stats(trades)
    add = stats["trades"][1]
    assert add["position_effect"] == "INCREASE_SHORT"
    row = stats["by_symbol"]["BTC-USDT"]
    assert row["open_qty"] == pytest.approx(-2.0)
    assert row["avg_cost"] == pytest.approx(110.0)  # (100+120)/2


# 12. Entry and exit fees are allocated correctly (long side).
def test_fee_allocation_on_open_and_close():
    trades = [
        _trade("AAA", "BUY", 1.0, 100.0, fee=1.0),
        _trade("AAA", "SELL", 1.0, 110.0, fee=1.1),
    ]
    stats = ps.compute_trade_stats(trades)
    open_trade, close_trade = stats["trades"]
    assert open_trade["closing_fee"] is None
    assert open_trade["opening_fee"] == pytest.approx(1.0)
    assert close_trade["entry_fee_allocated"] == pytest.approx(1.0)
    assert close_trade["closing_fee"] == pytest.approx(1.1)
    assert close_trade["net_pnl"] == pytest.approx(10.0 - 1.0 - 1.1)


# 13. Win rate / profit factor / expectancy / largest win-loss use only closing events.
def test_aggregate_stats_ignore_opening_trades():
    trades = [
        _trade("AAA", "BUY", 1.0, 100.0),   # open -- must not count as a trade outcome
        _trade("AAA", "SELL", 1.0, 110.0),  # win
        _trade("BTC-USDT", "SELL", 1.0, 100.0),  # open short -- must not count
        _trade("BTC-USDT", "BUY", 1.0, 95.0),    # win (short profit)
    ]
    stats = ps.compute_trade_stats(trades)
    overall = stats["overall"]
    assert overall["win_count"] == 2
    assert overall["loss_count"] == 0
    assert overall["realized_pnl"] == pytest.approx(10.0 + 5.0)


# 14. Existing long-only paper-session tests remain unchanged -- spot check
# against the exact scenario test_compute_trade_stats_allocates_entry_and_exit_fees
# (in test_paper_session_accounting.py) already covers, reproduced here so this
# file alone still proves long-only compatibility wasn't broken.
def test_long_only_behavior_matches_pre_existing_contract():
    trades = [
        {"timestamp": "t0", "symbol": "BTC-USDT", "side": "BUY", "qty": 1.0, "price": 100.0,
         "notional": 100.0, "fee_paid": 1.0, "reason": "entry"},
        {"timestamp": "t1", "symbol": "BTC-USDT", "side": "SELL", "qty": 1.0, "price": 110.0,
         "notional": 110.0, "fee_paid": 1.0, "reason": "rebalance"},
    ]
    stats = ps.compute_trade_stats(trades)
    closed = stats["trades"][1]
    assert closed["gross_pnl"] == pytest.approx(10.0)
    assert closed["entry_fee_allocated"] == pytest.approx(1.0)
    assert closed["total_fees"] == pytest.approx(2.0)
    assert closed["net_pnl"] == pytest.approx(8.0)
    assert stats["overall"]["realized_pnl"] == pytest.approx(8.0)
    assert stats["overall"]["fees_paid"] == pytest.approx(2.0)
    assert stats["overall"]["expectancy"] == pytest.approx(8.0)


# 15. Morning Glory's first BTC SELL is classified as OPEN_SHORT, not a win --
# the exact real-world trade that surfaced this bug.
def test_funding_live_first_btc_sell_is_open_short_not_a_win():
    trade = _trade("BTC-USDT", "SELL", 0.0031147262700685708, 64191.836670000004,
                    fee=0.09997000000000002, ts="2026-07-24T19:33:42.403648+00:00")
    stats = ps.compute_trade_stats([trade])
    annotated = stats["trades"][0]
    assert annotated["position_effect"] == "OPEN_SHORT"
    assert annotated["closed_qty"] == 0.0
    assert annotated["realized_pnl"] is None
    assert annotated["gross_pnl"] is None
    assert stats["overall"]["win_count"] == 0
    assert stats["overall"]["realized_pnl"] == pytest.approx(0.0)


# Additional cases from the second, expanded spec.

def test_breakeven_close_not_counted_as_win_or_loss():
    trades = [_trade("AAA", "BUY", 1.0, 100.0), _trade("AAA", "SELL", 1.0, 100.0)]
    stats = ps.compute_trade_stats(trades)
    assert stats["overall"]["win_count"] == 0
    assert stats["overall"]["loss_count"] == 0
    assert stats["by_symbol"]["AAA"]["breakeven_count"] == 1


def test_multiple_alternating_long_short_cycles():
    trades = [
        _trade("AAA", "BUY", 1.0, 100.0),   # open long
        _trade("AAA", "SELL", 2.0, 110.0),  # close long (+10), open short 1 @110
        _trade("AAA", "BUY", 1.0, 90.0),    # close short (+20)
    ]
    stats = ps.compute_trade_stats(trades)
    effects = [t["position_effect"] for t in stats["trades"]]
    assert effects == ["OPEN_LONG", "FLIP_LONG_TO_SHORT", "CLOSE_SHORT"]
    assert stats["overall"]["realized_pnl"] == pytest.approx(10.0 + 20.0)
    assert stats["by_symbol"]["AAA"]["open_qty"] == pytest.approx(0.0)


def test_inventory_reconciliation_against_book():
    from paper_accounting_guard import validate_inventory_reconciliation
    trades = [_trade("AAA", "BUY", 2.0, 100.0), _trade("AAA", "SELL", 1.0, 110.0)]
    stats = ps.compute_trade_stats(trades)
    diffs = validate_inventory_reconciliation(stats["by_symbol"], {"AAA": 1.0})
    assert diffs == {}
    corrupted = validate_inventory_reconciliation(stats["by_symbol"], {"AAA": 5.0})
    assert "AAA" in corrupted


def test_closure_validity_detects_the_original_defect_pattern():
    """Simulates what the OLD (buggy) annotation would have looked like --
    closed_qty fabricated as the full sell qty on a short-open -- and
    confirms the independent validator flags it."""
    fake_annotated = [{
        "symbol": "BTC-USDT", "side": "SELL", "qty": 1.0, "price": 100.0,
        "position_before": 0.0,
        "closed_qty": 1.0,  # WRONG -- should be 0.0 (opening a short from flat)
        "realized_pnl": 99.94,
    }]
    violations = validate_trade_closing_attribution(fake_annotated)
    assert len(violations) >= 1
    assert violations[0]["symbol"] == "BTC-USDT"
    assert violations[0]["expected_closed_qty"] == 0.0


def test_closure_validity_passes_on_correctly_annotated_trades():
    trades = [
        _trade("AAA", "BUY", 1.0, 100.0),
        _trade("AAA", "SELL", 1.0, 110.0),
        _trade("BTC-USDT", "SELL", 1.0, 100.0),
        _trade("BTC-USDT", "BUY", 1.0, 90.0),
    ]
    stats = ps.compute_trade_stats(trades)
    violations = validate_trade_closing_attribution(stats["trades"])
    assert violations == []


def test_structural_invariant_no_closed_qty_means_no_realized_pnl():
    trades = [_trade("AAA", "BUY", 1.0, 100.0), _trade("BTC-USDT", "SELL", 1.0, 100.0)]
    stats = ps.compute_trade_stats(trades)
    for trade in stats["trades"]:
        if trade["closed_qty"] == 0.0:
            assert trade["realized_pnl"] is None


def test_structural_invariant_open_position_has_positive_avg_cost():
    trades = [_trade("AAA", "BUY", 1.0, 100.0), _trade("BTC-USDT", "SELL", 1.0, 100.0)]
    stats = ps.compute_trade_stats(trades)
    for row in stats["by_symbol"].values():
        if abs(row["open_qty"]) > 1e-9:
            assert row["avg_cost"] > 0


def test_trade_stats_version_marker_present():
    stats = ps.compute_trade_stats([_trade("AAA", "BUY", 1.0, 100.0)])
    assert stats["trade_stats_version"] == "signed_weighted_average_v2"
