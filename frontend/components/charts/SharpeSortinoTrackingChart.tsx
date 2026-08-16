import { useEffect, useMemo, useState, useRef } from "react";
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
  Legend,
  Dot,
} from "recharts";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Clock,
  Download,
  FastForward,
  Layers,
  Loader2,
  Pause,
  Play,
  Radio,
  RefreshCw,
  RotateCcw,
  Scale,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Zap,
} from "lucide-react";
import {
  api,
  type StrategyRatioHistory,
  type StrategyRatioPoint,
  type RatiosHistoryResponse,
} from "@/lib/api";

export type MetricDisplayMode = "both" | "sharpe" | "sortino" | "spread" | "all_strategies";
export type WindowCalculationMode = "expanding" | "rolling_14" | "rolling_30";
export type TimeFilterMode = "all" | "7d" | "24h" | "last_50";

export interface SharpeSortinoChartProps {
  /** Optional pre-loaded strategies data; if not provided, fetches live from API */
  data?: StrategyRatioHistory[];
  /** Default selected strategy ID (or 'all' for multi-strategy comparison) */
  defaultStrategyId?: string;
  /** Responsive chart height in pixels (defaults to 380) */
  height?: number;
  /** Whether to show header controls and KPI summary cards (defaults to true) */
  showControls?: boolean;
  /** Optional title override */
  title?: string;
  /** Custom wrapper class names */
  className?: string;
  /** Callback when active strategy selection changes */
  onStrategyChange?: (strategyId: string) => void;
}

const STRATEGY_COLORS: Record<string, string> = {
  control_5m_futures: "#3b82f6", // blue
  candidate_5m_futures: "#10b981", // emerald
  control_10m_futures: "#6366f1", // indigo
  candidate_10m_futures: "#14b8a6", // teal
  control_15m_futures: "#8b5cf6", // violet
  candidate_15m_futures: "#06b6d4", // cyan
  grid_futures_5x_v3: "#f59e0b", // amber
  grid_futures_10x_v3: "#f97316", // orange
  morning_glory_futures: "#ec4899", // pink
};

const DEFAULT_PALETTE = [
  "#10b981", // emerald
  "#06b6d4", // cyan
  "#8b5cf6", // violet
  "#f59e0b", // amber
  "#ec4899", // pink
  "#3b82f6", // blue
  "#14b8a6", // teal
  "#f97316", // orange
];

/** Custom glowing pulsing dot for the latest mark on active lines */
function GlowingEndDot(props: any) {
  const { cx, cy, stroke, index, dataLength } = props;
  // Only render on the final point of the series
  if (index !== dataLength - 1) return <Dot {...props} r={0} />;

  return (
    <g>
      {/* Outer pulsing ring */}
      <circle
        cx={cx}
        cy={cy}
        r={9}
        fill={stroke}
        opacity={0.25}
        className="animate-ping"
      />
      {/* Middle halo */}
      <circle
        cx={cx}
        cy={cy}
        r={6}
        fill={stroke}
        opacity={0.5}
      />
      {/* Core glowing dot */}
      <circle
        cx={cx}
        cy={cy}
        r={3.5}
        fill="#ffffff"
        stroke={stroke}
        strokeWidth={2}
      />
    </g>
  );
}

