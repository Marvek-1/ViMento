from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import api_server
import paper_session
import shadow_ab_pair
import src.api.paper_session_routes as paper_routes


def _write_session(
    session_dir,
    *,
    initial_cash: float,
    cash_remaining: float,
    positions: dict[str, float],
    trades: list[dict],
    marks: list[dict],
) -> None:
    """Hand-build a session directory's on-disk files for diagnostics tests.

    Bypasses start_session()/rebalance_if_due() (which always rebalance back
    to equal weight and can never fully flatten a symbol) so scenarios like
    a fully-closed position or a stale mark can be constructed directly.
    """
    session_dir.mkdir(parents=True)
    session = {
        "strategy_type": paper_session.STRATEGY_TYPE,
        "symbols": list(positions.keys()),
        "initial_cash": initial_cash,
        "entry_time": trades[0]["timestamp"],
        "rebalance_interval_hours": 4.0,
        "fee_rate": 0.0,
    }
    (session_dir / "session.json").write_text(json.dumps(session), encoding="utf-8")
    book = {"positions": positions, "cash_remaining": cash_remaining, "last_rebalance_time": trades[-1]["timestamp"]}
    (session_dir / "book.json").write_text(json.dumps(book), encoding="utf-8")
    (session_dir / "trades.jsonl").write_text(
        "".join(json.dumps(t) + "\n" for t in trades), encoding="utf-8"
    )
    (session_dir / "marks.jsonl").write_text(
        "".join(json.dumps(m) + "\n" for m in marks), encoding="utf-8"
    )


def test_compute_trade_stats_allocates_entry_and_exit_fees() -> None:
    stats = paper_session.compute_trade_stats(
        [
            {
                "timestamp": "2026-07-11T00:00:00+00:00",
                "symbol": "BTC-USDT",
                "side": "BUY",
                "qty": 1.0,
                "price": 100.0,
                "notional": 100.0,
                "fee_paid": 1.0,
                "reason": "entry",
            },
            {
                "timestamp": "2026-07-11T01:00:00+00:00",
                "symbol": "BTC-USDT",
                "side": "SELL",
                "qty": 1.0,
                "price": 110.0,
                "notional": 110.0,
                "fee_paid": 1.0,
                "reason": "rebalance",
            },
        ]
    )

    closed = stats["trades"][1]
    assert closed["gross_pnl"] == pytest.approx(10.0)
    assert closed["entry_fee_allocated"] == pytest.approx(1.0)
    assert closed["total_fees"] == pytest.approx(2.0)
    assert closed["net_pnl"] == pytest.approx(8.0)
    assert stats["overall"]["realized_pnl"] == pytest.approx(8.0)
    assert stats["overall"]["fees_paid"] == pytest.approx(2.0)
    assert stats["overall"]["expectancy"] == pytest.approx(8.0)


def test_rebalance_applies_trade_notional_to_cash(tmp_path, monkeypatch) -> None:
    prices = {
        "entry": {"AAA-USDT": 10.0, "BBB-USDT": 10.0},
        "rebalance": {"AAA-USDT": 20.0, "BBB-USDT": 10.0},
    }
    current = {"value": "entry"}

    def fake_prices(symbols: list[str]) -> dict[str, float]:
        return {symbol: prices[current["value"]][symbol] for symbol in symbols}

    monkeypatch.setattr(paper_session, "fetch_last_prices", fake_prices)
    session_dir = tmp_path / "paper"

    paper_session.start_session(
        session_dir,
        ["AAA-USDT", "BBB-USDT"],
        initial_cash=100.0,
        rebalance_interval_hours=1.0,
        fee_rate=0.01,
    )
    current["value"] = "rebalance"
    result = paper_session.rebalance_if_due(session_dir, force=True)

    assert result is not None
    trades = result["trades"]
    assert [trade["side"] for trade in trades] == ["SELL", "BUY"]
    sell_proceeds = sum(
        trade["notional"] - trade["fee_paid"] for trade in trades if trade["side"] == "SELL"
    )
    buy_cost = sum(
        trade["notional"] + trade["fee_paid"] for trade in trades if trade["side"] == "BUY"
    )
    assert buy_cost <= sell_proceeds + 1e-12
    assert result["mark"]["cash_remaining"] == pytest.approx(0.0, abs=1e-12)


