"""Regression coverage for start_session's two position-sizing modes.

fixed_margin_per_trade=50.0 briefly became DEFAULT_RISK_CONFIG's value,
silently switching every session that omits risk_config (production CLI
default, start_paired_sessions, and most of test_paper_session_accounting.py)
from equal-weight/spot sizing to leveraged fixed-margin futures sizing --
raising a new minimum-capital requirement and, because leverage=5.0 also
leaked into position_metadata for equal-weight positions, arming a synthetic
liquidation price on ordinary spot exposure. Fixed-margin sizing must stay
opt-in: DEFAULT_RISK_CONFIG.fixed_margin_per_trade == 0.0, matching the CLI's
own --fixed-margin default ("0 = use percentage sizing").
"""

from __future__ import annotations

import json

import pytest

import paper_session


def _fetch(prices: dict[str, float]):
    return lambda symbols: {s: prices[s] for s in symbols}


def test_default_session_uses_equal_weight_sizing_not_fixed_margin(tmp_path, monkeypatch) -> None:
    """No risk_config given -- must fall back to equal-weight/spot sizing,
    not silently reserve $50/leg of futures margin."""
    symbols = ["AAA-USDT", "BBB-USDT"]
    monkeypatch.setattr(paper_session, "fetch_last_prices", _fetch({s: 10.0 for s in symbols}))
    session_dir = tmp_path / "legacy_default"

    session = paper_session.start_session(
        session_dir, symbols, initial_cash=100.0, rebalance_interval_hours=1.0, fee_rate=0.0,
    )

    assert session["risk_config"]["fixed_margin_per_trade"] == 0.0
    book = paper_session._load_book(session_dir)
    # Equal-weight: all $100 split 2 ways at $10/unit -> 5 units each, no
    # margin reservation (spot, not futures).
    assert book["positions"]["AAA-USDT"] == pytest.approx(5.0)
    assert book["positions"]["BBB-USDT"] == pytest.approx(5.0)
    # Unleveraged: "reserved_margin" here is cost basis, not futures margin
    # -- with no leverage, margin == notional, so it equals the full $100
    # invested (nothing held back the way real futures margin would be).
    assert book["reserved_margin"] == pytest.approx(100.0)
    assert book["cash_remaining"] == pytest.approx(0.0, abs=1e-9)


def test_default_session_positions_have_no_leverage_liquidation_risk(tmp_path, monkeypatch) -> None:
    """Equal-weight positions must not inherit risk_config's futures leverage
    (5.0) as position metadata -- that arms a synthetic liquidation price a
    plain spot/equal-weight position was never meant to have."""
    symbols = ["AAA-USDT"]
    monkeypatch.setattr(paper_session, "fetch_last_prices", _fetch({"AAA-USDT": 10.0}))
    session_dir = tmp_path / "legacy_no_liq"
    paper_session.start_session(
        session_dir, symbols, initial_cash=100.0, rebalance_interval_hours=1.0, fee_rate=0.0,
    )

    book = paper_session._load_book(session_dir)
    meta = book["position_metadata"]["AAA-USDT"]
    assert meta["leverage"] == 1.0
    assert meta["liquidation_price"] == 0.0

    # A severe (50%) price drop must not trigger a "liquidation" risk exit
    # on an unleveraged equal-weight position.
    session = paper_session._load_session(session_dir)
    executed = paper_session._check_risk_exits(
        session, book, {"AAA-USDT": 5.0}, paper_session._now_iso(), session_dir,
    )
    assert executed == []


def test_explicit_fixed_margin_mode_sizes_leveraged_positions(tmp_path, monkeypatch) -> None:
    """Opting in via risk_config must still produce leveraged fixed-margin
    sizing -- this mode isn't being removed, only made opt-in."""
    symbols = ["AAA-USDT", "BBB-USDT"]
    monkeypatch.setattr(paper_session, "fetch_last_prices", _fetch({s: 10.0 for s in symbols}))
    session_dir = tmp_path / "explicit_futures"

    session = paper_session.start_session(
        session_dir, symbols, initial_cash=200.0, rebalance_interval_hours=1.0, fee_rate=0.0,
        risk_config={"fixed_margin_per_trade": 50.0, "leverage": 5.0},
    )

    assert session["risk_config"]["fixed_margin_per_trade"] == 50.0
    book = paper_session._load_book(session_dir)
    # notional per leg = margin * leverage = 50 * 5 = 250 -> 25 units at $10.
    assert book["positions"]["AAA-USDT"] == pytest.approx(25.0)
    assert book["reserved_margin"] == pytest.approx(100.0)  # 50 margin x 2 legs
    meta = book["position_metadata"]["AAA-USDT"]
    assert meta["leverage"] == 5.0
    assert meta["liquidation_price"] > 0.0


