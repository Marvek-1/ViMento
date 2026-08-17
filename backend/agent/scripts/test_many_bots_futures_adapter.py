#!/usr/bin/env python3
"""Validation pack for many_bots_futures_adapter.py."""

from __future__ import annotations

import tempfile
from pathlib import Path

from futures_paper_engine import FuturesPaperEngine
from many_bots_futures_adapter import (
    ManyBotsFuturesAdapter,
    StalePriceError,
    load_frozen_universe,
)
from universe_frozen_canary8 import write as write_universe


def run() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        universe_path = root / "universe.json"
        write_universe(universe_path)
        assert len(load_frozen_universe(universe_path)) == 8

        # 1. Duplicate strategy intent is rejected (a second apply of the
        #    same intent_id is a no-op, not a second open).
        engine = FuturesPaperEngine(root / "acct1", initial_balance=10_000)
        adapter = ManyBotsFuturesAdapter(
            engine, account_id="acct1", universe_path=universe_path, leverage=5, margin=20.0,
        )
        intent = adapter.build_intent("BTC-USDT", "OPEN_LONG", timestamp="2026-07-25T00:00:00Z", reason="test")
        trade_id_1 = adapter.apply_intent(intent, price=100.0)
        assert trade_id_1 is not None
        assert len(engine.state.positions) == 1
        trade_id_2 = adapter.apply_intent(intent)
        assert trade_id_2 is None, "duplicate intent must be a no-op"
        assert len(engine.state.positions) == 1
        engine.close()

        # 2. Adapter survives "restart": duplicate rejection persists across
        #    a fresh adapter/engine instance reading the same ledger file.
        engine = FuturesPaperEngine(root / "acct1", initial_balance=10_000, acquire_lock=False)
        adapter2 = ManyBotsFuturesAdapter(
            engine, account_id="acct1", universe_path=universe_path, leverage=5, margin=20.0,
        )
        replay = adapter2.apply_intent(intent)
        assert replay is None, "duplicate intent must stay rejected after restart"
        assert len(engine.state.positions) == 1
        engine.close()

        # 3. One open position per symbol: a second OPEN_LONG intent (new
        #    intent_id, same symbol) is a no-op while a position is open.
        engine = FuturesPaperEngine(root / "acct2", initial_balance=10_000)
        adapter3 = ManyBotsFuturesAdapter(
            engine, account_id="acct2", universe_path=universe_path, leverage=5, margin=20.0,
        )
        i1 = adapter3.build_intent("ETH-USDT", "OPEN_LONG", timestamp="2026-07-25T00:00:00Z", reason="a")
        i2 = adapter3.build_intent("ETH-USDT", "OPEN_LONG", timestamp="2026-07-25T00:05:00Z", reason="b")
        assert i1.intent_id != i2.intent_id
        assert adapter3.apply_intent(i1, price=100.0) is not None
        assert adapter3.apply_intent(i2) is None, "must not open a second position on the same symbol"
        assert len(engine.state.positions) == 1
        engine.close()

        # 4. Unsupported/stale symbol: on_price_tick fails before mutation if
        #    the frozen universe is not fully priced.
        engine = FuturesPaperEngine(root / "acct3", initial_balance=10_000)
        adapter4 = ManyBotsFuturesAdapter(
            engine, account_id="acct3", universe_path=universe_path, leverage=5, margin=20.0,
        )
        incomplete_prices = {"BTCUSDT": 100.0}  # missing 7 of 8 frozen symbols
        try:
            adapter4.on_price_tick(incomplete_prices, timestamp="2026-07-25T00:00:00Z")
            raise AssertionError("expected StalePriceError on incomplete price snapshot")
        except StalePriceError:
            pass
        assert len(engine.state.positions) == 0, "no position may open from a partial snapshot"
        engine.close()

        # 5. A symbol outside the frozen universe is refused even with a
        #    hand-built intent (defense in depth beyond on_price_tick).
        engine = FuturesPaperEngine(root / "acct4", initial_balance=10_000)
        adapter5 = ManyBotsFuturesAdapter(
            engine, account_id="acct4", universe_path=universe_path, leverage=5, margin=20.0,
        )
        rogue = adapter5.build_intent("SHIB-USDT", "OPEN_LONG", timestamp="2026-07-25T00:00:00Z", reason="rogue")
        try:
            adapter5.apply_intent(rogue)
            raise AssertionError("expected rejection of a symbol outside the frozen universe")
        except RuntimeError as exc:
            assert "not in the frozen universe" in str(exc)
        engine.close()

    print("All many_bots_futures_adapter tests passed.")


if __name__ == "__main__":
    run()