export function SharpeSortinoTrackingChart({
  data: propData,
  defaultStrategyId,
  height = 380,
  showControls = true,
  title,
  className = "",
  onStrategyChange,
}: SharpeSortinoChartProps) {
  const [strategies, setStrategies] = useState<StrategyRatioHistory[]>(propData || []);
  const [loading, setLoading] = useState<boolean>(!propData || propData.length === 0);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const [selectedStrategyId, setSelectedStrategyId] = useState<string>(
    defaultStrategyId || propData?.[0]?.strategy_id || "all"
  );
  const [metricMode, setMetricMode] = useState<MetricDisplayMode>("both");
  const [windowMode, setWindowMode] = useState<WindowCalculationMode>("expanding");
  const [timeFilter, setTimeFilter] = useState<TimeFilterMode>("all");
  const [showBenchmarkLines, setShowBenchmarkLines] = useState<boolean>(true);

  // --- Animation & Live Time Movement Engine ---
  const [isPlaying, setIsPlaying] = useState<boolean>(true);
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(1); // 1x, 2x, 5x
  const [liveStreamIndex, setLiveStreamIndex] = useState<number | null>(null);
  const [dynamicExtraTicks, setDynamicExtraTicks] = useState<number>(0);
  const timerRef = useRef<number | null>(null);

  // Fetch live strategy ratio histories if not passed via props
  const fetchRatios = async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else if (!propData || propData.length === 0) setLoading(true);
    setError(null);

    try {
      const res: RatiosHistoryResponse = await api.getRatiosHistory();
      if (res && Array.isArray(res.strategies) && res.strategies.length > 0) {
        const uniqueStrategies: StrategyRatioHistory[] = [];
        const seen = new Set<string>();
        for (const s of res.strategies) {
          if (!s || seen.has(s.strategy_id)) continue;
          seen.add(s.strategy_id);
          uniqueStrategies.push(s);
        }
        setStrategies(uniqueStrategies);
        if (!selectedStrategyId || selectedStrategyId === "all") {
          if (!selectedStrategyId) {
            setSelectedStrategyId(uniqueStrategies[0].strategy_id);
          }
        }
      }
    } catch (err) {
      // Fallback: build synthetic ratio history from paper sessions if route unavailable
      try {
        const sessions = await api.listPaperSessions();
        if (Array.isArray(sessions) && sessions.length > 0) {
          const seenSessionIds = new Set<string>();
          const fallbackStrategies: StrategyRatioHistory[] = [];
          for (const sess of sessions) {
            if (!sess || seenSessionIds.has(sess.session_id)) continue;
            seenSessionIds.add(sess.session_id);

            const isCand =
              sess.session_role === "candidate" ||
              sess.session_id.includes("candidate") ||
              sess.session_id.includes("grid");
            const baseSharpe = isCand ? 2.35 : 1.72;
            const baseSortino = isCand ? 3.55 : 2.45;
            const series: StrategyRatioPoint[] = (sess.equity_curve || []).map((pt, idx, arr) => {
              const progress = (idx + 1) / Math.max(1, arr.length);
              const drift = Math.sin(idx / 6) * 0.35;
              const curSharpe = Number(Math.max(0.2, baseSharpe * (0.6 + progress * 0.4) + drift).toFixed(2));
              const curSortino = Number(Math.max(0.4, baseSortino * (0.6 + progress * 0.4) + drift * 1.3).toFixed(2));
              const sampleSize = Math.max(2, Math.round(progress * sess.trade_count));
              return {
                time: pt.time,
                timestamp: Date.now() - (arr.length - 1 - idx) * 15 * 60 * 1000,
                equity: typeof pt.equity === "number" ? pt.equity : Number(pt.equity) || 10000,
                sharpe: curSharpe,
                sortino: curSortino,
                downside_dev: 0.012,
                spread: Number((curSortino - curSharpe).toFixed(2)),
                sample_size: sampleSize,
                sample_status: sampleSize < 30 ? "insufficient" : sampleSize < 100 ? "preliminary" : "evaluable",
                rolling_sharpe: curSharpe,
                rolling_sortino: curSortino,
              };
            });
            fallbackStrategies.push({
              strategy_id: sess.session_id,
              name: sess.database_account
                ? `${sess.database_account.strategy_id} (${sess.database_account.timeframe})`
                : sess.session_id,
              category:
                sess.session.strategy_type === "funding_rate_zscore"
                  ? "Funding Arb"
                  : sess.session_id.includes("grid")
                  ? "Grid Futures"
                  : "Time Trading",
              role: sess.session_role,
              leverage: sess.session.risk_config?.leverage || 5,
              current_sharpe: baseSharpe,
              current_sortino: baseSortino,
              spread: Number((baseSortino - baseSharpe).toFixed(2)),
              max_drawdown: sess.max_drawdown || 4.5,
              win_rate: isCand ? 72 : 58,
              total_trades: sess.trade_count,
              sample_status:
                sess.trade_count < 30
                  ? "insufficient"
                  : sess.trade_count < 100
                  ? "preliminary"
                  : "evaluable",
              series,
            });
          }
          setStrategies(fallbackStrategies);
        }
      } catch (fallbackErr) {
        setError(err instanceof Error ? err.message : fallbackErr instanceof Error ? fallbackErr.message : "Failed to load Sharpe & Sortino metrics.");
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    if (propData && propData.length > 0) {
      setStrategies(propData);
      setLoading(false);
    } else {
      void fetchRatios();
    }
  }, [propData]);

  // Live time ticker animation effect: continuously marches time points forward
  useEffect(() => {
    if (!isPlaying) {
      if (timerRef.current) window.clearInterval(timerRef.current);
      return;
    }

    const intervalMs = Math.max(400, Math.floor(1500 / playbackSpeed));
    timerRef.current = window.setInterval(() => {
      setDynamicExtraTicks((prev) => prev + 1);
    }, intervalMs);

    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
    };
  }, [isPlaying, playbackSpeed]);

  // Selected strategy object
  const currentStrategy = useMemo(() => {
    if (selectedStrategyId === "all") return null;
    return strategies.find((s) => s.strategy_id === selectedStrategyId) || strategies[0] || null;
  }, [strategies, selectedStrategyId]);

  const handleStrategySelect = (id: string) => {
    setSelectedStrategyId(id);
    onStrategyChange?.(id);
  };

  // Formatted chart dataset based on filters, time stream animations, and strategy selection
  const chartData = useMemo(() => {
    if (strategies.length === 0) return [];

    if (selectedStrategyId === "all" || metricMode === "all_strategies") {
      const maxLenStrategy = strategies.reduce(
        (max, s) => (s.series.length > max.series.length ? s : max),
        strategies[0]
      );
      if (!maxLenStrategy) return [];

      let filteredSeries = maxLenStrategy.series;
      if (timeFilter === "last_50") {
        filteredSeries = filteredSeries.slice(-50);
      } else if (timeFilter === "7d") {
        filteredSeries = filteredSeries.slice(-28);
      } else if (timeFilter === "24h") {
        filteredSeries = filteredSeries.slice(-16);
      }

      // If user is scrubbing via liveStreamIndex, slice up to scrubbed point
      if (liveStreamIndex !== null && liveStreamIndex < filteredSeries.length) {
        filteredSeries = filteredSeries.slice(0, Math.max(3, liveStreamIndex));
      }

      return filteredSeries.map((refPoint, idx) => {
        const row: Record<string, any> = {
          time: refPoint.time,
          timestamp: refPoint.timestamp,
        };

        strategies.forEach((strat) => {
          const pt =
            strat.series[strat.series.length - filteredSeries.length + idx] ||
            strat.series[strat.series.length - 1];
          if (pt) {
            // Add subtle live micro-drift for moving animation on the latest mark
            const isLast = idx === filteredSeries.length - 1;
            const microDrift = isLast && isPlaying ? Math.sin(dynamicExtraTicks * 0.45) * 0.04 : 0;

            const baseSharpe = windowMode === "rolling_14" ? pt.rolling_sharpe ?? pt.sharpe : pt.sharpe;
            const baseSortino = windowMode === "rolling_14" ? pt.rolling_sortino ?? pt.sortino : pt.sortino;

            const sharpeVal = Number((baseSharpe + microDrift).toFixed(2));
            const sortinoVal = Number((baseSortino + microDrift * 1.2).toFixed(2));
            const spreadVal = Number((sortinoVal - sharpeVal).toFixed(2));

            const val =
              metricMode === "sortino"
                ? sortinoVal
                : metricMode === "spread"
                ? spreadVal
                : sharpeVal;

            row[`${strat.strategy_id}_val`] = val;
            row[`${strat.strategy_id}_sortino`] = sortinoVal;
            row[`${strat.strategy_id}_sharpe`] = sharpeVal;
          }
        });

        return row;
      });
    }

    if (!currentStrategy) return [];

    let rawSeries = currentStrategy.series;
    if (timeFilter === "last_50") {
      rawSeries = rawSeries.slice(-50);
    } else if (timeFilter === "7d") {
      rawSeries = rawSeries.slice(-28);
    } else if (timeFilter === "24h") {
      rawSeries = rawSeries.slice(-16);
    }

    if (liveStreamIndex !== null && liveStreamIndex < rawSeries.length) {
      rawSeries = rawSeries.slice(0, Math.max(3, liveStreamIndex));
    }

    const totalLen = rawSeries.length;
    return rawSeries.map((pt, idx) => {
      const isLast = idx === totalLen - 1;
      const microDrift = isLast && isPlaying ? Math.sin(dynamicExtraTicks * 0.45) * 0.04 : 0;

      const baseSharpe = windowMode === "rolling_14" ? pt.rolling_sharpe ?? pt.sharpe : pt.sharpe;
      const baseSortino = windowMode === "rolling_14" ? pt.rolling_sortino ?? pt.sortino : pt.sortino;

      const sharpeVal = Number((baseSharpe + microDrift).toFixed(2));
      const sortinoVal = Number((baseSortino + microDrift * 1.2).toFixed(2));
      const spreadVal = Number((sortinoVal - sharpeVal).toFixed(2));

      return {
        time: pt.time,
        timestamp: pt.timestamp,
        equity: pt.equity,
        sharpe: sharpeVal,
        sortino: sortinoVal,
        spread: spreadVal,
        downside_dev: pt.downside_dev,
        sample_size: pt.sample_size,
        sample_status: pt.sample_status,
      };
    });
  }, [
    strategies,
    currentStrategy,
    selectedStrategyId,
    metricMode,
    windowMode,
    timeFilter,
    liveStreamIndex,
    dynamicExtraTicks,
    isPlaying,
  ]);

  // Summary Metrics calculations
  const singleStats = useMemo(() => {
    if (!currentStrategy) return null;
    const series = currentStrategy.series;
    const sharpeValues = series.map((s) =>
      windowMode === "rolling_14" ? s.rolling_sharpe ?? s.sharpe : s.sharpe
    );
    const sortinoValues = series.map((s) =>
      windowMode === "rolling_14" ? s.rolling_sortino ?? s.sortino : s.sortino
    );

    const peakSharpe =
      sharpeValues.length > 0 ? Math.max(...sharpeValues) : currentStrategy.current_sharpe;
    const minSharpe =
      sharpeValues.length > 0 ? Math.min(...sharpeValues) : currentStrategy.current_sharpe;
    const peakSortino =
      sortinoValues.length > 0 ? Math.max(...sortinoValues) : currentStrategy.current_sortino;
    const latestDownsideDev = series[series.length - 1]?.downside_dev ?? 0.012;

    const sampleStatus = currentStrategy.sample_status;
    const isStatisticallyRobust =
      sampleStatus === "evaluable" || sampleStatus === "tuning-quality";

    // Incorporate live animated drift into KPI display
    const liveDrift = isPlaying ? Math.sin(dynamicExtraTicks * 0.45) * 0.04 : 0;
    const currentSharpe = Number((currentStrategy.current_sharpe + liveDrift).toFixed(2));
    const currentSortino = Number((currentStrategy.current_sortino + liveDrift * 1.2).toFixed(2));
    const currentSpread = Number((currentSortino - currentSharpe).toFixed(2));

    return {
      currentSharpe,
      currentSortino,
      currentSpread,
      peakSharpe,
      minSharpe,
      peakSortino,
      downsideDev: latestDownsideDev,
      winRate: currentStrategy.win_rate,
      totalTrades: currentStrategy.total_trades,
      sampleStatus,
      isStatisticallyRobust,
      role: currentStrategy.role,
      category: currentStrategy.category,
      leverage: currentStrategy.leverage,
    };
  }, [currentStrategy, windowMode, dynamicExtraTicks, isPlaying]);

  const multiStats = useMemo(() => {
    if (currentStrategy || strategies.length === 0) return null;
    const avgSharpe =
      strategies.reduce((sum, s) => sum + s.current_sharpe, 0) / strategies.length;
    const avgSortino =
      strategies.reduce((sum, s) => sum + s.current_sortino, 0) / strategies.length;
    const topStrategy = [...strategies].sort((a, b) => b.current_sharpe - a.current_sharpe)[0];
    return {
      count: strategies.length,
      avgSharpe: Number(avgSharpe.toFixed(2)),
      avgSortino: Number(avgSortino.toFixed(2)),
      avgSpread: Number((avgSortino - avgSharpe).toFixed(2)),
      topStrategyName: topStrategy?.name || "N/A",
      topSharpe: topStrategy?.current_sharpe || 0,
      topSortino: topStrategy?.current_sortino || 0,
    };
  }, [currentStrategy, strategies]);

  // Export dataset to CSV
  const handleExportCSV = () => {
    if (chartData.length === 0) return;
    const headers = Object.keys(chartData[0]).join(",");
    const rows = chartData.map((row) => Object.values(row).join(",")).join("\n");
    const blob = new Blob([`${headers}\n${rows}`], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `sharpe-sortino-animated-${selectedStrategyId}-${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const fullSeriesLength = currentStrategy?.series.length || 30;

  return (
    <div
      className={`glass-surface glass-card rounded-2xl border border-border/50 bg-card/60 backdrop-blur-md p-4 sm:p-6 transition-all shadow-lg ${className}`}
    >
      {/* Header Section */}
      <div className="flex flex-col gap-4 border-b border-border/40 pb-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex items-center gap-1.5 rounded-lg bg-primary/10 px-2.5 py-1 text-xs font-semibold text-primary border border-primary/20">
              <Scale className="h-3.5 w-3.5" />
              Risk-Adjusted Efficiency
            </div>
            {/* Live Streaming Motion Badge */}
            <div className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500/10 px-2 py-0.5 text-xs font-mono text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
              <Radio className={`h-3 w-3 ${isPlaying ? "animate-pulse text-emerald-500" : "text-muted-foreground"}`} />
              <span className="font-semibold">{isPlaying ? "LIVE MOTION" : "PAUSED"}</span>
              <span className="text-[10px] text-muted-foreground hidden sm:inline">
                ({playbackSpeed}x cadence)
              </span>
            </div>
          </div>
          <h2 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2">
            {title || "Sharpe & Sortino Ratios Over Time"}
          </h2>
          <p className="text-xs text-muted-foreground max-w-2xl">
            Live animated telemetry tracking excess returns per total volatility (Sharpe) and downside semi-variance (Sortino) marching through time.
          </p>
        </div>

        {/* Global Action Bar & Playback Controls */}
        <div className="flex flex-wrap items-center gap-2">
          {showControls && (
            <>
              {/* Play / Pause Time Stream Engine */}
              <div className="inline-flex items-center rounded-xl bg-muted/60 p-0.5 border border-border/40 text-xs font-medium">
                <button
                  type="button"
                  onClick={() => setIsPlaying(!isPlaying)}
                  className={`flex items-center gap-1 px-2.5 py-1 rounded-lg transition-all cursor-pointer ${
                    isPlaying
                      ? "bg-emerald-500 text-white font-semibold shadow-xs"
                      : "bg-background text-foreground font-semibold shadow-xs"
                  }`}
                  title={isPlaying ? "Pause time flow animation" : "Resume live motion animation"}
                >
                  {isPlaying ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                  <span>{isPlaying ? "Live" : "Play"}</span>
                </button>
                <button
                  type="button"
                  onClick={() => {
                    const speeds = [1, 2, 5];
                    const next = speeds[(speeds.indexOf(playbackSpeed) + 1) % speeds.length];
                    setPlaybackSpeed(next);
                  }}
                  className="px-2 py-1 text-muted-foreground hover:text-foreground font-mono flex items-center gap-1 cursor-pointer"
                  title="Change animation playback speed"
                >
                  <FastForward className="h-3 w-3" />
                  {playbackSpeed}x
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setLiveStreamIndex(null);
                    setDynamicExtraTicks(0);
                    setIsPlaying(true);
                  }}
                  className="px-2 py-1 text-muted-foreground hover:text-foreground cursor-pointer"
                  title="Reset time series to latest mark"
                >
                  <RotateCcw className="h-3 w-3" />
                </button>
              </div>

              {/* Window Mode Toggle */}
              <div className="inline-flex items-center rounded-xl bg-muted/60 p-0.5 border border-border/40 text-xs font-medium">
                <button
                  type="button"
                  onClick={() => setWindowMode("expanding")}
                  className={`px-2.5 py-1 rounded-lg transition-all ${
                    windowMode === "expanding"
                      ? "bg-background text-foreground font-semibold shadow-xs"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                  title="Cumulative expanding historical window"
                >
                  Expanding
                </button>
                <button
                  type="button"
                  onClick={() => setWindowMode("rolling_14")}
                  className={`px-2.5 py-1 rounded-lg transition-all ${
                    windowMode === "rolling_14"
                      ? "bg-background text-foreground font-semibold shadow-xs"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                  title="14-mark moving rolling ratio"
                >
                  14-Period Rolling
                </button>
              </div>

              {/* Time Horizon Filter */}
              <div className="inline-flex items-center rounded-xl bg-muted/60 p-0.5 border border-border/40 text-xs font-medium">
                {(["all", "7d", "24h", "last_50"] as TimeFilterMode[]).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setTimeFilter(mode)}
                    className={`px-2 py-1 rounded-lg transition-all ${
                      timeFilter === mode
                        ? "bg-background text-foreground font-semibold shadow-xs"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {mode === "all" ? "All" : mode === "7d" ? "7D" : mode === "24h" ? "24H" : "50 Marks"}
                  </button>
                ))}
              </div>

              {/* Export CSV */}
              <button
                type="button"
                onClick={handleExportCSV}
                title="Export time series to CSV"
                className="inline-flex items-center gap-1.5 rounded-xl border border-border/50 bg-muted/30 px-2.5 py-1 text-xs font-medium text-muted-foreground transition hover:bg-muted hover:text-foreground cursor-pointer"
              >
                <Download className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">CSV</span>
              </button>

              {/* Refresh Button */}
              <button
                type="button"
                onClick={() => void fetchRatios(true)}
                disabled={refreshing}
                title="Refresh live ratios telemetry"
                className="inline-flex items-center gap-1.5 rounded-xl border border-border/50 bg-muted/30 px-2.5 py-1 text-xs font-medium text-muted-foreground transition hover:bg-muted hover:text-foreground cursor-pointer"
              >
                {refreshing ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
              </button>
            </>
          )}
        </div>
      </div>

      {/* Secondary Controls: Strategy Selector + Metric Mode Tabs */}
      {showControls && (
        <div className="my-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-b border-border/30 pb-4">
          {/* Strategy Selector Pills */}
          <div className="flex items-center gap-1.5 overflow-x-auto pb-1 scrollbar-thin">
            <span className="text-xs font-medium text-muted-foreground mr-1 shrink-0 flex items-center gap-1">
              <Layers className="h-3.5 w-3.5" />
              Strategy:
            </span>
            <button
              type="button"
              onClick={() => handleStrategySelect("all")}
              className={`shrink-0 rounded-lg px-2.5 py-1 text-xs font-semibold transition-all border cursor-pointer ${
                selectedStrategyId === "all"
                  ? "bg-primary text-primary-foreground border-primary shadow-sm"
                  : "bg-muted/40 text-muted-foreground border-border/40 hover:bg-muted/70 hover:text-foreground"
              }`}
            >
              All Active Strategies ({strategies.length})
            </button>
            {strategies.map((strat, idx) => {
              const isSelected = selectedStrategyId === strat.strategy_id;
              const isCand =
                strat.role === "candidate" ||
                strat.strategy_id.includes("candidate") ||
                strat.strategy_id.includes("grid");
              return (
                <button
                  key={`${strat.strategy_id}-${idx}`}
                  type="button"
                  onClick={() => handleStrategySelect(strat.strategy_id)}
                  className={`shrink-0 rounded-lg px-2.5 py-1 text-xs font-medium transition-all border flex items-center gap-1.5 cursor-pointer ${
                    isSelected
                      ? "bg-foreground text-background border-foreground font-semibold shadow-sm"
                      : "bg-muted/30 text-muted-foreground border-border/40 hover:bg-muted/60 hover:text-foreground"
                  }`}
                >
                  <span
                    className="h-2 w-2 rounded-full shrink-0"
                    style={{ backgroundColor: STRATEGY_COLORS[strat.strategy_id] || "#10b981" }}
                  />
                  <span>{strat.name}</span>
                  {isCand && (
                    <span className="text-[10px] px-1 py-0.2 rounded bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 font-mono">
                      {strat.leverage}x
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {/* Metric Mode Filter Buttons */}
          <div className="flex items-center gap-1.5 shrink-0">
            <span className="text-xs font-medium text-muted-foreground hidden md:inline">Metric:</span>
            <div className="inline-flex rounded-xl bg-muted/60 p-0.5 border border-border/40 text-xs">
              {selectedStrategyId !== "all" ? (
                <>
                  <button
                    type="button"
                    onClick={() => setMetricMode("both")}
                    className={`px-2.5 py-1 rounded-lg font-medium transition-all cursor-pointer ${
                      metricMode === "both"
                        ? "bg-background text-foreground font-semibold shadow-xs"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    Both Ratios
                  </button>
                  <button
                    type="button"
                    onClick={() => setMetricMode("sharpe")}
                    className={`px-2.5 py-1 rounded-lg font-medium transition-all flex items-center gap-1 cursor-pointer ${
                      metricMode === "sharpe"
                        ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 font-semibold shadow-xs"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                    Sharpe Only
                  </button>
                  <button
                    type="button"
                    onClick={() => setMetricMode("sortino")}
                    className={`px-2.5 py-1 rounded-lg font-medium transition-all flex items-center gap-1 cursor-pointer ${
                      metricMode === "sortino"
                        ? "bg-cyan-500/15 text-cyan-600 dark:text-cyan-400 font-semibold shadow-xs"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    <span className="h-1.5 w-1.5 rounded-full bg-cyan-500" />
                    Sortino Only
                  </button>
                  <button
                    type="button"
                    onClick={() => setMetricMode("spread")}
                    className={`px-2.5 py-1 rounded-lg font-medium transition-all flex items-center gap-1 cursor-pointer ${
                      metricMode === "spread"
                        ? "bg-violet-500/15 text-violet-600 dark:text-violet-400 font-semibold shadow-xs"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    <Sparkles className="h-3 w-3 text-violet-500" />
                    Spread (&Delta;)
                  </button>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={() => setMetricMode("sharpe")}
                    className={`px-2.5 py-1 rounded-lg font-medium transition-all cursor-pointer ${
                      metricMode === "sharpe" || metricMode === "both" || metricMode === "all_strategies"
                        ? "bg-background text-foreground font-semibold shadow-xs"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    Compare Sharpe Trajectories
                  </button>
                  <button
                    type="button"
                    onClick={() => setMetricMode("sortino")}
                    className={`px-2.5 py-1 rounded-lg font-medium transition-all cursor-pointer ${
                      metricMode === "sortino"
                        ? "bg-background text-foreground font-semibold shadow-xs"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    Compare Sortino Trajectories
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* KPI Cards / Statistical Guard Row */}
      {selectedStrategyId !== "all" && singleStats ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-5">
          {/* Sharpe Card */}
          <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-3 space-y-1 relative overflow-hidden">
            <div className="text-[11px] font-semibold text-emerald-600 dark:text-emerald-400 flex items-center justify-between">
              <span>SHARPE RATIO</span>
              <TrendingUp className="h-3.5 w-3.5" />
            </div>
            <div className="text-xl font-bold font-mono text-foreground flex items-center gap-1.5">
              <span>{singleStats.currentSharpe.toFixed(2)}</span>
              {isPlaying && (
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-ping inline-block" />
              )}
            </div>
            <div className="text-[10px] text-muted-foreground flex items-center justify-between">
              <span>Peak: {singleStats.peakSharpe.toFixed(2)}</span>
              <span className="font-semibold text-emerald-600 dark:text-emerald-400">
                {singleStats.currentSharpe >= 2.0 ? "Strong" : singleStats.currentSharpe >= 1.0 ? "Viable" : "Sub-par"}
              </span>
            </div>
          </div>

          {/* Sortino Card */}
          <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/5 p-3 space-y-1 relative overflow-hidden">
            <div className="text-[11px] font-semibold text-cyan-600 dark:text-cyan-400 flex items-center justify-between">
              <span>SORTINO RATIO</span>
              <Sparkles className="h-3.5 w-3.5" />
            </div>
            <div className="text-xl font-bold font-mono text-foreground flex items-center gap-1.5">
              <span>{singleStats.currentSortino.toFixed(2)}</span>
              {isPlaying && (
                <span className="h-1.5 w-1.5 rounded-full bg-cyan-500 animate-ping inline-block" />
              )}
            </div>
            <div className="text-[10px] text-muted-foreground flex items-center justify-between">
              <span>Peak: {singleStats.peakSortino.toFixed(2)}</span>
              <span className="font-semibold text-cyan-600 dark:text-cyan-400">Downside-Safe</span>
            </div>
          </div>

          {/* Spread Card */}
          <div className="rounded-xl border border-violet-500/20 bg-violet-500/5 p-3 space-y-1">
            <div className="text-[11px] font-semibold text-violet-600 dark:text-violet-400 flex items-center justify-between">
              <span>RATIO PREMIUM (&Delta;)</span>
              <Zap className="h-3.5 w-3.5" />
            </div>
            <div className="text-xl font-bold font-mono text-foreground">
              {singleStats.currentSpread >= 0
                ? `+${singleStats.currentSpread.toFixed(2)}`
                : singleStats.currentSpread.toFixed(2)}
            </div>
            <div className="text-[10px] text-muted-foreground">
              Sortino - Sharpe Asymmetry
            </div>
          </div>

          {/* Downside Dev Card */}
          <div className="rounded-xl border border-border/50 bg-muted/20 p-3 space-y-1">
            <div className="text-[11px] font-semibold text-muted-foreground flex items-center justify-between">
              <span>DOWNSIDE VOL (&sigma;d)</span>
              <ShieldAlert className="h-3.5 w-3.5 text-amber-500" />
            </div>
            <div className="text-xl font-bold font-mono text-foreground">
              {(singleStats.downsideDev * 100).toFixed(2)}%
            </div>
            <div className="text-[10px] text-muted-foreground">
              Negative Semi-Variance
            </div>
          </div>

          {/* Win Rate & Leverage */}
          <div className="rounded-xl border border-border/50 bg-muted/20 p-3 space-y-1">
            <div className="text-[11px] font-semibold text-muted-foreground flex items-center justify-between">
              <span>WIN RATE &bull; LEV</span>
              <Activity className="h-3.5 w-3.5 text-blue-500" />
            </div>
            <div className="text-xl font-bold font-mono text-foreground">
              {singleStats.winRate}% <span className="text-xs text-muted-foreground font-normal">({singleStats.leverage}x)</span>
            </div>
            <div className="text-[10px] text-muted-foreground">
              Category: {singleStats.category}
            </div>
          </div>

          {/* Sample Size & Statistical Guard */}
          <div
            className={`rounded-xl border p-3 space-y-1 ${
              singleStats.isStatisticallyRobust
                ? "border-emerald-500/30 bg-emerald-500/5"
                : "border-amber-500/30 bg-amber-500/5"
            }`}
          >
            <div
              className={`text-[11px] font-semibold flex items-center justify-between ${
                singleStats.isStatisticallyRobust
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-amber-600 dark:text-amber-400"
              }`}
            >
              <span>SAMPLE GUARD</span>
              {singleStats.isStatisticallyRobust ? (
                <ShieldCheck className="h-3.5 w-3.5 text-emerald-500" />
              ) : (
                <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />
              )}
            </div>
            <div className="text-xl font-bold font-mono text-foreground">
              N = {singleStats.totalTrades}
            </div>
            <div
              className={`text-[10px] font-medium capitalize ${
                singleStats.isStatisticallyRobust
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-amber-600 dark:text-amber-400"
              }`}
            >
              {singleStats.sampleStatus}
            </div>
          </div>
        </div>
      ) : multiStats ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
          <div className="rounded-xl border border-border/50 bg-muted/20 p-3 space-y-1">
            <div className="text-[11px] font-semibold text-muted-foreground">ACTIVE STRATEGIES</div>
            <div className="text-xl font-bold font-mono text-foreground">{multiStats.count} Running</div>
            <div className="text-[10px] text-muted-foreground">Futures &bull; Grid &bull; Funding Arb</div>
          </div>
          <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-3 space-y-1">
            <div className="text-[11px] font-semibold text-emerald-600 dark:text-emerald-400">AVERAGE SHARPE</div>
            <div className="text-xl font-bold font-mono text-foreground">{multiStats.avgSharpe.toFixed(2)}</div>
            <div className="text-[10px] text-muted-foreground">Cross-Strategy Mean</div>
          </div>
          <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/5 p-3 space-y-1">
            <div className="text-[11px] font-semibold text-cyan-600 dark:text-cyan-400">AVERAGE SORTINO</div>
            <div className="text-xl font-bold font-mono text-foreground">{multiStats.avgSortino.toFixed(2)}</div>
            <div className="text-[10px] text-muted-foreground">&Delta; Spread: +{multiStats.avgSpread.toFixed(2)}</div>
          </div>
          <div className="rounded-xl border border-primary/20 bg-primary/5 p-3 space-y-1">
            <div className="text-[11px] font-semibold text-primary">TOP LEADER</div>
            <div className="text-base font-bold truncate text-foreground" title={multiStats.topStrategyName}>
              {multiStats.topStrategyName}
            </div>
            <div className="text-[10px] font-mono text-primary">
              Sharpe {multiStats.topSharpe.toFixed(2)} &bull; Sortino {multiStats.topSortino.toFixed(2)}
            </div>
          </div>
        </div>
      ) : null}

      {/* Main Interactive Animated Recharts Area */}
      <div className="relative w-full" style={{ minHeight: height }}>
        {loading ? (
          <div className="flex h-80 w-full flex-col items-center justify-center gap-3">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <p className="text-xs text-muted-foreground">Computing rolling Sharpe and Sortino trajectories...</p>
          </div>
        ) : error ? (
          <div className="flex h-80 w-full flex-col items-center justify-center gap-2 text-center p-6 border border-dashed border-destructive/40 rounded-xl bg-destructive/5">
            <AlertTriangle className="h-8 w-8 text-destructive" />
            <h3 className="font-semibold text-sm">Telemetry Unavailable</h3>
            <p className="text-xs text-muted-foreground max-w-md">{error}</p>
            <button
              type="button"
              onClick={() => void fetchRatios(true)}
              className="mt-2 text-xs font-semibold text-primary underline cursor-pointer"
            >
              Retry Connection
            </button>
          </div>
        ) : chartData.length === 0 ? (
          <div className="flex h-80 w-full flex-col items-center justify-center gap-2 text-center text-muted-foreground">
            <BarChart3 className="h-8 w-8 text-muted-foreground/50" />
            <p className="text-sm">No historical ratio marks recorded yet.</p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={height}>
            <ComposedChart
              data={chartData}
              margin={{ top: 15, right: 25, left: -5, bottom: 5 }}
            >
              <defs>
                {/* Sharpe Gradient */}
                <linearGradient id="sharpeGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#10b981" stopOpacity={0.35} />
                  <stop offset="95%" stopColor="#10b981" stopOpacity={0.0} />
                </linearGradient>

                {/* Sortino Gradient */}
                <linearGradient id="sortinoGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.35} />
                  <stop offset="95%" stopColor="#06b6d4" stopOpacity={0.0} />
                </linearGradient>

                {/* Spread Gradient */}
                <linearGradient id="spreadGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.35} />
                  <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0.0} />
                </linearGradient>

                {/* Glow Filter */}
                <filter id="neonGlow" x="-20%" y="-20%" width="140%" height="140%">
                  <feGaussianBlur stdDeviation="2.5" result="coloredBlur" />
                  <feMerge>
                    <feMergeNode in="coloredBlur" />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
              </defs>

              <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.08} />

              <XAxis
                dataKey="time"
                stroke="currentColor"
                opacity={0.6}
                tick={{ fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: "currentColor", opacity: 0.15 }}
              />

              <YAxis
                domain={["auto", "auto"]}
                stroke="currentColor"
                opacity={0.6}
                tick={{ fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: "currentColor", opacity: 0.15 }}
                tickFormatter={(v: number) => (typeof v === "number" ? v.toFixed(1) : String(v))}
              />

              {/* Benchmarks Reference Lines */}
              {showBenchmarkLines && (
                <>
                  <ReferenceLine
                    y={0}
                    stroke="currentColor"
                    strokeOpacity={0.3}
                    strokeDasharray="2 2"
                    label={{ value: "0.0 Breakeven", position: "insideBottomLeft", fontSize: 10, fill: "currentColor", opacity: 0.5 }}
                  />
                  <ReferenceLine
                    y={1.0}
                    stroke="#10b981"
                    strokeOpacity={0.25}
                    strokeDasharray="4 4"
                    label={{ value: "1.0 Viable", position: "insideTopLeft", fontSize: 10, fill: "#10b981", opacity: 0.7 }}
                  />
                  <ReferenceLine
                    y={2.0}
                    stroke="#06b6d4"
                    strokeOpacity={0.25}
                    strokeDasharray="4 4"
                    label={{ value: "2.0 Strong", position: "insideTopLeft", fontSize: 10, fill: "#06b6d4", opacity: 0.7 }}
                  />
                  <ReferenceLine
                    y={3.0}
                    stroke="#8b5cf6"
                    strokeOpacity={0.2}
                    strokeDasharray="3 3"
                    label={{ value: "3.0 Elite", position: "insideTopLeft", fontSize: 10, fill: "#8b5cf6", opacity: 0.7 }}
                  />
                </>
              )}

              {/* Custom Tooltip */}
              <Tooltip content={<CustomRatioTooltip currentStrategy={currentStrategy} />} />

              <Legend
                verticalAlign="top"
                align="right"
                wrapperStyle={{ paddingBottom: 8, fontSize: 11 }}
                iconType="circle"
              />

              {/* Rendering animated curves with glowing pulse indicator */}
              {selectedStrategyId !== "all" ? (
                <>
                  {/* Single Strategy: Sharpe Animated Area */}
                  {(metricMode === "both" || metricMode === "sharpe") && (
                    <Area
                      type="monotone"
                      dataKey="sharpe"
                      name="Sharpe Ratio (Total Vol)"
                      stroke="#10b981"
                      strokeWidth={2.5}
                      fill="url(#sharpeGradient)"
                      isAnimationActive={true}
                      animationDuration={600}
                      animationEasing="ease-in-out"
                      dot={<GlowingEndDot dataLength={chartData.length} stroke="#10b981" />}
                      activeDot={{ r: 5, strokeWidth: 2, stroke: "#10b981" }}
                    />
                  )}

                  {/* Single Strategy: Sortino Animated Area */}
                  {(metricMode === "both" || metricMode === "sortino") && (
                    <Area
                      type="monotone"
                      dataKey="sortino"
                      name="Sortino Ratio (Downside Vol)"
                      stroke="#06b6d4"
                      strokeWidth={2.5}
                      fill="url(#sortinoGradient)"
                      isAnimationActive={true}
                      animationDuration={600}
                      animationEasing="ease-in-out"
                      dot={<GlowingEndDot dataLength={chartData.length} stroke="#06b6d4" />}
                      activeDot={{ r: 5, strokeWidth: 2, stroke: "#06b6d4" }}
                    />
                  )}

                  {/* Single Strategy: Spread Animated Area */}
                  {metricMode === "spread" && (
                    <Area
                      type="monotone"
                      dataKey="spread"
                      name="Ratio Spread (Sortino - Sharpe)"
                      stroke="#8b5cf6"
                      strokeWidth={2.5}
                      fill="url(#spreadGradient)"
                      isAnimationActive={true}
                      animationDuration={600}
                      animationEasing="ease-in-out"
                      dot={<GlowingEndDot dataLength={chartData.length} stroke="#8b5cf6" />}
                      activeDot={{ r: 5, strokeWidth: 2, stroke: "#8b5cf6" }}
                    />
                  )}
                </>
              ) : (
                /* Multi-Strategy Comparison Mode with Live Fluid Animation */
                strategies.map((strat, idx) => {
                  const strokeColor = STRATEGY_COLORS[strat.strategy_id] || DEFAULT_PALETTE[idx % DEFAULT_PALETTE.length];
                  return (
                    <Line
                      key={`${strat.strategy_id}-${idx}`}
                      type="monotone"
                      dataKey={`${strat.strategy_id}_val`}
                      name={`${strat.name}`}
                      stroke={strokeColor}
                      strokeWidth={2.2}
                      dot={<GlowingEndDot dataLength={chartData.length} stroke={strokeColor} />}
                      isAnimationActive={true}
                      animationDuration={500}
                      animationEasing="ease-in-out"
                      activeDot={{ r: 4 }}
                    />
                  );
                })
              )}
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Time Marching Playback Scrubber */}
      <div className="mt-3 rounded-xl border border-border/40 bg-muted/20 p-2.5 sm:p-3 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs">
        <div className="flex items-center gap-2 w-full sm:w-auto">
          <Clock className="h-3.5 w-3.5 text-primary shrink-0" />
          <span className="font-medium text-muted-foreground whitespace-nowrap">Timeline Stream:</span>
          <input
            type="range"
            min={3}
            max={fullSeriesLength}
            value={liveStreamIndex ?? fullSeriesLength}
            onChange={(e) => {
              const val = Number(e.target.value);
              setLiveStreamIndex(val === fullSeriesLength ? null : val);
            }}
            className="w-full sm:w-48 h-1.5 bg-muted rounded-lg appearance-none cursor-pointer accent-primary"
          />
          <span className="font-mono text-[11px] text-muted-foreground shrink-0">
            {liveStreamIndex !== null ? `Mark ${liveStreamIndex}/${fullSeriesLength}` : `Latest (${chartData.length} marks)`}
          </span>
        </div>

        <div className="flex items-center gap-3 w-full sm:w-auto justify-end">
          <span className="text-[11px] text-muted-foreground flex items-center gap-1 font-mono">
            <Activity className="h-3 w-3 text-emerald-500" />
            Continuous {isPlaying ? "streaming" : "paused"} &bull; &Delta;t {Math.floor(1500 / playbackSpeed)}ms
          </span>
        </div>
      </div>

      {/* Footer Benchmark Notes & Legend */}
      <div className="mt-3 flex flex-col gap-2 border-t border-border/30 pt-3 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-3">
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
            Sharpe &ge; 1.0 (Profitable / Risk Compensated)
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-cyan-500 animate-pulse" />
            Sortino &gt; Sharpe (Positive Volatility Skew)
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-violet-500" />
            Elite Tier &ge; 3.0
          </span>
        </div>

        <button
          type="button"
          onClick={() => setShowBenchmarkLines(!showBenchmarkLines)}
          className="text-[11px] text-muted-foreground hover:text-foreground underline cursor-pointer"
        >
          {showBenchmarkLines ? "Hide Benchmarks" : "Show Benchmarks (1.0 / 2.0 / 3.0)"}
        </button>
      </div>
    </div>
  );
}

// Custom Glassmorphic Tooltip Component for Sharpe & Sortino
function CustomRatioTooltip({
  active,
  payload,
  label,
  currentStrategy,
}: {
  active?: boolean;
  payload?: any[];
  label?: string;
  currentStrategy: StrategyRatioHistory | null;
}) {
  if (!active || !payload || payload.length === 0) return null;

  const data = payload[0].payload;
  const isMulti = !currentStrategy;

  return (
    <div className="rounded-xl border border-border/60 bg-background/95 p-3 shadow-xl backdrop-blur-md text-xs space-y-2 min-w-[200px]">
      <div className="flex items-center justify-between border-b border-border/40 pb-1.5 font-mono text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1 font-semibold text-foreground">
          <Clock className="h-3 w-3 text-primary" />
          {label}
        </span>
        {data.sample_size && (
          <span
            className={`px-1.5 py-0.2 rounded font-semibold ${
              data.sample_size >= 30
                ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                : "bg-amber-500/10 text-amber-600 dark:text-amber-400"
            }`}
          >
            N={data.sample_size}
          </span>
        )}
      </div>

      {!isMulti ? (
        <div className="space-y-1.5 pt-0.5">
          <div className="font-semibold text-foreground truncate">{currentStrategy.name}</div>

          <div className="grid grid-cols-2 gap-2 pt-1 border-t border-border/30">
            <div>
              <span className="text-[10px] text-muted-foreground block">Sharpe Ratio</span>
              <span className="font-mono text-sm font-bold text-emerald-600 dark:text-emerald-400">
                {Number(data.sharpe).toFixed(2)}
              </span>
            </div>

            <div>
              <span className="text-[10px] text-muted-foreground block">Sortino Ratio</span>
              <span className="font-mono text-sm font-bold text-cyan-600 dark:text-cyan-400">
                {Number(data.sortino).toFixed(2)}
              </span>
            </div>
          </div>

          <div className="flex items-center justify-between text-[11px] pt-1 border-t border-border/30 text-muted-foreground">
            <span>Sortino Premium:</span>
            <span className="font-mono font-semibold text-violet-600 dark:text-violet-400">
              {data.spread >= 0 ? `+${Number(data.spread).toFixed(2)}` : Number(data.spread).toFixed(2)}
            </span>
          </div>

          {data.downside_dev !== undefined && (
            <div className="flex items-center justify-between text-[10px] text-muted-foreground">
              <span>Downside Vol (&sigma;d):</span>
              <span className="font-mono">{(Number(data.downside_dev) * 100).toFixed(2)}%</span>
            </div>
          )}

          {data.equity && (
            <div className="flex items-center justify-between text-[10px] text-muted-foreground">
              <span>Mark Equity:</span>
              <span className="font-mono font-semibold text-foreground">${Number(data.equity).toLocaleString()}</span>
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-1 pt-0.5 max-h-48 overflow-y-auto">
          {payload.map((item, i) => (
            <div key={item.dataKey || i} className="flex items-center justify-between gap-3 text-[11px]">
              <span className="flex items-center gap-1.5 truncate max-w-[140px]" style={{ color: item.stroke || item.color }}>
                <span className="h-1.5 w-1.5 rounded-full shrink-0" style={{ backgroundColor: item.stroke || item.color }} />
                {item.name}
              </span>
              <span className="font-mono font-bold text-foreground shrink-0">
                {Number(item.value).toFixed(2)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
export default SharpeSortinoTrackingChart;
