import { useEffect, useState, useMemo } from "react";
import {
  AlertTriangle,
  BarChart3,
  Download,
  Filter,
  FlaskConical,
  Layers,
  Loader2,
  Play,
  RefreshCw,
  Search,
  ShieldAlert,
  ShieldCheck,
  Sliders,
} from "lucide-react";
import { api, type GridResearchDatasetDetail, type GridResearchDatasetSummaryListItem } from "@/lib/api";
import { ALL_MARKET_REGIMES, getGridStatisticalStatus } from "@/lib/statisticalGuards";

export function GridResearchLab() {
  const [datasets, setDatasets] = useState<GridResearchDatasetSummaryListItem[]>([]);
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>("BTCUSDT-1m-2025-2026");
  const [currentDataset, setCurrentDataset] = useState<GridResearchDatasetDetail | null>(null);
  const [, setLoading] = useState<boolean>(true);
  const [sampling, setSampling] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Sampler form state
  const [sampleSymbol, setSampleSymbol] = useState("BTCUSDT");
  const [sampleInterval, setSampleInterval] = useState("1m");
  const [sampleCycles, setSampleCycles] = useState(650);
  const [sampleLeverage, setSampleLeverage] = useState(5);
  const [sampleGridCount, setSampleGridCount] = useState(20);

  // Filter in event log
  const [regimeFilter, setRegimeFilter] = useState<string>("ALL");
  const [searchFilter, setSearchFilter] = useState<string>("");

  async function loadDatasets() {
    try {
      setLoading(true);
      const list = await api.listGridResearchDatasets();
      const uniqueList: GridResearchDatasetSummaryListItem[] = [];
      const seen = new Set<string>();
      for (const item of list) {
        if (!item || seen.has(item.dataset_id)) continue;
        seen.add(item.dataset_id);
        uniqueList.push(item);
      }
      setDatasets(uniqueList);
      if (uniqueList.length > 0) {
        setSelectedDatasetId((prev) => {
          if (prev && uniqueList.some((item) => item.dataset_id === prev)) {
            return prev;
          }
          return uniqueList[0].dataset_id;
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load datasets");
    } finally {
      setLoading(false);
    }
  }

  async function loadDetail(id: string) {
    try {
      setError(null);
      const detail = await api.getGridResearchDataset(id);
      setCurrentDataset(detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load dataset detail");
    }
  }

  useEffect(() => {
    void loadDatasets();
  }, []);

  useEffect(() => {
    if (selectedDatasetId) {
      void loadDetail(selectedDatasetId);
    }
  }, [selectedDatasetId]);

  async function handleRunSampler(e: React.FormEvent) {
    e.preventDefault();
    setSampling(true);
    setError(null);
    try {
      const generated = await api.sampleGridResearch({
        symbol: sampleSymbol,
        interval: sampleInterval,
        cycles: sampleCycles,
        leverage: sampleLeverage,
        grid_count: sampleGridCount,
      });
      setCurrentDataset(generated);
      setSelectedDatasetId(generated.dataset_id);
      await loadDatasets();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to run sampler");
    } finally {
      setSampling(false);
    }
  }

  // Filtered event rows
  const filteredEvents = useMemo(() => {
    if (!currentDataset?.events_sample) return [];
    return currentDataset.events_sample.filter((ev) => {
      if (regimeFilter !== "ALL" && ev.regime !== regimeFilter) return false;
      if (searchFilter.trim()) {
        const query = searchFilter.toLowerCase();
        return (
          ev.symbol.toLowerCase().includes(query) ||
          ev.side.toLowerCase().includes(query) ||
          ev.reason_opened.toLowerCase().includes(query) ||
          ev.reason_closed.toLowerCase().includes(query)
        );
      }
      return true;
    });
  }, [currentDataset, regimeFilter, searchFilter]);

  const cycleStatus = currentDataset
    ? getGridStatisticalStatus(currentDataset.cycle_count)
    : null;

  return (
    <div className="min-h-screen p-4 sm:p-6 lg:p-8 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <section className="flex flex-col gap-4 border-b border-border/40 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="space-y-2">
          <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full text-xs font-semibold bg-primary/10 text-primary border border-primary/20">
            <FlaskConical className="h-3.5 w-3.5" />
            Statistical Rigor &bull; Bybit Historical Sampler Engine
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">
            Bybit Grid & Futures Research Dataset Engine
          </h1>
          <p className="max-w-3xl text-sm text-muted-foreground">
            Validating grid trading strategies requires high-frequency event-level data across complete
            cycles &mdash; not tiny 7-trade summaries. Pulls historical OHLCV (<code className="text-xs bg-muted px-1 py-0.5 rounded">/v5/market/kline</code>),
            mark price (<code className="text-xs bg-muted px-1 py-0.5 rounded">/v5/market/mark-price-kline</code>),
            funding history (<code className="text-xs bg-muted px-1 py-0.5 rounded">/v5/market/funding/history</code>), and
            open interest to simulate exact signed accounting:{" "}
            <span className="font-mono text-xs text-foreground font-semibold">
              NetPnL = GrossPnL &minus; Fees &minus; Slippage + FundingReceived &minus; FundingPaid
            </span>
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {currentDataset && (
            <>
              <a
                href={api.exportGridResearchUrl(currentDataset.dataset_id, "csv")}
                download
                className="glass-btn text-xs inline-flex items-center gap-1.5 px-3 py-2"
              >
                <Download className="h-3.5 w-3.5" />
                Export CSV
              </a>
              <a
                href={api.exportGridResearchUrl(currentDataset.dataset_id, "json")}
                download
                className="glass-btn text-xs inline-flex items-center gap-1.5 px-3 py-2"
              >
                <Download className="h-3.5 w-3.5" />
                Export JSON
              </a>
            </>
          )}
          <button
            type="button"
            onClick={() => void loadDatasets()}
            className="glass-btn text-xs inline-flex items-center gap-1.5 px-3 py-2"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
        </div>
      </section>

      {/* Dataset Selection & Sampler Controls */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Dataset Selector */}
        <div className="glass-card rounded-2xl p-5 border border-border/50 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
              <Layers className="h-4 w-4 text-primary" />
              Available Datasets
            </h2>
            <span className="text-xs text-muted-foreground font-mono">{datasets.length} files</span>
          </div>

          <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
            {datasets.map((d, index) => {
              const stat = getGridStatisticalStatus(d.cycle_count);
              const isSelected = selectedDatasetId === d.dataset_id;
              return (
                <button
                  key={`${d.dataset_id}-${index}`}
                  onClick={() => setSelectedDatasetId(d.dataset_id)}
                  type="button"
                  className={`w-full text-left p-3 rounded-xl border transition-all ${
                    isSelected
                      ? "border-primary bg-primary/10 shadow-sm"
                      : "border-border/40 hover:border-border hover:bg-muted/30"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-xs font-bold text-foreground">
                      {d.symbol} ({d.interval})
                    </span>
                    <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${stat.badgeClass}`}>
                      {stat.label} (N={d.cycle_count})
                    </span>
                  </div>
                  <div className="mt-1 flex items-center justify-between text-[11px] text-muted-foreground font-mono">
                    <span>{d.date_range.start} ~ {d.date_range.end}</span>
                    <span className={d.overall_expectancy.mean_bps >= 0 ? "text-success font-semibold" : "text-danger font-semibold"}>
                      E[R]: {d.overall_expectancy.mean_bps > 0 ? "+" : ""}{d.overall_expectancy.mean_bps} bps
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Interactive Bybit Sampler Generator */}
        <form
          onSubmit={handleRunSampler}
          className="lg:col-span-2 glass-card rounded-2xl p-5 border border-border/50 space-y-4"
        >
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
              <Sliders className="h-4 w-4 text-primary" />
              Generate Custom Bybit Historical Sample
            </h2>
            <span className="text-xs text-muted-foreground">Target: N &ge; 200 or 500</span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
            <div>
              <label className="text-[11px] font-medium text-muted-foreground block mb-1">Symbol</label>
              <select
                value={sampleSymbol}
                onChange={(e) => setSampleSymbol(e.target.value)}
                className="w-full bg-background border border-border/60 rounded-lg px-2.5 py-1.5 text-xs font-mono"
              >
                <option value="BTCUSDT">BTCUSDT</option>
                <option value="ETHUSDT">ETHUSDT</option>
                <option value="SOLUSDT">SOLUSDT</option>
              </select>
            </div>

            <div>
              <label className="text-[11px] font-medium text-muted-foreground block mb-1">Interval</label>
              <select
                value={sampleInterval}
                onChange={(e) => setSampleInterval(e.target.value)}
                className="w-full bg-background border border-border/60 rounded-lg px-2.5 py-1.5 text-xs font-mono"
              >
                <option value="1m">1m</option>
                <option value="5m">5m</option>
                <option value="15m">15m</option>
                <option value="1h">1h</option>
              </select>
            </div>

            <div>
              <label className="text-[11px] font-medium text-muted-foreground block mb-1">
                Target Cycles (N)
              </label>
              <select
                value={sampleCycles}
                onChange={(e) => setSampleCycles(Number(e.target.value))}
                className="w-full bg-background border border-border/60 rounded-lg px-2.5 py-1.5 text-xs font-mono"
              >
                <option value={7}>N = 7 (Tiny audit)</option>
                <option value={80}>N = 80 (Exploratory)</option>
                <option value={250}>N = 250 (Evaluable)</option>
                <option value={500}>N = 500 (Tuning Quality)</option>
                <option value={1000}>N = 1000 (Deep Gauntlet)</option>
              </select>
            </div>

            <div>
              <label className="text-[11px] font-medium text-muted-foreground block mb-1">Grid Levels</label>
              <input
                type="number"
                min={5}
                max={50}
                value={sampleGridCount}
                onChange={(e) => setSampleGridCount(Number(e.target.value))}
                className="w-full bg-background border border-border/60 rounded-lg px-2.5 py-1.5 text-xs font-mono"
              />
            </div>

            <div>
              <label className="text-[11px] font-medium text-muted-foreground block mb-1">Leverage</label>
              <select
                value={sampleLeverage}
                onChange={(e) => setSampleLeverage(Number(e.target.value))}
                className="w-full bg-background border border-border/60 rounded-lg px-2.5 py-1.5 text-xs font-mono"
              >
                <option value={2}>2x</option>
                <option value={3}>3x</option>
                <option value={5}>5x</option>
                <option value={10}>10x</option>
              </select>
            </div>
          </div>

          <div className="flex items-center justify-between pt-2 border-t border-border/30">
            <div className="text-xs text-muted-foreground flex items-center gap-1.5">
              <ShieldCheck className="h-4 w-4 text-emerald-500" />
              <span>Full Bybit funding interval & fee telemetry aligned</span>
            </div>
            <button
              type="submit"
              disabled={sampling}
              className="glass-btn px-4 py-2 text-xs font-semibold text-primary-foreground bg-primary hover:bg-primary/90 inline-flex items-center gap-2 shadow"
            >
              {sampling ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Sampling Bybit Market...
                </>
              ) : (
                <>
                  <Play className="h-3.5 w-3.5 fill-current" />
                  Sample & Backtest Cycles
                </>
              )}
            </button>
          </div>
        </form>
      </div>

      {error && (
        <div className="p-4 rounded-xl border border-destructive/40 bg-destructive/10 text-destructive text-sm flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {currentDataset && (
        <>
          {/* Statistical Validity Overview Banner */}
          <div className={`p-5 rounded-2xl border ${cycleStatus?.badgeClass} bg-muted/20 space-y-3`}>
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-xl bg-background/80 shadow-sm">
                  {currentDataset.cycle_count >= 200 ? (
                    <ShieldCheck className="h-6 w-6 text-emerald-500" />
                  ) : (
                    <ShieldAlert className="h-6 w-6 text-amber-500" />
                  )}
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-bold text-base text-foreground">
                      Sample Quality: {cycleStatus?.label} (N = {currentDataset.cycle_count} completed cycles)
                    </h3>
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {cycleStatus?.explanation}
                  </p>
                </div>
              </div>

              {/* Statistical Rule Reference Badge */}
              <div className="text-right font-mono text-xs space-y-1">
                <div className="text-[11px] text-muted-foreground">Standard Validation Targets:</div>
                <div className="flex items-center gap-1.5 text-[11px]">
                  <span className="px-1.5 py-0.5 rounded bg-muted">N &ge; 200: initial read</span>
                  <span className="px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 font-semibold">
                    N &ge; 500: tuning-quality
                  </span>
                </div>
              </div>
            </div>

            {/* Core Statistical Expectancy & 95% Confidence Interval Metric Row */}
            <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3 pt-3 border-t border-border/40">
              <div className="p-3 rounded-xl bg-background/70 border border-border/50">
                <div className="text-[10px] uppercase font-bold text-muted-foreground">
                  Expectancy E[R]
                </div>
                <div className="text-base font-bold font-mono mt-0.5 text-primary">
                  {currentDataset.overall_expectancy.mean_bps > 0 ? "+" : ""}
                  {currentDataset.overall_expectancy.mean_bps} bps
                </div>
                <div className="text-[10px] text-muted-foreground mt-0.5">
                  ${currentDataset.overall_expectancy.mean_pnl} / cycle
                </div>
              </div>

              <div className="p-3 rounded-xl bg-background/70 border border-border/50">
                <div className="text-[10px] uppercase font-bold text-muted-foreground">
                  Std Error SE(&#x0154;)
                </div>
                <div className="text-base font-bold font-mono mt-0.5 text-foreground">
                  &plusmn;{currentDataset.overall_expectancy.standard_error} bps
                </div>
                <div className="text-[10px] text-muted-foreground mt-0.5">
                  s / &radic;N (s = {currentDataset.overall_expectancy.sample_std})
                </div>
              </div>

              <div className="p-3 rounded-xl bg-background/70 border border-border/50 sm:col-span-2">
                <div className="text-[10px] uppercase font-bold text-muted-foreground flex items-center justify-between">
                  <span>95% Confidence Interval</span>
                  <span className="text-[10px] font-mono text-muted-foreground">z = 1.96</span>
                </div>
                <div className="text-sm font-bold font-mono mt-0.5 text-foreground">
                  [{currentDataset.overall_expectancy.ci_95_lower} bps, {currentDataset.overall_expectancy.ci_95_upper} bps]
                </div>
                <div className="text-[10px] text-muted-foreground mt-0.5 truncate">
                  {currentDataset.overall_expectancy.ci_95_lower > 0
                    ? "Statistically significant positive edge (p < 0.05)"
                    : "Zero is inside CI - cannot reject null hypothesis of zero edge"}
                </div>
              </div>

              <div className="p-3 rounded-xl bg-background/70 border border-border/50">
                <div className="text-[10px] uppercase font-bold text-muted-foreground">
                  Gross vs Net PnL
                </div>
                <div className="text-sm font-bold font-mono mt-0.5 text-success">
                  ${currentDataset.accounting_summary.net_pnl.toFixed(2)}
                </div>
                <div className="text-[10px] text-muted-foreground mt-0.5">
                  Gross: ${currentDataset.accounting_summary.gross_pnl.toFixed(2)}
                </div>
              </div>

              <div className="p-3 rounded-xl bg-background/70 border border-border/50">
                <div className="text-[10px] uppercase font-bold text-muted-foreground">
                  Total Friction
                </div>
                <div className="text-sm font-bold font-mono mt-0.5 text-danger">
                  -${(
                    currentDataset.accounting_summary.maker_fees +
                    currentDataset.accounting_summary.taker_fees +
                    currentDataset.accounting_summary.slippage
                  ).toFixed(2)}
                </div>
                <div className="text-[10px] text-muted-foreground mt-0.5">
                  Fees + Slippage
                </div>
              </div>
            </div>
          </div>

          {/* Conditional Expectancy by Market Regime: E[Grid PnL | Regime] */}
          <div className="glass-card rounded-2xl p-5 border border-border/50 space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div>
                <h2 className="text-base font-bold flex items-center gap-2">
                  <BarChart3 className="h-5 w-5 text-primary" />
                  Conditional Expectancy by Market Regime: E[Grid PnL &mid; Regime]
                </h2>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Grid strategy performance is highly conditional. Inspecting E[Grid PnL &mid; Regime] prevents deploying into toxic trending/divergent regimes.
                </p>
              </div>
              <div className="text-xs font-mono text-muted-foreground">
                8 Calibrated Regimes
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left">
                <thead className="border-b border-border/60 text-muted-foreground uppercase text-[10px]">
                  <tr>
                    <th className="py-2.5 px-3">Market Regime</th>
                    <th className="py-2.5 px-3 text-right">Cycles (N)</th>
                    <th className="py-2.5 px-3 text-right">Share %</th>
                    <th className="py-2.5 px-3 text-right">Win Rate</th>
                    <th className="py-2.5 px-3 text-right">E[PnL &mid; Regime] (bps)</th>
                    <th className="py-2.5 px-3 text-right">SE (bps)</th>
                    <th className="py-2.5 px-3 text-right">95% CI (bps)</th>
                    <th className="py-2.5 px-3 text-right">Net PnL ($)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/30 font-mono">
                  {ALL_MARKET_REGIMES.map((reg) => {
                    const row = currentDataset.regime_breakdown[reg];
                    if (!row || row.count === 0) {
                      return (
                        <tr key={reg} className="opacity-50">
                          <td className="py-2.5 px-3 font-semibold">{reg}</td>
                          <td className="py-2.5 px-3 text-right">0</td>
                          <td className="py-2.5 px-3 text-right">0%</td>
                          <td className="py-2.5 px-3 text-right">-</td>
                          <td className="py-2.5 px-3 text-right">-</td>
                          <td className="py-2.5 px-3 text-right">-</td>
                          <td className="py-2.5 px-3 text-right">-</td>
                          <td className="py-2.5 px-3 text-right">$0.00</td>
                        </tr>
                      );
                    }

                    const isPositive = row.meanNetBps > 0;
                    return (
                      <tr key={reg} className="hover:bg-muted/30 transition-colors">
                        <td className="py-2.5 px-3 font-semibold flex items-center gap-1.5">
                          <span
                            className={`h-2 w-2 rounded-full ${
                              reg.includes("RANGE")
                                ? "bg-emerald-500"
                                : reg.includes("TREND")
                                ? "bg-amber-500"
                                : reg.includes("FUNDING")
                                ? "bg-blue-500"
                                : "bg-purple-500"
                            }`}
                          />
                          {reg}
                        </td>
                        <td className="py-2.5 px-3 text-right font-bold">{row.count}</td>
                        <td className="py-2.5 px-3 text-right text-muted-foreground">
                          {row.percentOfTotal}%
                        </td>
                        <td className="py-2.5 px-3 text-right">
                          {(row.winRate * 100).toFixed(1)}%
                        </td>
                        <td
                          className={`py-2.5 px-3 text-right font-bold ${
                            isPositive ? "text-success" : "text-danger"
                          }`}
                        >
                          {isPositive ? "+" : ""}
                          {row.meanNetBps} bps
                        </td>
                        <td className="py-2.5 px-3 text-right text-muted-foreground">
                          &plusmn;{row.standardError}
                        </td>
                        <td className="py-2.5 px-3 text-right text-muted-foreground">
                          [{row.ciLower}, {row.ciUpper}]
                        </td>
                        <td
                          className={`py-2.5 px-3 text-right font-bold ${
                            row.netPnlTotal >= 0 ? "text-success" : "text-danger"
                          }`}
                        >
                          ${row.netPnlTotal.toFixed(2)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Event-Level Cycle Telemetry Explorer (40+ Columns) */}
          <div className="glass-card rounded-2xl p-5 border border-border/50 space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <h2 className="text-base font-bold flex items-center gap-2">
                  <Search className="h-5 w-5 text-primary" />
                  Event-Level Telemetry Explorer (40+ Dimensions)
                </h2>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Granular execution logs with orderbook microstructure, Bybit funding timestamps, mark price, and signed fee accounting.
                </p>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                {/* Regime Filter */}
                <div className="flex items-center gap-1.5 bg-background border border-border/60 rounded-lg px-2.5 py-1 text-xs">
                  <Filter className="h-3 w-3 text-muted-foreground" />
                  <select
                    value={regimeFilter}
                    onChange={(e) => setRegimeFilter(e.target.value)}
                    className="bg-transparent border-0 text-xs focus:ring-0 cursor-pointer"
                  >
                    <option value="ALL">All Regimes ({currentDataset.events_sample.length})</option>
                    {ALL_MARKET_REGIMES.map((r) => (
                      <option key={r} value={r}>
                        {r} ({currentDataset.regime_breakdown[r]?.count || 0})
                      </option>
                    ))}
                  </select>
                </div>

                {/* Text Filter */}
                <input
                  type="text"
                  placeholder="Filter by side, reason..."
                  value={searchFilter}
                  onChange={(e) => setSearchFilter(e.target.value)}
                  className="bg-background border border-border/60 rounded-lg px-2.5 py-1 text-xs font-mono w-44"
                />
              </div>
            </div>

            <div className="overflow-x-auto max-h-96 overflow-y-auto border border-border/40 rounded-xl">
              <table className="w-full text-[11px] text-left">
                <thead className="sticky top-0 bg-background/95 backdrop-blur border-b border-border/60 text-muted-foreground uppercase text-[9px] font-mono z-10">
                  <tr>
                    <th className="py-2 px-2.5">Time</th>
                    <th className="py-2 px-2.5">Symbol</th>
                    <th className="py-2 px-2.5">Side/Rung</th>
                    <th className="py-2 px-2.5">Regime</th>
                    <th className="py-2 px-2.5 text-right">Entry &rarr; Exit</th>
                    <th className="py-2 px-2.5 text-right">Mark Price</th>
                    <th className="py-2 px-2.5 text-right">Funding Rate</th>
                    <th className="py-2 px-2.5 text-right">Fees (Maker/Taker)</th>
                    <th className="py-2 px-2.5 text-right">Slippage</th>
                    <th className="py-2 px-2.5 text-right">Funding P/R</th>
                    <th className="py-2 px-2.5 text-right font-bold">Net PnL ($)</th>
                    <th className="py-2 px-2.5 text-right">Net bps</th>
                    <th className="py-2 px-2.5 text-right">Liq Dist %</th>
                    <th className="py-2 px-2.5">Reason Closed</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/20 font-mono">
                  {filteredEvents.map((ev, idx) => {
                    const isWin = ev.net_pnl > 0;
                    const netBps = (ev.net_pnl / ev.notional) * 10000;
                    return (
                      <tr key={idx} className="hover:bg-muted/30 transition-colors">
                        <td className="py-1.5 px-2.5 text-muted-foreground whitespace-nowrap">
                          {new Date(ev.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                        </td>
                        <td className="py-1.5 px-2.5 font-bold">{ev.symbol}</td>
                        <td className="py-1.5 px-2.5 whitespace-nowrap">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                              ev.side === "LONG" || ev.side === "BUY"
                                ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                                : "bg-rose-500/10 text-rose-600 dark:text-rose-400"
                            }`}
                          >
                            {ev.side} #{ev.grid_index}
                          </span>
                        </td>
                        <td className="py-1.5 px-2.5 whitespace-nowrap text-[10px]">
                          <span className="px-1.5 py-0.5 rounded bg-muted font-sans font-medium">
                            {ev.regime}
                          </span>
                        </td>
                        <td className="py-1.5 px-2.5 text-right whitespace-nowrap">
                          ${ev.entry_price} &rarr; ${ev.exit_price}
                        </td>
                        <td className="py-1.5 px-2.5 text-right text-muted-foreground">
                          ${ev.mark_price}
                        </td>
                        <td className="py-1.5 px-2.5 text-right text-muted-foreground">
                          {(ev.funding_rate * 100).toFixed(4)}%
                        </td>
                        <td className="py-1.5 px-2.5 text-right text-muted-foreground">
                          -${(ev.maker_fee + ev.taker_fee).toFixed(3)}
                        </td>
                        <td className="py-1.5 px-2.5 text-right text-muted-foreground">
                          -${ev.slippage.toFixed(3)}
                        </td>
                        <td
                          className={`py-1.5 px-2.5 text-right ${
                            ev.funding_paid_received >= 0 ? "text-emerald-500" : "text-rose-500"
                          }`}
                        >
                          {ev.funding_paid_received >= 0 ? "+" : ""}
                          ${ev.funding_paid_received.toFixed(3)}
                        </td>
                        <td
                          className={`py-1.5 px-2.5 text-right font-bold ${
                            isWin ? "text-success" : "text-danger"
                          }`}
                        >
                          {isWin ? "+" : ""}${ev.net_pnl.toFixed(2)}
                        </td>
                        <td
                          className={`py-1.5 px-2.5 text-right font-semibold ${
                            netBps >= 0 ? "text-success" : "text-danger"
                          }`}
                        >
                          {netBps >= 0 ? "+" : ""}{netBps.toFixed(1)}
                        </td>
                        <td className="py-1.5 px-2.5 text-right text-muted-foreground">
                          {(ev.liquidation_distance_pct * 100).toFixed(1)}%
                        </td>
                        <td className="py-1.5 px-2.5 text-muted-foreground text-[10px] truncate max-w-[150px]">
                          {ev.reason_closed}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="text-right text-[11px] text-muted-foreground font-mono">
              Showing {filteredEvents.length} of {currentDataset.events_sample.length} cycle events
            </div>
          </div>
        </>
      )}
    </div>
  );
}