def test_rebalance_scales_pending_buys_when_no_trade_band_skips_a_sell(tmp_path, monkeypatch) -> None:
    symbols = ["AAA-USDT", "BBB-USDT", "CCC-USDT", "DDD-USDT"]
    entry_prices = {symbol: 10.0 for symbol in symbols}
    monkeypatch.setattr(
        paper_session,
        "fetch_last_prices",
        lambda requested: {symbol: entry_prices[symbol] for symbol in requested},
    )
    session_dir = tmp_path / "cash_constrained_candidate"
    paper_session.start_session(
        session_dir,
        symbols,
        initial_cash=400.0,
        rebalance_interval_hours=1.0,
        fee_rate=0.01,
        min_rebalance_notional=10.0,
    )
    positions = paper_session._load_book(session_dir)["positions"]
    desired_values = {
        "AAA-USDT": 120.0,
        "BBB-USDT": 109.0,
        "CCC-USDT": 85.0,
        "DDD-USDT": 86.0,
    }
    rebalance_prices = {
        symbol: desired_values[symbol] / positions[symbol] for symbol in symbols
    }

    result = paper_session.rebalance_if_due(
        session_dir,
        force=True,
        prices=rebalance_prices,
        now="2026-07-19T06:00:00+00:00",
    )

    trades = result["trades"]
    assert [trade["side"] for trade in trades] == ["SELL", "BUY", "BUY"]
    assert trades[0]["symbol"] == "AAA-USDT"
    assert all(trade["symbol"] != "BBB-USDT" for trade in trades)
    sell_proceeds = trades[0]["notional"] - trades[0]["fee_paid"]
    buys = [trade for trade in trades if trade["side"] == "BUY"]
    buy_cost = sum(trade["notional"] + trade["fee_paid"] for trade in buys)
    assert buy_cost <= sell_proceeds + 1e-12
    assert buys[0]["notional"] / 15.0 == pytest.approx(buys[1]["notional"] / 14.0)
    assert result["mark"]["cash_remaining"] == pytest.approx(0.0, abs=1e-12)
    assert paper_session._load_book(session_dir)["cash_remaining"] >= 0.0
    diagnostics = paper_session.compute_session_diagnostics(session_dir)
    assert diagnostics["metrics"]["reconciled"] is True
    assert diagnostics["metrics"]["reconciliation_error"] == pytest.approx(0.0, abs=1e-9)
    assert paper_session._load_session(session_dir)["accounting_status"] == "OK"