def test_explicit_fixed_margin_rejects_insufficient_cash(tmp_path, monkeypatch) -> None:
    symbols = ["AAA-USDT", "BBB-USDT"]
    monkeypatch.setattr(paper_session, "fetch_last_prices", _fetch({s: 10.0 for s in symbols}))
    session_dir = tmp_path / "explicit_futures_underfunded"

    with pytest.raises(ValueError, match="insufficient initial cash"):
        paper_session.start_session(
            session_dir, symbols, initial_cash=90.0, rebalance_interval_hours=1.0, fee_rate=0.0,
            risk_config={"fixed_margin_per_trade": 50.0, "leverage": 5.0},
        )
    # Fails before any receipted write -- no session.json left behind.
    assert not (session_dir / "session.json").exists()


def test_explicit_fixed_margin_accepts_exact_boundary_cash(tmp_path, monkeypatch) -> None:
    """required_cash > initial_cash is the rejection condition -- cash equal
    to the requirement (not merely close to it) must be accepted."""
    symbols = ["AAA-USDT", "BBB-USDT"]
    monkeypatch.setattr(paper_session, "fetch_last_prices", _fetch({s: 10.0 for s in symbols}))
    session_dir = tmp_path / "explicit_futures_exact"

    session = paper_session.start_session(
        session_dir, symbols, initial_cash=100.0, rebalance_interval_hours=1.0, fee_rate=0.0,
        risk_config={"fixed_margin_per_trade": 50.0, "leverage": 5.0},
    )
    assert session["risk_config"]["fixed_margin_per_trade"] == 50.0
    book = paper_session._load_book(session_dir)
    assert book["cash_remaining"] == pytest.approx(0.0, abs=1e-9)


def test_explicit_fixed_margin_multiple_positions_reserve_margin_per_leg(tmp_path, monkeypatch) -> None:
    symbols = ["AAA-USDT", "BBB-USDT", "CCC-USDT"]
    monkeypatch.setattr(paper_session, "fetch_last_prices", _fetch({s: 20.0 for s in symbols}))
    session_dir = tmp_path / "explicit_futures_multi"

    session = paper_session.start_session(
        session_dir, symbols, initial_cash=300.0, rebalance_interval_hours=1.0, fee_rate=0.0,
        risk_config={"fixed_margin_per_trade": 50.0, "leverage": 5.0},
    )
    assert session["risk_config"]["fixed_margin_per_trade"] == 50.0
    book = paper_session._load_book(session_dir)
    for code in symbols:
        assert book["positions"][code] == pytest.approx(12.5)  # (50*5)/20
        assert book["position_metadata"][code]["margin"] == pytest.approx(50.0)
    assert book["reserved_margin"] == pytest.approx(150.0)  # 50 * 3 legs
    assert book["cash_remaining"] == pytest.approx(150.0)  # 300 - 150 margin, no fees


def test_explicit_fixed_margin_reserves_fee_budget_alongside_margin(tmp_path, monkeypatch) -> None:
    """required_cash must cover both the margin and the entry fee on the
    full (leveraged) notional, per leg -- not margin alone."""
    symbols = ["AAA-USDT", "BBB-USDT"]
    monkeypatch.setattr(paper_session, "fetch_last_prices", _fetch({s: 10.0 for s in symbols}))
    session_dir = tmp_path / "explicit_futures_fees"

    # margin=50, leverage=5 -> notional=250/leg, fee_rate=0.01 -> fee=2.5/leg
    # required = (50 + 2.5) * 2 = 105
    with pytest.raises(ValueError, match="insufficient initial cash"):
        paper_session.start_session(
            session_dir, symbols, initial_cash=104.0, rebalance_interval_hours=1.0, fee_rate=0.01,
            risk_config={"fixed_margin_per_trade": 50.0, "leverage": 5.0},
        )

    session_dir_ok = session_dir.with_name("explicit_futures_fees_ok")
    session = paper_session.start_session(
        session_dir_ok, symbols, initial_cash=105.0, rebalance_interval_hours=1.0, fee_rate=0.01,
        risk_config={"fixed_margin_per_trade": 50.0, "leverage": 5.0},
    )
    book = paper_session._load_book(session_dir_ok)
    assert book["cash_remaining"] == pytest.approx(0.0, abs=1e-9)
    assert book["reserved_margin"] == pytest.approx(100.0)


