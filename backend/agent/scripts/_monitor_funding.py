#!/usr/bin/env python3
"""Quick monitor for all paper trading sessions."""
import json
import subprocess
import urllib.request
from pathlib import Path

SESSIONS_DIR = Path(__file__).parent / "paper_sessions"
API_URL = "http://127.0.0.1:8787/api/portfolio"

def last_n_lines(path: Path, n: int = 3) -> list[str]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        lines = f.readlines()
    return [line.strip() for line in lines[-n:] if line.strip()]

def main() -> None:
    print("=" * 60)
    print("Paper Trading Sessions Monitor")
    print("=" * 60)

    print("\n--- Running tmux sessions ---")
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name} | #{session_created}"],
            capture_output=True, text=True, check=True,
        )
        for line in result.stdout.strip().splitlines():
            print(line)
    except Exception as e:
        print(f"tmux not available or no sessions: {e}")

    print(f"\nAPI: {API_URL}")
    try:
        req = urllib.request.Request(API_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode())
        account = data.get("account", {})
        tabs = data.get("tabs", [])
        if not tabs:
            print("No strategy tabs returned by API")
        for tab in tabs:
            print(f"\n  Strategy: {tab.get('tab', '—')}")
            print(f"    Equity:    ${account.get('current_equity', 0):,.2f}")
            print(f"    P&L:       ${tab.get('pnl', 0):+,.2f} ({tab.get('pnl_pct', 0):+.2f}%)")
            print(f"    Positions: {tab.get('positions', 0)}")
            print(f"    Realized:  ${tab.get('realized_pnl', 0):+,.2f}")
            print(f"    Unrealized:${tab.get('unrealized_pnl', 0):+,.2f}")
            print(f"    Fees:      ${tab.get('fees_paid', 0):,.2f}")

            session_dir = SESSIONS_DIR / tab.get("tab", "")
            marks = last_n_lines(session_dir / "marks.jsonl", 1)
            if marks:
                try:
                    m = json.loads(marks[0])
                    print(f"    Last mark: {m.get('timestamp', '—')[:19]} equity=${m.get('equity', 0):,.2f}")
                except json.JSONDecodeError:
                    pass
            trades_path = session_dir / "trades.jsonl"
            total = 0
            if trades_path.exists():
                total = len(trades_path.read_text(encoding="utf-8").strip().splitlines())
            print(f"    Trades:    {total}")
    except Exception as e:
        print(f"API error: {e}")

    print("=" * 60)

if __name__ == "__main__":
    main()
