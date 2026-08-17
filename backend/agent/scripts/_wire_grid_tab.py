import re
from pathlib import Path

FILE = Path("/home/idona/MoStar/_apps/financial/Vibe-Trading-main/Vibe-Trading-main/frontend/src/pages/PaperTradingDashboard.tsx")
text = FILE.read_text(encoding="utf-8")

# Match the entire Futures Grid mock block, from the comment to its closing )}
pattern = r"      \{/\* ============ FUTURES GRID \(mock — no backend\) ============ \*/\}\n      \{isGrid && \([\s\S]*?\n      \)\}"

new_block = '''      {/* ============ FUTURES GRID (real — selected session) ============ */}
      {isGrid && (
        <div style={css("display:flex;flex-direction:column;gap:16px")}>
          <div style={css("display:grid;grid-template-columns:repeat(4,1fr);gap:12px")}>
            {([
              ["Current Equity", usd(equity), W],
              ["Open Notional", usd(openNotional), W],
              ["Reserved Margin", usd(reserved), W],
              ["Unrealized P&L", signUsd(unreal), unrealColor],
            ] as [string, string, string][]).map(([k, v, c], i) => (
              <div key={i} style={css(card + ";padding:14px 16px")}>
                <div style={css("font-size:12px;color:#9aa3b2")}>{k}</div>
                <div style={{ ...css("font-size:20px;font-weight:700"), color: c, fontFamily: MONO }}>{v}</div>
              </div>
            ))}
          </div>

          <div style={css(card + ";overflow:hidden")}>
            <div style={css("padding:14px 18px;font-size:16px;font-weight:700;border-bottom:1px solid #1e2534")}>Live Grid Positions</div>
            <table style={css("width:100%;border-collapse:collapse;font-size:13px")}>
              <thead><tr style={css("color:#9aa3b2;font-size:12px")}>
                <th style={css(thL)}>Pair</th><th style={css("text-align:left;padding:10px 8px;font-weight:600")}>Side</th>
                <th style={css(thM)}>Margin</th><th style={css(thM)}>Leverage</th><th style={css(thM)}>Entry</th>
                <th style={css(thM)}>Mark</th><th style={css(thM)}>Unrealized</th><th style={css(thM)}>ROI</th>
                <th style={css("text-align:center;padding:10px 18px 10px 8px;font-weight:600")}>Action</th>
              </tr></thead>
              <tbody>
                {positions.map((p, i) => (
                  <tr key={i} style={css("border-top:1px solid #1e2534")}>
                    <td style={css("padding:10px 18px;font-weight:700")}>{p.symbol}</td>
                    <td style={{ ...css("padding:10px 8px;font-weight:700"), color: p.sideColor }}>{p.side}</td>
                    <td style={{ ...css("padding:10px 8px;text-align:right"), fontFamily: MONO }}>{p.margin}</td>
                    <td style={css("padding:10px 8px;text-align:right;color:#6ea0ff;font-weight:600")}>{p.lev}</td>
                    <td style={{ ...css("padding:10px 8px;text-align:right"), fontFamily: MONO }}>{p.entry}</td>
                    <td style={{ ...css("padding:10px 8px;text-align:right"), fontFamily: MONO, color: p.markColor }}>{p.mark}</td>
                    <td style={{ ...css("padding:10px 8px;text-align:right;font-weight:600"), fontFamily: MONO, color: p.pnlColor }}>{p.pnl}</td>
                    <td style={{ ...css("padding:10px 8px;text-align:right;font-weight:600"), fontFamily: MONO, color: p.pnlColor }}>{p.roi}</td>
                    <td style={css("padding:10px 18px 10px 8px;text-align:center")}><button onClick={() => closePosition(p.tradeId)} style={css("background:transparent;border:1px solid #dc2626;color:#ef4444;border-radius:6px;padding:4px 14px;font-size:12px;cursor:pointer;font-family:inherit")}>Close</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={css(card + ";padding:16px 18px;display:flex;flex-direction:column;gap:8px")}>
            <div style={css("font-size:16px;font-weight:700")}>Equity Curve</div>
            <div style={css("flex:1;min-height:150px")}>{equityChart(snap?.equity_curve as any)}</div>
          </div>
        </div>
      )}'''

if not re.search(pattern, text):
    print("ERROR: Futures Grid block not found")
    raise SystemExit(1)

text, count = re.subn(pattern, new_block, text, count=1)
if count != 1:
    print(f"ERROR: replaced {count} occurrences")
    raise SystemExit(1)
FILE.write_text(text, encoding="utf-8")
print("Futures Grid block replaced")