def test_session_reload_preserves_configured_margin_mode(tmp_path, monkeypatch) -> None:
    """risk_config written at start_session time must survive a disk
    round-trip unchanged -- a reload must not quietly fall back to the
    module default for an explicitly-configured session."""
    symbols = ["AAA-USDT"]
    monkeypatch.setattr(paper_session, "fetch_last_prices", _fetch({"AAA-USDT": 10.0}))
    session_dir = tmp_path / "reload_futures"
    paper_session.start_session(
        session_dir, symbols, initial_cash=100.0, rebalance_interval_hours=1.0, fee_rate=0.0,
        risk_config={"fixed_margin_per_trade": 30.0, "leverage": 10.0, "margin_mode": "cross"},
    )

    reloaded = paper_session._load_session(session_dir)
    assert reloaded["risk_config"]["fixed_margin_per_trade"] == 30.0
    assert reloaded["risk_config"]["leverage"] == 10.0
    assert reloaded["risk_config"]["margin_mode"] == "cross"

    # And a legacy/default session must likewise round-trip its (disabled)
    # fixed-margin mode rather than drift to some other value on reload.
    legacy_dir = tmp_path / "reload_legacy"
    paper_session.start_session(
        legacy_dir, symbols, initial_cash=100.0, rebalance_interval_hours=1.0, fee_rate=0.0,
    )
    reloaded_legacy = paper_session._load_session(legacy_dir)
    assert reloaded_legacy["risk_config"]["fixed_margin_per_trade"] == 0.0


def test_fixed_margin_between_zero_and_twenty_is_still_rejected(tmp_path, monkeypatch) -> None:
    """0 (disabled) is a valid escape hatch, but a misconfigured nonzero
    value below the $20 floor must still fail loudly, not silently clamp."""
    symbols = ["AAA-USDT"]
    monkeypatch.setattr(paper_session, "fetch_last_prices", _fetch({"AAA-USDT": 10.0}))
    session_dir = tmp_path / "bad_margin_config"

    with pytest.raises(ValueError, match="fixed_margin_per_trade must be 0"):
        paper_session.start_session(
            session_dir, symbols, initial_cash=100.0, rebalance_interval_hours=1.0, fee_rate=0.0,
            risk_config={"fixed_margin_per_trade": 10.0, "leverage": 5.0},
        )


@pytest.mark.parametrize("leverage", [1.0, 5.0, 10.0])
def test_portfolio_leverage_uses_full_account_and_reports_true_equity(
    tmp_path, monkeypatch, leverage
) -> None:
    symbols = ["AAA-USDT", "BBB-USDT"]
    prices = {s: 10.0 for s in symbols}
    monkeypatch.setattr(paper_session, "fetch_last_prices", _fetch(prices))
    session_dir = tmp_path / f"portfolio_{leverage:g}x"

    paper_session.start_session(
        session_dir, symbols, initial_cash=1000.0, rebalance_interval_hours=1.0,
        fee_rate=0.001,
        risk_config={
            "leverage": leverage,
            "portfolio_leverage": True,
            "liquidation_buffer_pct": 0.005,
        },
    )

    book = paper_session._load_book(session_dir)
    mark = json.loads((session_dir / "marks.jsonl").read_text().splitlines()[-1])
    assert mark["open_notional"] / mark["equity"] == pytest.approx(leverage)
    assert mark["equity"] == pytest.approx(
        book["cash_remaining"] + book["reserved_margin"]
    )
    assert mark["equity"] < 1000.0  # entry fees are charged on leveraged notional
    for meta in book["position_metadata"].values():
        assert meta["leverage"] == leverage
        if leverage == 1.0:
            assert meta["liquidation_price"] == 0.0
        else:
            assert 0.0 < meta["liquidation_price"] < 10.0


def test_portfolio_leverage_rebalance_releases_and_reserves_margin(
    tmp_path, monkeypatch
) -> None:
    symbols = ["AAA-USDT", "BBB-USDT"]
    monkeypatch.setattr(
        paper_session, "fetch_last_prices", _fetch({s: 10.0 for s in symbols})
    )
    session_dir = tmp_path / "portfolio_5x_rebalance"
    paper_session.start_session(
        session_dir, symbols, initial_cash=1000.0, rebalance_interval_hours=1.0,
        fee_rate=0.001,
        risk_config={
            "leverage": 5.0,
            "portfolio_leverage": True,
            "liquidation_buffer_pct": 0.005,
        },
    )

    result = paper_session.rebalance_if_due(
        session_dir, force=True,
        prices={"AAA-USDT": 11.0, "BBB-USDT": 9.0},
        now=paper_session._now_iso(),
    )
    assert result is not None
    assert result["mark"]["leverage"] == 5.0
    assert result["mark"]["open_notional"] / result["mark"]["equity"] == pytest.approx(
        5.0, rel=0.02
    )
    assert paper_session._load_session(session_dir)["accounting_status"] == "OK"
