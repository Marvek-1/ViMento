#!/usr/bin/env python3
"""Minimal read-only web dashboard for the paper engine."""

from __future__ import annotations

import argparse
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from futures_paper_engine import FuturesPaperEngine


def money(value: float) -> str:
    return f"${value:,.2f}"


def page(engine: FuturesPaperEngine) -> str:
    s = engine.account_summary()
    cards = [
        ("Wallet", money(s["wallet_balance"])),
        ("Available", money(s["available_balance"])),
        ("Reserved Margin", money(s["reserved_margin"])),
        ("Open Notional", money(s["open_notional"])),
        ("Realized Net", money(s["realized_net_pnl"])),
        ("Unrealized", money(s["unrealized_pnl"])),
        ("Fees", money(s["fees_paid"])),
        ("Current Equity", money(s["current_equity"])),
    ]
    card_html = "".join(
        f'<div class="card"><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></div>'
        for label, value in cards
    )

    rows = ""
    for p in s["open_positions"]:
        rows += f"""
        <tr>
          <td>{html.escape(p['trade_id'])}</td>
          <td>{html.escape(p['symbol'])}</td>
          <td>{html.escape(p['side'].upper())}</td>
          <td>{html.escape(p['margin_mode'])}</td>
          <td>{p['leverage']}x</td>
          <td>{money(p['isolated_margin'])}</td>
          <td>{money(p['notional'])}</td>
          <td>{p['entry_price']:.6f}</td>
          <td>{p['mark_price']:.6f}</td>
          <td>{p['take_profit_price']:.6f}</td>
          <td>{p['stop_loss_price']:.6f}</td>
          <td>{money(p['unrealized_net_pnl'])}</td>
          <td>{p['margin_roi_pct']:.2f}%</td>
        </tr>"""
    if not rows:
        rows = '<tr><td colspan="13">No open positions</td></tr>'

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="5">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MoStar Futures Paper</title>
<style>
body{{font-family:Arial,sans-serif;background:#0b1020;color:#ecf2ff;margin:0;padding:20px}}
h1{{margin:0 0 18px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}}
.card{{background:#151d33;border:1px solid #2c385a;border-radius:12px;padding:14px}}
.card span{{display:block;color:#9aa7c2;font-size:12px;margin-bottom:8px}}
.card strong{{font-size:22px}}
table{{width:100%;border-collapse:collapse;margin-top:22px;background:#151d33}}
th,td{{padding:10px;border-bottom:1px solid #2c385a;text-align:right;font-size:13px}}
th:first-child,td:first-child,th:nth-child(2),td:nth-child(2),th:nth-child(3),td:nth-child(3){{text-align:left}}
small{{color:#9aa7c2}}
</style>
</head>
<body>
<h1>MoStar Futures Paper</h1>
<small>Paper-only &bull; Default isolated &bull; 5x/10x &bull; $20-$100 margin</small>
<div class="grid">{card_html}</div>
<table>
<thead><tr>
<th>ID</th><th>Symbol</th><th>Side</th><th>Mode</th><th>Lev</th>
<th>Margin</th><th>Notional</th><th>Entry</th><th>Mark</th>
<th>TP</th><th>SL</th><th>Net uPnL</th><th>ROI</th>
</tr></thead>
<tbody>{rows}</tbody>
</table>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default="paper_sessions/default")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    engine = FuturesPaperEngine(Path(args.session))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            route = urlparse(self.path).path
            if route == "/api/status":
                payload = json.dumps(engine.account_summary()).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            payload = page(engine).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Dashboard: http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
