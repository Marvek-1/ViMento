"""Rebuild paper-session cash/equity from the immutable trade ledger.

The live cash ledger (``book.json``/``marks.jsonl``) can drift from what
``trades.jsonl`` actually implies -- see the ``demo_10k_8pair_15m_*``
session, where ``cash_remaining`` tracked only cumulative fees and never
applied trade notional, understating equity by ~$900. ``trades.jsonl``
itself (side/qty/price/notional/fee_paid per execution) is the append-only,
receipted source of truth; this module replays it from ``initial_cash``
to reconstruct what cash/positions/equity *should* have been, independent
of whatever ``book.json``/``marks.jsonl`` happened to record.

Never mutates the original session directory -- outputs go to a sibling
``paper_sessions_reconstructed/<session_id>/`` tree so the original,
possibly-tainted evidence is preserved untouched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from write_receipt import receipted_write  # agent/write_receipt.py, top-level module

import paper_session as ps

RECONSTRUCTED_ROOT = Path(__file__).resolve().parent / "paper_sessions_reconstructed"

VALID = "VALID"
RECONSTRUCTABLE = "RECONSTRUCTABLE"
TAINTED_UNUSABLE = "TAINTED_UNUSABLE"

POSITION_QTY_TOLERANCE = 1e-6


def reconstruct_session(session_dir: Path) -> dict[str, Any]:
    """Replay trades.jsonl from initial_cash, independent of book.json/marks.jsonl.

    Reuses each original mark's ``timestamp``/``prices`` (market data, not
    ledger state, so untainted by the cash bug) but recomputes
    ``cash_remaining``/``position_values``/``equity`` at that instant from
    a from-scratch trade replay. Any trades whose timestamp falls after the
    last original mark are still applied to the running state so the final
    reconstructed book reflects every trade, then one trailing mark is
    appended using the last available prices.
    """
    session = ps._load_session(session_dir)
    trades = ps._read_jsonl(session_dir / "trades.jsonl")
    original_marks = ps._read_jsonl(session_dir / "marks.jsonl")
    initial_cash = float(session["initial_cash"])
    symbols = session["symbols"]

    cash = initial_cash
    positions = {code: 0.0 for code in symbols}
    trade_idx = 0
    reconstructed_marks: list[dict[str, Any]] = []
    last_prices: dict[str, float] = {}

    def apply_trade(t: dict[str, Any]) -> None:
        nonlocal cash
        signed_notional = t["notional"] if t["side"] == "BUY" else -t["notional"]
        signed_qty = t["qty"] if t["side"] == "BUY" else -t["qty"]
        positions[t["symbol"]] = positions.get(t["symbol"], 0.0) + signed_qty
        cash -= signed_notional + (t.get("fee_paid", 0.0) or 0.0)

    for mark in original_marks:
        ts = mark["timestamp"]
        while trade_idx < len(trades) and trades[trade_idx]["timestamp"] <= ts:
            apply_trade(trades[trade_idx])
            trade_idx += 1
        prices = mark.get("prices") or {}
        last_prices = prices or last_prices
        position_values = {code: positions[code] * prices[code] for code in symbols if code in prices}
        equity = cash + sum(position_values.values())
        reconstructed_marks.append({
            "timestamp": ts,
            "prices": prices,
            "position_values": position_values,
            "cash_remaining": cash,
            "equity": equity,
            "pnl": equity - initial_cash,
            "pnl_pct": (equity - initial_cash) / initial_cash if initial_cash else 0.0,
        })

    # Any trades logged after the last original mark still need to land in
    # the reconstructed book, even though there's no later mark to anchor a
    # price snapshot to -- use the last known prices rather than dropping them.
    trailing_applied = False
    while trade_idx < len(trades):
        apply_trade(trades[trade_idx])
        trade_idx += 1
        trailing_applied = True

    if trailing_applied and last_prices:
        position_values = {code: positions[code] * last_prices[code] for code in symbols if code in last_prices}
        equity = cash + sum(position_values.values())
        reconstructed_marks.append({
            "timestamp": trades[-1]["timestamp"],
            "prices": last_prices,
            "position_values": position_values,
            "cash_remaining": cash,
            "equity": equity,
            "pnl": equity - initial_cash,
            "pnl_pct": (equity - initial_cash) / initial_cash if initial_cash else 0.0,
        })

    reconstructed_book = {
        "positions": positions,
        "cash_remaining": cash,
        "last_rebalance_time": trades[-1]["timestamp"] if trades else session.get("entry_time"),
    }

    original_book = ps._load_book(session_dir)
    position_gaps = {
        code: positions[code] - original_book["positions"].get(code, 0.0)
        for code in symbols
        if abs(positions[code] - original_book["positions"].get(code, 0.0)) > POSITION_QTY_TOLERANCE
    }

    return {
        "session": session,
        "trades": trades,
        "book": reconstructed_book,
        "marks": reconstructed_marks,
        "position_gaps": position_gaps,
    }


def classify_session(session_dir: Path) -> dict[str, Any]:
    """Classify a session as VALID, RECONSTRUCTABLE, or TAINTED_UNUSABLE.

    VALID: the original ledger already reconciles -- no repair needed.
    RECONSTRUCTABLE: the original doesn't reconcile, but a from-scratch
        trade replay does (positions match the original book, and the
        reconstructed equity/realized/unrealized identity closes).
    TAINTED_UNUSABLE: even the reconstruction doesn't reconcile, or the
        trade ledger is incomplete (position mismatch vs. book.json,
        meaning trades.jsonl doesn't fully explain the session's state).
    """
    original_diag = ps.compute_session_diagnostics(session_dir)
    original_reconciled = bool(original_diag["metrics"]["reconciled"])

    reconstruction = reconstruct_session(session_dir)
    if reconstruction["position_gaps"]:
        return {
            "session_id": session_dir.name,
            "status": TAINTED_UNUSABLE,
            "reason": (
                "trade ledger does not fully explain book.json positions -- "
                f"gaps: {reconstruction['position_gaps']}"
            ),
            "original_diagnostics": original_diag,
            "reconstruction": reconstruction,
        }

    recon_diag = ps.compute_session_diagnostics(
        session_dir,
        session=reconstruction["session"],
        book=reconstruction["book"],
        marks=reconstruction["marks"],
        trades=reconstruction["trades"],
    )
    reconstructed_reconciled = bool(recon_diag["metrics"]["reconciled"])

    if original_reconciled:
        status = VALID
    elif reconstructed_reconciled:
        status = RECONSTRUCTABLE
    else:
        status = TAINTED_UNUSABLE

    return {
        "session_id": session_dir.name,
        "status": status,
        "original_diagnostics": original_diag,
        "reconstructed_diagnostics": recon_diag,
        "reconstruction": reconstruction,
    }


def write_reconstruction(session_dir: Path, output_root: Path = RECONSTRUCTED_ROOT) -> dict[str, Any]:
    """Classify a session and, if not already VALID, write repaired artifacts.

    Writes ``reconstructed_book.json``, ``reconstructed_marks.jsonl``,
    ``diagnostics.json``, and ``reconciliation_report.json`` under
    ``output_root/<session_id>/`` -- the original session_dir is never
    written to.
    """
    result = classify_session(session_dir)
    out_dir = output_root / session_dir.name
    out_dir.mkdir(parents=True, exist_ok=True)

    original_metrics = result["original_diagnostics"]["metrics"]
    report = {
        "session_id": session_dir.name,
        "status": result["status"],
        "original_reconciled": original_metrics["reconciled"],
        "original_final_equity": original_metrics["current_equity"],
        "original_reconciliation_error": original_metrics["reconciliation_error"],
    }

    if result["status"] == TAINTED_UNUSABLE and "reconstructed_diagnostics" not in result:
        report["taint_reason"] = result["reason"]
        (out_dir / "reconciliation_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report

    reconstruction = result["reconstruction"]
    recon_metrics = result["reconstructed_diagnostics"]["metrics"]

    receipted_write(out_dir / "reconstructed_book.json", json.dumps(reconstruction["book"], indent=2))
    receipted_write(
        out_dir / "reconstructed_marks.jsonl",
        "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in reconstruction["marks"]),
    )
    receipted_write(out_dir / "diagnostics.json", json.dumps(result["reconstructed_diagnostics"], indent=2))

    report.update({
        "reconstructed_reconciled": recon_metrics["reconciled"],
        "reconstructed_final_equity": recon_metrics["current_equity"],
        "reconstructed_reconciliation_error": recon_metrics["reconciliation_error"],
        "cash_ledger_gap": recon_metrics["current_equity"] - original_metrics["current_equity"],
        "taint_reason": "historical cash ledger excluded trade notional" if result["status"] != VALID else None,
    })
    receipted_write(out_dir / "reconciliation_report.json", json.dumps(report, indent=2))
    return report


def batch_reconcile(sessions_dir: Path, output_root: Path = RECONSTRUCTED_ROOT) -> list[dict[str, Any]]:
    reports = []
    for session_dir in sorted(p for p in sessions_dir.iterdir() if p.is_dir()):
        reports.append(write_reconstruction(session_dir, output_root))
    return reports


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions-dir", default=str(ps.SESSIONS_DIR))
    parser.add_argument("--output-root", default=str(RECONSTRUCTED_ROOT))
    args = parser.parse_args()

    reports = batch_reconcile(Path(args.sessions_dir), Path(args.output_root))
    print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    _cli()
