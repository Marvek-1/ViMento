import { memo } from "react";
import { cn } from "@/lib/utils";
import { getMetricLabel, DISPLAY_ORDER, formatMetricVal, metricSentiment } from "@/lib/formatters";
import { ShieldAlert } from "lucide-react";

const SENTIMENT = {
  positive: "text-success",
  neutral: "text-foreground",
  negative: "text-danger",
} as const;

interface Props {
  metrics: Record<string, number>;
  compact?: boolean;
}

const RATIO_KEYS = new Set(["sharpe", "sortino", "calmar", "information_ratio"]);

export const MetricsCard = memo(function MetricsCard({ metrics, compact = false }: Props) {
  const entries = DISPLAY_ORDER
    .filter((k) => metrics[k] != null)
    .map((k) => ({ k, v: metrics[k] }));

  if (entries.length === 0) return null;

  const shown = compact ? entries.slice(0, 6) : entries;
  const trades = metrics.trade_count;
  const isInsufficientSample = typeof trades === "number" && trades < 30;

  return (
    <div className="space-y-1.5">
      <div className={cn(
        "grid gap-1.5 rounded-xl border border-border/60 bg-muted/20 p-3",
        compact ? "grid-cols-3" : "grid-cols-[repeat(auto-fit,minmax(120px,1fr))]"
      )}>
        {shown.map(({ k, v }) => {
          const isMutedRatio = isInsufficientSample && RATIO_KEYS.has(k);
          return (
            <div key={k} className="text-center py-1 relative group">
              <p className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium flex items-center justify-center gap-1">
                {getMetricLabel(k)}
                {isMutedRatio && (
                  <ShieldAlert className="h-3 w-3 text-amber-500 shrink-0 inline" />
                )}
              </p>
              <p className={cn(
                "text-sm font-bold font-mono tabular-nums mt-0.5",
                isMutedRatio
                  ? "text-muted-foreground/60 line-through cursor-help"
                  : SENTIMENT[metricSentiment(k, v)]
              )}
              title={isMutedRatio ? `N=${trades} trades (< 30): ${getMetricLabel(k)} is statistically unverified and unstable at this sample size.` : undefined}
              >
                {isMutedRatio ? (metrics.is_sharpe_valid ? formatMetricVal(k, v) : "N/A*") : formatMetricVal(k, v)}
              </p>
            </div>
          );
        })}
      </div>
      {isInsufficientSample && (
        <p className="text-[10px] text-amber-600 dark:text-amber-400 text-center font-medium">
          * Trade count (N={trades}) is below the statistical threshold (N &ge; 30). Sharpe/ratios grayed out.
        </p>
      )}
    </div>
  );
});
