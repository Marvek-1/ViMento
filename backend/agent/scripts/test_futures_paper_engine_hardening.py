#!/usr/bin/env python3
"""Hardening validation pack: cross-margin rejection, funding idempotency,
validate-before-persist, cross-process writer lease, pure snapshot reads.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from futures_paper_engine import (
    FuturesPaperEngine,
    RiskConfig,
    WriterLockError,
    funding_event_id,
)


def approx(a: float, b: float, tol: float = 1e-6) -> None:
    assert abs(a - b) <= tol, (a, b)


def run() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        # 1. Cross mode rejected
        engine = FuturesPaperEngine(root / "cross_test", initial_balance=10_000)
        try:
            engine.open_position(
                "BTCUSDT", "long", price=100.0,
                risk=RiskConfig(margin_mode="cross", margin=20, leverage=5),
            )
            raise AssertionError("expected cross margin rejection")
        except ValueError as exc:
            assert "cross margin is not implemented" in str(exc)
        engine.close()

        # 2. Funding duplicate rejected after "process restart"
        session = root / "funding_test"
        engine = FuturesPaperEngine(session, initial_balance=10_000)
        pos = engine.open_position(
            "ETHUSDT", "long", price=100.0,
            risk=RiskConfig(margin=50, leverage=5, take_profit_pct=0.05, stop_loss_pct=0.03),
        )
        event_id = funding_event_id("ETHUSDT", "2026-07-25T08:00:00Z")
        first = engine.apply_funding(pos.trade_id, 0.0002, event_id=event_id)
        assert first != 0.0
        wallet_after_first = engine.state.wallet_balance
        engine.close()

        # simulate a PM2 restart: new engine instance loads persisted state
        engine = FuturesPaperEngine(session, initial_balance=10_000)
        replay = engine.apply_funding(pos.trade_id, 0.0002, event_id=event_id)
        assert replay == 0.0, "duplicate funding event must be a no-op"
        approx(engine.state.wallet_balance, wallet_after_first)
        engine.close()

        # 3. Failed invariant leaves disk state unchanged
        session2 = root / "invariant_test"
        engine = FuturesPaperEngine(session2, initial_balance=10_000)
        pos2 = engine.open_position(
            "BTCUSDT", "long", price=100.0,
            risk=RiskConfig(margin=50, leverage=5, take_profit_pct=0.05, stop_loss_pct=0.03),
        )
        before_disk = json.loads(engine.state_path.read_text())
        before_reserved = engine.state.reserved_margin
        # Corrupt reserved_margin directly on the live state, then attempt a
        # mutation; _commit must validate the clone before persisting/publishing.
        engine.state.reserved_margin = -999.0
        try:
            engine.close_position(pos2.trade_id, price=101.0, exit_reason="manual")
            raise AssertionError("expected invariant violation to block commit")
        except AssertionError as exc:
            assert "reserved margin" in str(exc) or "cannot be negative" in str(exc)
        after_disk = json.loads(engine.state_path.read_text())
        assert after_disk == before_disk, "disk must not change when validation fails"
        # engine.state itself was intentionally corrupted above by the test to
        # prove _commit never persisted it; restore for cleanliness.
        engine.state.reserved_margin = before_reserved
        engine.close()

        # 4. Second process writer rejected
        session3 = root / "writer_lock_test"
        engine_a = FuturesPaperEngine(session3, initial_balance=10_000)
        try:
            FuturesPaperEngine(session3, initial_balance=10_000)
            raise AssertionError("expected second writer to be rejected")
        except WriterLockError:
            pass
        engine_a.close()
        # after release, a new writer may acquire the lease
        engine_b = FuturesPaperEngine(session3, initial_balance=10_000)
        engine_b.close()

        # 5. Snapshot read produces no files or ledger rows
        session4 = root / "pure_read_test"
        engine = FuturesPaperEngine(session4, initial_balance=10_000)
        engine.open_position(
            "SOLUSDT", "long", price=100.0,
            risk=RiskConfig(margin=50, leverage=5, take_profit_pct=0.05, stop_loss_pct=0.03),
        )
        marks_before = engine.marks_path.read_text() if engine.marks_path.exists() else ""
        for _ in range(5):
            engine.account_summary({"SOLUSDT": 101.0})
            engine.snapshot({"SOLUSDT": 101.0})
        marks_after = engine.marks_path.read_text() if engine.marks_path.exists() else ""
        assert marks_before == marks_after == "", "pure reads must not write marks.jsonl"
        # explicit record_mark is the only path that appends
        engine.record_mark({"SOLUSDT": 101.0})
        assert engine.marks_path.exists()
        assert len(engine.marks_path.read_text().splitlines()) == 1
        engine.close()

        # 6. 5x reserves $20 margin and creates $100 notional
        session5 = root / "five_x_test"
        engine = FuturesPaperEngine(session5, initial_balance=10_000)
        p5 = engine.open_position(
            "BNBUSDT", "long", price=100.0,
            risk=RiskConfig(margin=20, leverage=5, take_profit_pct=0.05, stop_loss_pct=0.03),
        )
        approx(engine.state.reserved_margin, 20.0)
        approx(p5.notional, 100.0)
        engine.close()

        # 7. 10x reserves $20 margin and creates $200 notional
        session6 = root / "ten_x_test"
        engine = FuturesPaperEngine(session6, initial_balance=10_000)
        p6 = engine.open_position(
            "BNBUSDT", "long", price=100.0,
            risk=RiskConfig(margin=20, leverage=10, take_profit_pct=0.05, stop_loss_pct=0.03),
        )
        approx(engine.state.reserved_margin, 20.0)
        approx(p6.notional, 200.0)
        engine.close()

        # 8. Account A cannot change account B
        session_a = root / "account_a"
        session_b = root / "account_b"
        engine_a = FuturesPaperEngine(session_a, initial_balance=5_000)
        engine_b = FuturesPaperEngine(session_b, initial_balance=9_000)
        engine_a.open_position(
            "BTCUSDT", "long", price=100.0,
            risk=RiskConfig(margin=50, leverage=5, take_profit_pct=0.05, stop_loss_pct=0.03),
        )
        assert engine_b.state.wallet_balance == 9_000
        assert engine_b.state.reserved_margin == 0.0
        engine_a.close()
        engine_b.close()

        # 9. PM2 restart preserves open positions and funding-event history
        session7 = root / "restart_test"
        engine = FuturesPaperEngine(session7, initial_balance=10_000)
        pos7 = engine.open_position(
            "XRPUSDT", "long", price=1.0,
            risk=RiskConfig(margin=20, leverage=5, take_profit_pct=0.05, stop_loss_pct=0.03),
        )
        eid = funding_event_id("XRPUSDT", "2026-07-25T00:00:00Z")
        engine.apply_funding(pos7.trade_id, 0.0001, event_id=eid)
        engine.close()

        reloaded = FuturesPaperEngine(session7, initial_balance=10_000)
        assert pos7.trade_id in reloaded.state.positions
        assert eid in reloaded.state.applied_funding_event_ids
        replay2 = reloaded.apply_funding(pos7.trade_id, 0.0001, event_id=eid)
        assert replay2 == 0.0
        reloaded.close()

    print("All futures engine hardening tests passed.")


if __name__ == "__main__":
    run()