def test_paper_session_diagnostics_route_is_read_only(tmp_path, monkeypatch) -> None:
    prices = {"AAA-USDT": 10.0, "BBB-USDT": 10.0}
    monkeypatch.setattr(paper_session, "fetch_last_prices", lambda symbols: {s: prices[s] for s in symbols})
    monkeypatch.setattr(paper_routes, "PAPER_SESSIONS_DIR", tmp_path)

    session_dir = tmp_path / "s1"
    paper_session.start_session(
        session_dir,
        ["AAA-USDT", "BBB-USDT"],
        initial_cash=100.0,
        rebalance_interval_hours=1.0,
        fee_rate=0.01,
    )

    client = TestClient(api_server.app, client=("127.0.0.1", 50000))
    response = client.get("/paper-sessions/s1/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["execution_permissions"] == "paper_only"
    assert body["idimikang_used"] is False
    assert body["metrics"]["fees_paid"] == pytest.approx(100.0 / 101.0)


def test_diagnostics_reconciles_fully_closed_position(tmp_path) -> None:
    session_dir = tmp_path / "s_closed"
    trades = [
        {"timestamp": "t0", "symbol": "AAA-USDT", "side": "BUY", "qty": 1.0, "price": 100.0,
         "notional": 100.0, "fee_paid": 1.0, "reason": "entry"},
        {"timestamp": "t1", "symbol": "AAA-USDT", "side": "SELL", "qty": 1.0, "price": 110.0,
         "notional": 110.0, "fee_paid": 1.0, "reason": "rebalance"},
    ]
    marks = [{"timestamp": "t1", "prices": {"AAA-USDT": 110.0}, "equity": 1008.0, "cash_remaining": 1008.0}]
    _write_session(
        session_dir, initial_cash=1000.0, cash_remaining=1008.0,
        positions={"AAA-USDT": 0.0}, trades=trades, marks=marks,
    )

    metrics = paper_session.compute_session_diagnostics(session_dir)["metrics"]
    assert metrics["realized_pnl"] == pytest.approx(8.0)
    assert metrics["unrealized_pnl"] == pytest.approx(0.0)
    assert metrics["open_position_count"] == 0
    assert metrics["current_equity"] == pytest.approx(1008.0)
    assert metrics["reconciliation_error"] == pytest.approx(0.0)
    assert metrics["reconciled"] is True


def test_diagnostics_reconciles_partial_close_with_remaining_inventory(tmp_path) -> None:
    session_dir = tmp_path / "s_partial"
    trades = [
        {"timestamp": "t0", "symbol": "AAA-USDT", "side": "BUY", "qty": 2.0, "price": 100.0,
         "notional": 200.0, "fee_paid": 2.0, "reason": "entry"},
        {"timestamp": "t1", "symbol": "AAA-USDT", "side": "SELL", "qty": 1.0, "price": 110.0,
         "notional": 110.0, "fee_paid": 1.0, "reason": "rebalance"},
    ]
    cash_remaining = 1000.0 - 200.0 - 2.0 + 110.0 - 1.0  # 907.0
    marks = [{"timestamp": "t1", "prices": {"AAA-USDT": 120.0}, "equity": cash_remaining + 120.0,
              "cash_remaining": cash_remaining}]
    _write_session(
        session_dir, initial_cash=1000.0, cash_remaining=cash_remaining,
        positions={"AAA-USDT": 1.0}, trades=trades, marks=marks,
    )

    metrics = paper_session.compute_session_diagnostics(session_dir)["metrics"]
    assert metrics["realized_pnl"] == pytest.approx(8.0)
    assert metrics["open_cost_basis"] == pytest.approx(101.0)  # 1*100 avg_cost + 1 remaining entry fee
    assert metrics["unrealized_pnl"] == pytest.approx(19.0)  # 120 market value - 101 cost basis
    assert metrics["reconciliation_error"] == pytest.approx(0.0)
    assert metrics["reconciled"] is True


def test_diagnostics_reflects_open_losing_position(tmp_path) -> None:
    session_dir = tmp_path / "s_loss"
    trades = [
        {"timestamp": "t0", "symbol": "AAA-USDT", "side": "BUY", "qty": 1.0, "price": 100.0,
         "notional": 100.0, "fee_paid": 1.0, "reason": "entry"},
    ]
    entry_equity = 1000.0 - 101.0 + 100.0  # 999.0, first mark at entry price
    later_equity = 1000.0 - 101.0 + 80.0  # 979.0, price has since dropped
    marks = [
        {"timestamp": "t0", "prices": {"AAA-USDT": 100.0}, "equity": entry_equity, "cash_remaining": 899.0},
        {"timestamp": "t1", "prices": {"AAA-USDT": 80.0}, "equity": later_equity, "cash_remaining": 899.0},
    ]
    _write_session(
        session_dir, initial_cash=1000.0, cash_remaining=899.0,
        positions={"AAA-USDT": 1.0}, trades=trades, marks=marks,
    )

    diagnostics = paper_session.compute_session_diagnostics(session_dir)
    metrics = diagnostics["metrics"]
    assert metrics["realized_pnl"] == pytest.approx(0.0)
    assert metrics["unrealized_pnl"] == pytest.approx(-21.0)  # 80 - (100 + 1 fee)
    assert metrics["unrealized_pnl"] < 0
    assert metrics["reconciliation_error"] == pytest.approx(0.0)
    assert diagnostics["metrics"]["max_drawdown"] < 0  # the open loss shows up as drawdown


def test_diagnostics_reflects_open_profitable_position(tmp_path) -> None:
    session_dir = tmp_path / "s_gain"
    trades = [
        {"timestamp": "t0", "symbol": "AAA-USDT", "side": "BUY", "qty": 1.0, "price": 100.0,
         "notional": 100.0, "fee_paid": 1.0, "reason": "entry"},
    ]
    equity = 1000.0 - 101.0 + 130.0
    marks = [{"timestamp": "t0", "prices": {"AAA-USDT": 130.0}, "equity": equity, "cash_remaining": 899.0}]
    _write_session(
        session_dir, initial_cash=1000.0, cash_remaining=899.0,
        positions={"AAA-USDT": 1.0}, trades=trades, marks=marks,
    )

    metrics = paper_session.compute_session_diagnostics(session_dir)["metrics"]
    assert metrics["realized_pnl"] == pytest.approx(0.0)
    assert metrics["unrealized_pnl"] == pytest.approx(29.0)  # 130 - (100 + 1 fee)
    assert metrics["unrealized_pnl"] > 0
    assert metrics["reconciliation_error"] == pytest.approx(0.0)


def test_diagnostics_reconciles_incremental_buys_and_partial_sell(tmp_path) -> None:
    session_dir = tmp_path / "s_incremental"
    trades = [
        {"timestamp": "t0", "symbol": "AAA-USDT", "side": "BUY", "qty": 1.0, "price": 100.0,
         "notional": 100.0, "fee_paid": 1.0, "reason": "entry"},
        {"timestamp": "t1", "symbol": "AAA-USDT", "side": "BUY", "qty": 1.0, "price": 120.0,
         "notional": 120.0, "fee_paid": 1.2, "reason": "rebalance"},
        {"timestamp": "t2", "symbol": "AAA-USDT", "side": "SELL", "qty": 1.5, "price": 130.0,
         "notional": 195.0, "fee_paid": 1.95, "reason": "rebalance"},
    ]
    # avg_cost after both buys = (1*100 + 1*120) / 2 = 110; entry_fee_basis = 2.2
    # sell closes 1.5 of 2.0 open qty -> allocates 1.5/2.0 * 2.2 = 1.65 of entry fee
    cash_remaining = 1000.0 - 100.0 - 1.0 - 120.0 - 1.2 + 195.0 - 1.95  # 969.85
    marks = [{"timestamp": "t2", "prices": {"AAA-USDT": 140.0}, "equity": cash_remaining + 0.5 * 140.0,
              "cash_remaining": cash_remaining}]
    _write_session(
        session_dir, initial_cash=1000.0, cash_remaining=cash_remaining,
        positions={"AAA-USDT": 0.5}, trades=trades, marks=marks,
    )

    metrics = paper_session.compute_session_diagnostics(session_dir)["metrics"]
    gross_pnl = 1.5 * (130.0 - 110.0)  # 30.0
    total_fees_on_sell = 1.65 + 1.95  # entry_fee_allocated + exit_fee = 3.6
    expected_realized = gross_pnl - total_fees_on_sell  # 26.4
    assert metrics["realized_pnl"] == pytest.approx(expected_realized)
    remaining_entry_fee_basis = 2.2 - 1.65  # 0.55
    expected_open_cost_basis = 0.5 * 110.0 + remaining_entry_fee_basis  # 55.55
    assert metrics["open_cost_basis"] == pytest.approx(expected_open_cost_basis)
    expected_unrealized = 0.5 * 140.0 - expected_open_cost_basis
    assert metrics["unrealized_pnl"] == pytest.approx(expected_unrealized)
    assert metrics["reconciliation_error"] == pytest.approx(0.0, abs=1e-9)
    assert metrics["reconciled"] is True


def test_diagnostics_flags_stale_mark_instead_of_valuing_at_zero(tmp_path) -> None:
    session_dir = tmp_path / "s_stale"
    trades = [
        {"timestamp": "t0", "symbol": "AAA-USDT", "side": "BUY", "qty": 1.0, "price": 100.0,
         "notional": 100.0, "fee_paid": 1.0, "reason": "entry"},
    ]
    # Latest mark is missing a price for AAA-USDT entirely (simulates a
    # dropped ticker / partial mark write) -- must not be treated as $0.
    marks = [{"timestamp": "t0", "prices": {}, "equity": 899.0, "cash_remaining": 899.0}]
    _write_session(
        session_dir, initial_cash=1000.0, cash_remaining=899.0,
        positions={"AAA-USDT": 1.0}, trades=trades, marks=marks,
    )

    metrics = paper_session.compute_session_diagnostics(session_dir)["metrics"]
    assert metrics["stale_mark_symbols"] == ["AAA-USDT"]
    assert metrics["unrealized_pnl"] is None
    assert metrics["open_market_value"] is None
    assert metrics["reconciliation_error"] is None
    assert metrics["reconciled"] is False


def test_start_session_stamps_accounting_schema_version(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        paper_session, "fetch_last_prices", lambda symbols: {s: 10.0 for s in symbols}
    )
    session_dir = tmp_path / "s_versioned"
    session = paper_session.start_session(
        session_dir, ["AAA-USDT"], initial_cash=100.0, rebalance_interval_hours=1.0, fee_rate=0.0,
    )
    assert session["accounting_schema_version"] == paper_session.ACCOUNTING_SCHEMA_VERSION
    assert session["accounting_status"] == "OK"


def test_start_session_defaults_min_rebalance_notional_to_zero(tmp_path, monkeypatch) -> None:
    """The control arm of a shadow A/B must be indistinguishable from a
    session started before min_rebalance_notional existed."""
    monkeypatch.setattr(
        paper_session, "fetch_last_prices", lambda symbols: {s: 10.0 for s in symbols}
    )
    session_dir = tmp_path / "s_control"
    session = paper_session.start_session(
        session_dir, ["AAA-USDT"], initial_cash=100.0, rebalance_interval_hours=1.0, fee_rate=0.0,
    )
    assert session["min_rebalance_notional"] == 0.0


def test_rebalance_suppresses_trades_below_min_rebalance_notional(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        paper_session, "fetch_last_prices", lambda symbols: {"AAA-USDT": 10.0, "BBB-USDT": 10.0}
    )
    session_dir = tmp_path / "s_candidate"
    paper_session.start_session(
        session_dir, ["AAA-USDT", "BBB-USDT"], initial_cash=100.0,
        rebalance_interval_hours=1.0, fee_rate=0.0, min_rebalance_notional=10.0,
    )

    # AAA drifts up just enough to need a small ($6) rebalance -- below the
    # $10 candidate threshold, so it must be suppressed entirely.
    monkeypatch.setattr(
        paper_session, "fetch_last_prices",
        lambda symbols: {"AAA-USDT": 10.6, "BBB-USDT": 10.0},
    )
    result = paper_session.rebalance_if_due(session_dir, force=True)
    assert result["trades"] == []

    # Now AAA has drifted far enough that its delta exceeds $10 -- must execute.
    # (equity=150, target=75/symbol, AAA position value=100 -> delta=-25)
    monkeypatch.setattr(
        paper_session, "fetch_last_prices",
        lambda symbols: {"AAA-USDT": 20.0, "BBB-USDT": 10.0},
    )
    result = paper_session.rebalance_if_due(session_dir, force=True)
    assert len(result["trades"]) > 0


def test_diagnostics_reports_tracking_error_and_weight_drift(tmp_path) -> None:
    session_dir = tmp_path / "s_drift"
    trades = [
        {"timestamp": "t0", "symbol": "AAA-USDT", "side": "BUY", "qty": 5.0, "price": 10.0,
         "notional": 50.0, "fee_paid": 0.0, "reason": "entry"},
        {"timestamp": "t0", "symbol": "BBB-USDT", "side": "BUY", "qty": 5.0, "price": 10.0,
         "notional": 50.0, "fee_paid": 0.0, "reason": "entry"},
    ]
    # mark 1: perfectly balanced (50/50 -> 0 drift); mark 2: AAA has drifted
    # to 90% of equity, BBB to 10% -- deviations of +0.4 / -0.4 from the 0.5
    # equal-weight target.
    marks = [
        {"timestamp": "t0", "prices": {"AAA-USDT": 10.0, "BBB-USDT": 10.0},
         "position_values": {"AAA-USDT": 50.0, "BBB-USDT": 50.0}, "equity": 100.0, "cash_remaining": 0.0},
        {"timestamp": "t1", "prices": {"AAA-USDT": 18.0, "BBB-USDT": 2.0},
         "position_values": {"AAA-USDT": 90.0, "BBB-USDT": 10.0}, "equity": 100.0, "cash_remaining": 0.0},
    ]
    _write_session(
        session_dir, initial_cash=100.0, cash_remaining=0.0,
        positions={"AAA-USDT": 5.0, "BBB-USDT": 5.0}, trades=trades, marks=marks,
    )

    metrics = paper_session.compute_session_diagnostics(session_dir)["metrics"]
    assert metrics["max_weight_drift"] == pytest.approx(0.4)
    # rms over samples [0, 0, 0.4, -0.4] (2 symbols x 2 marks)
    assert metrics["tracking_error_rms"] == pytest.approx((0.4 * 0.4 * 2 / 4) ** 0.5)


def test_session_status_classifies_control_candidate_and_historical(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(paper_session, "fetch_last_prices", lambda symbols: {s: 10.0 for s in symbols})

    control_dir = tmp_path / "s_control"
    paper_session.start_session(
        control_dir, ["AAA-USDT"], initial_cash=100.0, rebalance_interval_hours=0.25, fee_rate=0.0,
    )
    control_status = paper_session.compute_session_status(control_dir)
    assert control_status["session_role"] == "control"
    assert control_status["regimen"] == "15m"
    assert control_status["runtime_status"] == "running"  # just marked, so recent
    assert control_status["active"] is True
    assert control_status["analysis_status"] == "valid"

    candidate_dir = tmp_path / "s_candidate"
    paper_session.start_session(
        candidate_dir, ["AAA-USDT"], initial_cash=100.0, rebalance_interval_hours=0.25,
        fee_rate=0.0, min_rebalance_notional=10.0,
    )
    candidate_status = paper_session.compute_session_status(candidate_dir)
    assert candidate_status["session_role"] == "candidate"

    # historical: no accounting_schema_version at all (pre-versioning session)
    historical_dir = tmp_path / "s_historical"
    trades = [
        {"timestamp": "t0", "symbol": "AAA-USDT", "side": "BUY", "qty": 1.0, "price": 10.0,
         "notional": 10.0, "fee_paid": 0.0, "reason": "entry"},
    ]
    old_ts = (paper_session.datetime.now(paper_session.timezone.utc) - paper_session.timedelta(days=1)).isoformat()
    marks = [{"timestamp": old_ts, "prices": {"AAA-USDT": 10.0}, "equity": 10.0, "cash_remaining": 0.0}]
    _write_session(
        historical_dir, initial_cash=10.0, cash_remaining=0.0,
        positions={"AAA-USDT": 1.0}, trades=trades, marks=marks,
    )
    historical_status = paper_session.compute_session_status(historical_dir)
    assert historical_status["session_role"] == "historical"
    assert historical_status["runtime_status"] == "stopped"  # last mark is a day old
    assert historical_status["active"] is False


def test_shadow_comparison_pairs_control_and_candidate_by_regimen(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(paper_session, "fetch_last_prices", lambda symbols: {"AAA-USDT": 10.0})

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    paper_session.start_session(
        sessions_dir / "control_15m", ["AAA-USDT"], initial_cash=100.0,
        rebalance_interval_hours=0.25, fee_rate=0.0,
    )
    paper_session.start_session(
        sessions_dir / "candidate_15m", ["AAA-USDT"], initial_cash=100.0,
        rebalance_interval_hours=0.25, fee_rate=0.0, min_rebalance_notional=10.0,
    )

    comparisons = paper_session.build_shadow_comparison(sessions_dir)
    assert len(comparisons) == 1
    row = comparisons[0]
    assert row["regimen"] == "15m"
    assert row["control_session_id"] == "control_15m"
    assert row["candidate_session_id"] == "candidate_15m"
    assert row["delta"] is not None
    assert row["delta"]["net_return"] == pytest.approx(
        row["candidate"]["net_return"] - row["control"]["net_return"]
    )


def test_rebalance_refuses_when_accounting_status_is_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        paper_session, "fetch_last_prices", lambda symbols: {s: 10.0 for s in symbols}
    )
    session_dir = tmp_path / "s_halted"
    paper_session.start_session(
        session_dir, ["AAA-USDT"], initial_cash=100.0, rebalance_interval_hours=1.0, fee_rate=0.0,
    )
    session = paper_session._load_session(session_dir)
    session["accounting_status"] = "ACCOUNTING_ERROR"
    (session_dir / "session.json").write_text(json.dumps(session), encoding="utf-8")

    with pytest.raises(RuntimeError, match="accounting invariant violated"):
        paper_session.rebalance_if_due(session_dir, force=True)


def test_rebalance_refuses_overlapping_cross_process_mutation(tmp_path, monkeypatch) -> None:
    import fcntl

    monkeypatch.setattr(
        paper_session, "fetch_last_prices", lambda symbols: {s: 10.0 for s in symbols}
    )
    session_dir = tmp_path / "s_locked"
    paper_session.start_session(
        session_dir, ["AAA-USDT"], initial_cash=100.0,
        rebalance_interval_hours=1.0, fee_rate=0.0,
    )

    with (session_dir / ".mutation.lock").open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(paper_session.ConcurrentSessionMutation, match="active ledger mutation"):
            paper_session.rebalance_if_due(session_dir, force=True)


def test_rebalance_flags_accounting_status_when_invariant_breaks(tmp_path, monkeypatch) -> None:
    """A rebalance whose own cash update ignores notional (simulating the
    demo_10k_8pair_15m bug) must flip accounting_status to ACCOUNTING_ERROR
    and refuse any further rebalance on this session."""
    monkeypatch.setattr(
        paper_session, "fetch_last_prices", lambda symbols: {s: 10.0 for s in symbols}
    )
    session_dir = tmp_path / "s_breaks"
    paper_session.start_session(
        session_dir, ["AAA-USDT", "BBB-USDT"], initial_cash=100.0, rebalance_interval_hours=1.0, fee_rate=0.0,
    )

    # Corrupt cash_remaining directly, as if a buggy rebalance had already
    # applied fees but not notional -- the next rebalance's own invariant
    # check should catch the resulting mismatch.
    book = paper_session._load_book(session_dir)
    book["cash_remaining"] -= 500.0
    (session_dir / "book.json").write_text(json.dumps(book), encoding="utf-8")

    monkeypatch.setattr(
        paper_session, "fetch_last_prices", lambda symbols: {s: 20.0 for s in symbols}
    )
    paper_session.rebalance_if_due(session_dir, force=True)

    session = paper_session._load_session(session_dir)
    assert session["accounting_status"] == "ACCOUNTING_ERROR"

    with pytest.raises(RuntimeError, match="accounting invariant violated"):
        paper_session.rebalance_if_due(session_dir, force=True)


def test_reconstruct_session_recovers_notional_omitted_from_cash(tmp_path) -> None:
    """Reproduces the demo_10k_8pair_15m bug: cash_remaining only reflects
    fees, never trade notional. session_reconciliation should classify this
    as RECONSTRUCTABLE and recompute the correct, reconciled equity."""
    import session_reconciliation as sr

    session_dir = tmp_path / "s_corrupted_cash"
    trades = [
        {"timestamp": "t0", "symbol": "AAA-USDT", "side": "BUY", "qty": 10.0, "price": 10.0,
         "notional": 100.0, "fee_paid": 0.1, "reason": "entry"},
        {"timestamp": "t1", "symbol": "AAA-USDT", "side": "SELL", "qty": 2.0, "price": 12.0,
         "notional": 24.0, "fee_paid": 0.024, "reason": "rebalance"},
    ]
    # Correct cash would be: 100 - 100 - 0.1 + 24 - 0.024 = 23.876
    # Corrupted cash only reflects fees: -(0.1 + 0.024) = -0.124
    corrupted_cash = -0.124
    marks = [
        {"timestamp": "t0", "prices": {"AAA-USDT": 10.0}, "equity": -0.1 + 100.0, "cash_remaining": -0.1},
        {"timestamp": "t1", "prices": {"AAA-USDT": 12.0}, "equity": corrupted_cash + 8 * 12.0,
         "cash_remaining": corrupted_cash},
    ]
    _write_session(
        session_dir, initial_cash=100.0, cash_remaining=corrupted_cash,
        positions={"AAA-USDT": 8.0}, trades=trades, marks=marks,
    )

    result = sr.classify_session(session_dir)
    assert result["status"] == sr.RECONSTRUCTABLE
    assert result["original_diagnostics"]["metrics"]["reconciled"] is False

    recon_metrics = result["reconstructed_diagnostics"]["metrics"]
    assert recon_metrics["reconciled"] is True
    assert recon_metrics["cash_remaining"] == pytest.approx(23.876)
    assert recon_metrics["current_equity"] == pytest.approx(23.876 + 8 * 12.0)

    report = sr.write_reconstruction(session_dir, output_root=tmp_path / "reconstructed")
    assert report["status"] == sr.RECONSTRUCTABLE
    assert report["original_reconciled"] is False
    assert report["reconstructed_reconciled"] is True
    assert report["cash_ledger_gap"] == pytest.approx(recon_metrics["current_equity"] - (corrupted_cash + 8 * 12.0))
    out_dir = tmp_path / "reconstructed" / "s_corrupted_cash"
    assert (out_dir / "reconstructed_book.json").exists()
    assert (out_dir / "reconstructed_marks.jsonl").exists()
    assert (out_dir / "diagnostics.json").exists()
    assert (out_dir / "reconciliation_report.json").exists()
    # original session directory must be untouched
    assert not (session_dir / "reconstructed_book.json").exists()


def test_start_paired_sessions_uses_a_single_shared_entry_quote(tmp_path, monkeypatch) -> None:
    """A control/candidate pair must enter on the identical quote, not two
    independent fetches a few seconds apart (the archived shadow_ab_v1
    sessions show a real ~5.75s entry-time gap caused by exactly that)."""
    call_count = {"n": 0}

    def fake_prices(symbols: list[str]) -> dict[str, float]:
        call_count["n"] += 1
        # A different price each call would prove a real bug if it leaked
        # into more than one session's entry_prices.
        return {s: 100.0 + call_count["n"] for s in symbols}

    monkeypatch.setattr(paper_session, "fetch_last_prices", fake_prices)

    control_dir = tmp_path / "control"
    candidate_dir = tmp_path / "candidate"
    specs = [
        {
            "session_dir": control_dir,
            "symbols": ["AAA-USDT", "BBB-USDT"],
            "initial_cash": 100.0,
            "rebalance_interval_hours": 1.0,
            "fee_rate": 0.001,
            "min_rebalance_notional": 0.0,
        },
        {
            "session_dir": candidate_dir,
            "symbols": ["AAA-USDT", "BBB-USDT"],
            "initial_cash": 100.0,
            "rebalance_interval_hours": 1.0,
            "fee_rate": 0.001,
            "min_rebalance_notional": 10.0,
        },
    ]

    results = paper_session.start_paired_sessions(specs)

    assert call_count["n"] == 1, "expected exactly one shared price fetch for the whole group"
    assert results[0]["entry_prices"] == results[1]["entry_prices"]
    assert results[0]["entry_time"] == results[1]["entry_time"], (
        "both sessions must be written from the same start_session call batch, "
        "not staggered independent starts"
    )


def test_start_paired_sessions_rejects_mismatched_symbol_sets(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        paper_session, "fetch_last_prices", lambda symbols: {s: 10.0 for s in symbols}
    )
    specs = [
        {
            "session_dir": tmp_path / "control",
            "symbols": ["AAA-USDT", "BBB-USDT"],
            "initial_cash": 100.0,
            "rebalance_interval_hours": 1.0,
        },
        {
            "session_dir": tmp_path / "candidate",
            "symbols": ["AAA-USDT", "CCC-USDT"],
            "initial_cash": 100.0,
            "rebalance_interval_hours": 1.0,
        },
    ]

    with pytest.raises(ValueError, match="same symbol set"):
        paper_session.start_paired_sessions(specs)

    # Fails fast -- no partially-started group left on disk.
    assert not (tmp_path / "control").exists()
    assert not (tmp_path / "candidate").exists()


def test_identical_policies_paired_produce_identical_ledgers(tmp_path, monkeypatch) -> None:
    """Two identically-configured sessions, driven by the same shared prices
    at every step, must end up bit-for-bit identical -- the deterministic-
    replay property a valid A/B comparison depends on. Any observed
    difference between differently-configured sessions run this way is then
    attributable to policy, not to quote timing."""
    entry_prices = {"AAA-USDT": 10.0, "BBB-USDT": 10.0}
    monkeypatch.setattr(paper_session, "fetch_last_prices", lambda symbols: entry_prices)

    dir_a = tmp_path / "replay_a"
    dir_b = tmp_path / "replay_b"
    spec = {
        "symbols": ["AAA-USDT", "BBB-USDT"],
        "initial_cash": 100.0,
        "rebalance_interval_hours": 1.0,
        "fee_rate": 0.01,
        "min_rebalance_notional": 0.0,
    }
    paper_session.start_paired_sessions(
        [{**spec, "session_dir": dir_a}, {**spec, "session_dir": dir_b}]
    )

    rebalance_prices = {"AAA-USDT": 20.0, "BBB-USDT": 10.0}
    rebalance_now = paper_session._now_iso()
    result_a = paper_session.rebalance_if_due(dir_a, force=True, prices=rebalance_prices, now=rebalance_now)
    result_b = paper_session.rebalance_if_due(dir_b, force=True, prices=rebalance_prices, now=rebalance_now)

    assert result_a["trades"] == result_b["trades"]
    assert result_a["mark"]["cash_remaining"] == result_b["mark"]["cash_remaining"]
    assert result_a["mark"]["equity"] == result_b["mark"]["equity"]

    book_a = paper_session._load_book(dir_a)
    book_b = paper_session._load_book(dir_b)
    assert book_a["positions"] == book_b["positions"]
    assert book_a["cash_remaining"] == book_b["cash_remaining"]


def test_run_paired_loop_shares_one_fetch_across_the_group(tmp_path, monkeypatch) -> None:
    """run_paired_loop must fetch once per tick and feed the same dict into
    every session's rebalance/mark call, not one fetch per session."""
    fetch_calls: list[list[str]] = []

    def fake_prices(symbols: list[str]) -> dict[str, float]:
        fetch_calls.append(list(symbols))
        return {s: 10.0 for s in symbols}

    monkeypatch.setattr(paper_session, "fetch_last_prices", fake_prices)

    dir_a = tmp_path / "loop_a"
    dir_b = tmp_path / "loop_b"
    spec = {
        "symbols": ["AAA-USDT", "BBB-USDT"],
        "initial_cash": 100.0,
        # Long interval so the loop's one tick takes the mark_once branch,
        # not rebalance -- isolates the fetch-sharing behavior from
        # rebalance-specific logic already covered above.
        "rebalance_interval_hours": 100.0,
        "fee_rate": 0.0,
        "min_rebalance_notional": 0.0,
    }
    paper_session.start_paired_sessions(
        [{**spec, "session_dir": dir_a}, {**spec, "session_dir": dir_b}]
    )
    fetch_calls.clear()  # drop the entry-quote fetch; only the loop tick matters here

    # A short future deadline guarantees exactly one tick executes before the
    # loop's own clock check exits it -- run_paired_loop checks "now < until"
    # only at the top of each iteration. poll_seconds must outlast the
    # deadline so the post-tick sleep pushes "now" past "until" before the
    # loop re-checks, instead of ticking again inside the same window.
    until_iso = (datetime.now(timezone.utc) + timedelta(milliseconds=200)).isoformat()
    paper_session.run_paired_loop([dir_a, dir_b], poll_seconds=1, until_iso=until_iso)

    assert len(fetch_calls) == 1, f"expected exactly one shared fetch per tick, got {len(fetch_calls)}"


def test_shadow_pair_wrapper_creates_identical_entry_receipts(tmp_path, monkeypatch) -> None:
    prices = {"AAA-USDT": 10.0, "BBB-USDT": 20.0}
    fetch_count = {"value": 0}

    def fake_prices(symbols: list[str]) -> dict[str, float]:
        fetch_count["value"] += 1
        return {symbol: prices[symbol] for symbol in symbols}

    monkeypatch.setattr(paper_session, "fetch_last_prices", fake_prices)
    control_dir = tmp_path / "control"
    candidate_dir = tmp_path / "candidate"

    sessions = shadow_ab_pair.ensure_paired_sessions(
        control_dir,
        candidate_dir,
        list(prices),
        100.0,
        1.0,
        0.001,
        10.0,
    )

    assert fetch_count["value"] == 1
    assert sessions[0]["entry_time"] == sessions[1]["entry_time"]
    assert sessions[0]["entry_prices"] == sessions[1]["entry_prices"]
    control_trades = paper_session._read_jsonl(control_dir / "trades.jsonl")
    candidate_trades = paper_session._read_jsonl(candidate_dir / "trades.jsonl")
    assert control_trades == candidate_trades
    control_marks = paper_session._read_jsonl(control_dir / "marks.jsonl")
    candidate_marks = paper_session._read_jsonl(candidate_dir / "marks.jsonl")
    assert control_marks == candidate_marks


def test_shadow_pair_wrapper_rejects_contaminated_existing_pair(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        paper_session,
        "fetch_last_prices",
        lambda symbols: {symbol: 10.0 for symbol in symbols},
    )
    control_dir = tmp_path / "control"
    candidate_dir = tmp_path / "candidate"
    args = (control_dir, candidate_dir, ["AAA-USDT"], 100.0, 1.0, 0.001, 10.0)
    shadow_ab_pair.ensure_paired_sessions(*args)
    candidate = json.loads((candidate_dir / "session.json").read_text(encoding="utf-8"))
    candidate["entry_time"] = "2026-01-01T00:00:00+00:00"
    (candidate_dir / "session.json").write_text(json.dumps(candidate), encoding="utf-8")

    with pytest.raises(RuntimeError, match="different entry timestamps"):
        shadow_ab_pair.ensure_paired_sessions(*args)


def test_shadow_pair_wrapper_rejects_half_created_pair(tmp_path) -> None:
    control_dir = tmp_path / "control"
    control_dir.mkdir()

    with pytest.raises(RuntimeError, match="both exist or both be absent"):
        shadow_ab_pair.ensure_paired_sessions(
            control_dir,
            tmp_path / "candidate",
            ["AAA-USDT"],
            100.0,
            1.0,
            0.001,
            10.0,
        )
