import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  CheckCircle2,
  Database,
  FlaskConical,
  Layers,
  Loader2,
  RefreshCw,
  Scale,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { api, type AutopilotEvidenceRunItem } from "@/lib/api";
import { formatMetricVal } from "@/lib/formatters";
import { getTradeStatisticalStatus } from "@/lib/statisticalGuards";
import { GridResearchLab } from "./GridResearchLab";
import { SharpeSortinoTrackingChart } from "@/components/charts/SharpeSortinoTrackingChart";

export function AutopilotRuns() {
  const [activeTab, setActiveTab] = useState<"provenance_audit" | "risk_ratios" | "grid_research">("provenance_audit");
  const [runs, setRuns] = useState<AutopilotEvidenceRunItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load(mode: "initial" | "refresh" = "refresh") {
    if (mode === "initial") setLoading(true);
    else setRefreshing(true);
    setError(null);
    try {
      const list = await api.listAutopilotEvidenceRuns(100);
      setRuns(Array.isArray(list) ? list : []);
    } catch (err) {
      setRuns([]);
      setError(err instanceof Error ? err.message : "Failed to load autopilot evidence runs.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    void load("initial");
  }, []);

  return (
    <div className="min-h-screen p-4 sm:p-6 lg:p-8 space-y-6 max-w-7xl mx-auto">
      {/* Top Tab Toggle */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border/40 pb-4">
        <div className="flex items-center gap-2 bg-muted/40 p-1 rounded-xl border border-border/50">
          <button
            type="button"
            onClick={() => setActiveTab("provenance_audit")}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              activeTab === "provenance_audit"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <FlaskConical className="h-3.5 w-3.5" />
            Provenance Audit &amp; Sample Size
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("risk_ratios")}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              activeTab === "risk_ratios"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Scale className="h-3.5 w-3.5 text-emerald-500" />
            Sharpe &amp; Sortino Trajectory
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("grid_research")}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              activeTab === "grid_research"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Database className="h-3.5 w-3.5 text-primary" />
            Bybit Grid &amp; Futures Dataset Engine (N &ge; 500)
          </button>
        </div>

        {activeTab === "provenance_audit" && (
          <button
            type="button"
            onClick={() => void load("refresh")}
            disabled={refreshing}
            className="glass-btn text-xs inline-flex items-center gap-1.5 px-3 py-1.5"
          >
            {refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            Refresh
          </button>
        )}
      </div>

      {activeTab === "grid_research" ? (
        <GridResearchLab />
      ) : activeTab === "risk_ratios" ? (
        <div className="space-y-6">
          <SharpeSortinoTrackingChart />
        </div>
      ) : (
        <div className="flex flex-col gap-6">
          {/* Header */}
          <section className="space-y-3">
            <div className="glass-chip inline-flex items-center gap-2 text-xs font-medium text-muted-foreground">
              <FlaskConical className="h-3.5 w-3.5" />
              Provenance Verification &bull; Statistical Usability Audit
            </div>
            <div>
              <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">
                Autopilot Runs: Statistical Audit &amp; Sample Size Guard
              </h1>
              <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
                Provenance verification certifies that run artifacts exist and were produced by actual execution &mdash;
                it does <strong>not</strong> mean the run is statistically evaluable for model selection.
                A Sharpe ratio like <code className="text-xs bg-muted px-1 py-0.5 rounded text-amber-500 font-bold">+2.14</code> repeated across tiny runs (N=7, 3, 1) is a <strong>reporting artifact</strong> rather than statistical evidence.
              </p>
            </div>
          </section>

          {/* User Requested 4-Run Statistical Status Table */}
          <section className="glass-card rounded-2xl p-5 border border-border/50 space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div>
                <h2 className="text-base font-bold flex items-center gap-2">
                  <ShieldAlert className="h-5 w-5 text-amber-500" />
                  Audited Provenance Summary &amp; Statistical Usability
                </h2>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Audited trade sample sizes and statistical validity status. Small-sample Sharpe ratios are grayed out.
                </p>
              </div>
              <div className="text-xs font-mono text-muted-foreground">
                Evaluation Rule: Trades &lt; 30 = Insufficient
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left">
                <thead className="border-b border-border/60 text-muted-foreground uppercase text-[10px]">
                  <tr>
                    <th className="py-2.5 px-3">Run Name / Strategy</th>
                    <th className="py-2.5 px-3 text-right">Return</th>
                    <th className="py-2.5 px-3 text-right">Trades (N)</th>
                    <th className="py-2.5 px-3 text-right">Sharpe Ratio</th>
                    <th className="py-2.5 px-3 text-right">Statistical Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/30 font-mono">
                  {/* BTC Momentum */}
                  <tr className="hover:bg-muted/30 transition-colors">
                    <td className="py-3 px-3 font-semibold text-foreground">
                      <div className="flex items-center gap-2">
                        <span className="h-2 w-2 rounded-full bg-amber-500" />
                        <span>BTC momentum (1h Breakout + RSI Filter)</span>
                      </div>
                    </td>
                    <td className="py-3 px-3 text-right font-bold text-danger">-5.50%</td>
                    <td className="py-3 px-3 text-right font-bold">7</td>
                    <td className="py-3 px-3 text-right text-muted-foreground line-through cursor-help" title="N=7 trades: Sharpe is statistically unverified and unstable at this sample size.">
                      +2.14 (invalid)
                    </td>
                    <td className="py-3 px-3 text-right">
                      <span className="px-2.5 py-1 rounded-full text-[10px] font-bold bg-destructive/10 text-destructive border border-destructive/30">
                        insufficient
                      </span>
                    </td>
                  </tr>

                  {/* ETH Funding Arb */}
                  <tr className="hover:bg-muted/30 transition-colors">
                    <td className="py-3 px-3 font-semibold text-foreground">
                      <div className="flex items-center gap-2">
                        <span className="h-2 w-2 rounded-full bg-amber-500" />
                        <span>ETH funding arb (Z-Score Volatility Filter)</span>
                      </div>
                    </td>
                    <td className="py-3 px-3 text-right font-bold text-success">+0.89%</td>
                    <td className="py-3 px-3 text-right font-bold">3</td>
                    <td className="py-3 px-3 text-right text-muted-foreground line-through cursor-help" title="N=3 trades: Sharpe is statistically unverified and unstable at this sample size.">
                      +2.14 (invalid)
                    </td>
                    <td className="py-3 px-3 text-right">
                      <span className="px-2.5 py-1 rounded-full text-[10px] font-bold bg-destructive/10 text-destructive border border-destructive/30">
                        insufficient
                      </span>
                    </td>
                  </tr>

                  {/* SOL Breakout */}
                  <tr className="hover:bg-muted/30 transition-colors">
                    <td className="py-3 px-3 font-semibold text-foreground">
                      <div className="flex items-center gap-2">
                        <span className="h-2 w-2 rounded-full bg-amber-500" />
                        <span>SOL breakout (Intraday VWAP Reversion)</span>
                      </div>
                    </td>
                    <td className="py-3 px-3 text-right font-bold text-muted-foreground">0.00%</td>
                    <td className="py-3 px-3 text-right font-bold">1</td>
                    <td className="py-3 px-3 text-right text-muted-foreground line-through cursor-help" title="N=1 trade: Sharpe is statistically unverified and unstable at this sample size.">
                      +2.14 (invalid)
                    </td>
                    <td className="py-3 px-3 text-right">
                      <span className="px-2.5 py-1 rounded-full text-[10px] font-bold bg-destructive/10 text-destructive border border-destructive/30">
                        insufficient
                      </span>
                    </td>
                  </tr>

                  {/* Alpha101 Comparison */}
                  <tr className="hover:bg-muted/30 transition-colors">
                    <td className="py-3 px-3 font-semibold text-foreground">
                      <div className="flex items-center gap-2">
                        <span className="h-2 w-2 rounded-full bg-muted-foreground" />
                        <span>Alpha101 comparison (#001 vs #101 Portfolio)</span>
                      </div>
                    </td>
                    <td className="py-3 px-3 text-right text-muted-foreground">incomplete</td>
                    <td className="py-3 px-3 text-right text-muted-foreground">unknown</td>
                    <td className="py-3 px-3 text-right text-muted-foreground line-through">N/A</td>
                    <td className="py-3 px-3 text-right">
                      <span className="px-2.5 py-1 rounded-full text-[10px] font-bold bg-muted text-muted-foreground border border-border">
                        not evaluable
                      </span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            {/* Quick Action to Grid Research */}
            <div className="flex flex-col sm:flex-row items-center justify-between gap-3 p-3.5 rounded-xl bg-primary/5 border border-primary/20">
              <div className="text-xs text-muted-foreground">
                To build high-power datasets with <code className="text-primary font-bold">N &ge; 200</code> or <code className="text-primary font-bold">N &ge; 500</code> cycles, switch to the Bybit Research Engine.
              </div>
              <button
                type="button"
                onClick={() => setActiveTab("grid_research")}
                className="glass-btn px-3 py-1.5 text-xs font-semibold text-primary inline-flex items-center gap-1.5 shrink-0"
              >
                Open Bybit Dataset Engine
                <ArrowRight className="h-3.5 w-3.5" />
              </button>
            </div>
          </section>

          {/* Statistical Threshold Reference Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Trade Sample Guard Rule */}
            <div className="p-4 rounded-2xl border border-border/60 bg-muted/20 space-y-2">
              <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                <BarChart3 className="h-4 w-4 text-primary" />
                Standard Trade Sample Size Rules
              </h3>
              <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                <div className="p-2 rounded-lg bg-background/80 border border-border/40">
                  <div className="text-destructive font-bold">&lt; 30 trades</div>
                  <div className="text-[11px] text-muted-foreground">INSUFFICIENT (Hide Sharpe)</div>
                </div>
                <div className="p-2 rounded-lg bg-background/80 border border-border/40">
                  <div className="text-amber-500 font-bold">30 &ndash; 99 trades</div>
                  <div className="text-[11px] text-muted-foreground">PRELIMINARY (Wide Error)</div>
                </div>
                <div className="p-2 rounded-lg bg-background/80 border border-border/40">
                  <div className="text-blue-500 font-bold">100 &ndash; 299 trades</div>
                  <div className="text-[11px] text-muted-foreground">EVALUABLE (Valid Comparison)</div>
                </div>
                <div className="p-2 rounded-lg bg-background/80 border border-border/40">
                  <div className="text-emerald-500 font-bold">300+ trades</div>
                  <div className="text-[11px] text-muted-foreground">STRONG_SAMPLE (High Power)</div>
                </div>
              </div>
            </div>

            {/* Grid Cycle Guard Rule */}
            <div className="p-4 rounded-2xl border border-border/60 bg-muted/20 space-y-2">
              <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                <Layers className="h-4 w-4 text-primary" />
                Grid / Futures Cycle Sample Rules
              </h3>
              <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                <div className="p-2 rounded-lg bg-background/80 border border-border/40">
                  <div className="text-destructive font-bold">&lt; 50 cycles</div>
                  <div className="text-[11px] text-muted-foreground">Insufficient (Untrusted)</div>
                </div>
                <div className="p-2 rounded-lg bg-background/80 border border-border/40">
                  <div className="text-amber-500 font-bold">50 &ndash; 199 cycles</div>
                  <div className="text-[11px] text-muted-foreground">Exploratory (Jitter Check)</div>
                </div>
                <div className="p-2 rounded-lg bg-background/80 border border-border/40">
                  <div className="text-blue-500 font-bold">200 &ndash; 499 cycles</div>
                  <div className="text-[11px] text-muted-foreground">Evaluable (Initial Read)</div>
                </div>
                <div className="p-2 rounded-lg bg-background/80 border border-border/40">
                  <div className="text-emerald-500 font-bold">500+ cycles</div>
                  <div className="text-[11px] text-muted-foreground">Tuning-Quality (Production)</div>
                </div>
              </div>
            </div>
          </div>

          {/* All Provenance Runs List */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="text-sm font-semibold text-muted-foreground">
                All Verified Run Cards ({runs.length})
              </div>
            </div>

            {loading ? (
              <div className="grid gap-3">
                {[1, 2, 3].map((item) => (
                  <div key={item} className="glass-panel h-24 animate-pulse rounded-2xl" />
                ))}
              </div>
            ) : null}

            {!loading && error ? (
              <section className="glass-surface rounded-2xl border border-warning/30 p-5">
                <div className="flex items-center gap-2 font-medium text-warning">
                  <AlertTriangle className="h-5 w-5" />
                  Could not load autopilot evidence runs
                </div>
                <p className="mt-2 text-sm text-muted-foreground">{error}</p>
              </section>
            ) : null}

            {!loading && !error && runs.length > 0 ? (
              <div className="grid gap-3">
                {runs.map((run) => (
                  <AutopilotRunRow key={run.run_dir} run={run} />
                ))}
              </div>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}

function AutopilotRunRow({ run }: { run: AutopilotEvidenceRunItem }) {
  const runName = run.run_dir.split(/[\\/]/).filter(Boolean).pop() || run.run_dir;
  const statStatus = getTradeStatisticalStatus(run.trade_count);
  const lowSample = !statStatus.isSharpeValid;

  return (
    <article className="glass-surface glass-card rounded-2xl p-4">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1 rounded bg-success/10 px-2 py-0.5 text-xs font-medium text-success">
              <CheckCircle2 className="h-3 w-3" />
              provenance verified
            </span>
            <span
              className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium border ${statStatus.badgeClass}`}
              title={statStatus.explanation}
            >
              {lowSample ? <ShieldAlert className="h-3 w-3" /> : <ShieldCheck className="h-3 w-3" />}
              {statStatus.label.toLowerCase()} (N={run.trade_count ?? 0})
            </span>
            <Link to={run.run_dir} className="truncate font-mono text-sm font-medium hover:underline text-primary">
              {runName}
            </Link>
            {run.generated_at ? (
              <span className="text-xs text-muted-foreground">{formatRunDate(run.generated_at)}</span>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-1.5 text-xs text-muted-foreground">
            <span className="rounded border px-2 py-0.5">status: {run.strategy_implementation_status}</span>
            <span className="rounded border px-2 py-0.5">purpose: {run.run_purpose}</span>
          </div>
          <p className="break-all font-mono text-xs text-muted-foreground">{run.run_dir}</p>
        </div>

        <div className="grid grid-cols-3 gap-2 text-right sm:flex sm:flex-wrap sm:justify-end">
          <MetricPill
            label="Return"
            value={formatOptionalMetric("total_return", run.total_return)}
            muted={false}
          />
          <MetricPill
            label="Sharpe"
            value={lowSample ? "N/A*" : formatOptionalMetric("sharpe", run.sharpe)}
            muted={lowSample}
            tooltip={lowSample ? `N=${run.trade_count} trades (< 30): Sharpe is statistically unverified and unstable at this sample size.` : undefined}
          />
          <MetricPill label="Trades" value={run.trade_count != null ? String(run.trade_count) : "-"} />
        </div>
      </div>
    </article>
  );
}

function MetricPill({ label, value, muted, tooltip }: { label: string; value: string; muted?: boolean; tooltip?: string }) {
  return (
    <div className="glass-panel rounded-lg px-3 py-1.5" title={tooltip}>
      <div className="text-[11px] uppercase text-muted-foreground">{label}</div>
      <div className={muted ? "font-mono text-sm font-medium text-muted-foreground line-through cursor-help" : "font-mono text-sm font-medium"}>
        {value}
      </div>
    </div>
  );
}

function formatOptionalMetric(key: string, value: number | undefined): string {
  return Number.isFinite(value) ? formatMetricVal(key, value as number) : "-";
}

function formatRunDate(value: string): string {
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}
