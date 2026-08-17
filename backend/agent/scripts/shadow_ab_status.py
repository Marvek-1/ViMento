"""One-shot status pull for the control vs. $10-candidate shadow A/B, across
all three rebalance-interval regimens (5m/10m/15m).

Read-only: calls compute_session_diagnostics on each of the 6 running
schema-v2 sessions and prints a compact comparison table. Safe to run at
any time without affecting the live sessions.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paper_session as ps

PAIRS = [
    ("5m", "shadow_ab_v1_control_5m_20260711_192538", "shadow_ab_v1_candidate10_5m_20260711_192538"),
    ("10m", "shadow_ab_v1_control_10m_20260711_192538", "shadow_ab_v1_candidate10_10m_20260711_192538"),
    ("15m", "shadow_ab_v1_control_20260711_185947", "shadow_ab_v1_candidate10_20260711_185947"),
]


def _row(session_id: str) -> dict:
    d = ps.compute_session_diagnostics(ps.SESSIONS_DIR / session_id)
    m = d["metrics"]
    return {
        "session_id": session_id,
        "reconciled": m["reconciled"],
        "equity": m["current_equity"],
        "net_return_pct": m["net_portfolio_pnl"] / m["initial_cash"] * 100,
        "trades": d["trade_count"],
        "fees": m["total_fees"],
        "max_dd_pct": m["max_drawdown"] * 100,
        "tracking_error_rms": m["tracking_error_rms"],
        "max_weight_drift": m["max_weight_drift"],
    }


def main() -> None:
    print(f"{'regimen':>7} {'arm':>12} {'reconciled':>10} {'net_ret%':>9} {'trades':>7} "
          f"{'fees':>8} {'max_dd%':>8} {'track_err':>10} {'max_drift':>10}")
    for label, control_id, candidate_id in PAIRS:
        control = _row(control_id)
        candidate = _row(candidate_id)
        for arm_name, r in (("control", control), (f"$10-cand", candidate)):
            te = f"{r['tracking_error_rms']:.6f}" if r["tracking_error_rms"] is not None else "n/a"
            print(f"{label:>7} {arm_name:>12} {str(r['reconciled']):>10} {r['net_return_pct']:9.4f} "
                  f"{r['trades']:7d} {r['fees']:8.4f} {r['max_dd_pct']:8.4f} {te:>10} "
                  f"{r['max_weight_drift']:10.6f}")
        diff = candidate["net_return_pct"] - control["net_return_pct"]
        print(f"{label:>7} {'candidate-control':>12} {'':>10} {diff:9.4f}")
        print()


if __name__ == "__main__":
    main()
