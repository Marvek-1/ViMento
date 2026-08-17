from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest


class RecoveryToolTests(unittest.TestCase):
    def _load_recovery_module(self, *, trade_qty: float = 1.0):
        fake = types.ModuleType("paper_session")
        fake.RECONCILIATION_ABS_TOLERANCE = 1e-6
        fake.RECONCILIATION_REL_TOLERANCE = 1e-9

        def verify_receipted_file(path: Path) -> bool:
            return path.exists()

        def _load_session(session_dir: Path):
            return json.loads((session_dir / "session.json").read_text())

        def _load_book(session_dir: Path):
            return json.loads((session_dir / "book.json").read_text())

        def _read_jsonl(path: Path):
            return []

        def compute_trade_stats(trades):
            return {
                "overall": {"realized_pnl": 0.0},
                "by_symbol": {
                    "A": {
                        "open_qty": trade_qty,
                        "avg_cost": 100.0,
                        "entry_fee_basis": 0.0,
                    }
                },
            }

        def fetch_last_prices(symbols):
            return {"A": 100.0}

        def _build_mark(session, book, prices, now=None):
            equity = float(book["cash_remaining"]) + (
                float(book["positions"]["A"]) * float(prices["A"])
            )
            return {"timestamp": now, "prices": prices, "equity": equity}

        def _compute_unrealized_position_pnl(by_symbol, prices):
            stats = by_symbol["A"]
            market = stats["open_qty"] * prices["A"]
            cost = stats["open_qty"] * stats["avg_cost"]
            return {
                "unrealized_pnl": market - cost,
                "stale_mark_symbols": [],
            }

        def receipted_write(path: Path, content: str):
            path.write_text(content, encoding="utf-8")
            path.with_suffix(path.suffix + ".hash").write_text("test", encoding="utf-8")

        def _mirror_session_to_store(session_id, session):
            return None

        def _append_jsonl(path: Path, record):
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            path.write_text(existing + json.dumps(record) + "\n", encoding="utf-8")

        fake.verify_receipted_file = verify_receipted_file
        fake._load_session = _load_session
        fake._load_book = _load_book
        fake._read_jsonl = _read_jsonl
        fake.compute_trade_stats = compute_trade_stats
        fake.fetch_last_prices = fetch_last_prices
        fake._build_mark = _build_mark
        fake._compute_unrealized_position_pnl = _compute_unrealized_position_pnl
        fake.receipted_write = receipted_write
        fake._mirror_session_to_store = _mirror_session_to_store
        fake._append_jsonl = _append_jsonl

        previous = sys.modules.get("paper_session")
        sys.modules["paper_session"] = fake
        try:
            path = Path(__file__).resolve().parents[1] / "tools" / "recover_paper_sessions.py"
            spec = importlib.util.spec_from_file_location("recovery_under_test", path)
            module = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(module)
            return module
        finally:
            if previous is None:
                sys.modules.pop("paper_session", None)
            else:
                sys.modules["paper_session"] = previous

    def _session_dir(self, base: Path) -> Path:
        session_dir = base / "frozen"
        session_dir.mkdir()
        (session_dir / "session.json").write_text(
            json.dumps(
                {
                    "symbols": ["A"],
                    "initial_cash": 100.0,
                    "accounting_status": "ACCOUNTING_ERROR",
                    "accounting_error": -100.0,
                }
            ),
            encoding="utf-8",
        )
        (session_dir / "book.json").write_text(
            json.dumps({"positions": {"A": 1.0}, "cash_remaining": 0.0}),
            encoding="utf-8",
        )
        return session_dir

    def test_recovery_is_dry_run_by_default(self) -> None:
        module = self._load_recovery_module()
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = self._session_dir(Path(tmp))
            report = module.recover(session_dir, apply=False)
            self.assertEqual(report["action"], "WOULD_UNFREEZE")
            persisted = json.loads((session_dir / "session.json").read_text())
            self.assertEqual(persisted["accounting_status"], "ACCOUNTING_ERROR")

    def test_recovery_refuses_position_mismatch(self) -> None:
        module = self._load_recovery_module(trade_qty=0.0)
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = self._session_dir(Path(tmp))
            report = module.recover(session_dir, apply=True)
            self.assertEqual(report["action"], "REFUSED")
            self.assertEqual(
                report["decision"]["reason"],
                "POSITION_LEDGER_MISMATCH",
            )


if __name__ == "__main__":
    unittest.main()
