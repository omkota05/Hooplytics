import { Info } from "lucide-react";

import { fmtNum, fmtPct } from "@/lib/format";
import type { StatAnalysis } from "@/lib/types";
import { cn } from "@/lib/utils";

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-border bg-surface/70 px-3 py-2.5">
      <p className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{label}</p>
      <p className="mt-0.5 text-lg font-semibold tabular">{value}</p>
      {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function HitRateSummary({ analysis }: { analysis: StatAnalysis }) {
  const { line_result: lr, distribution: d } = analysis;
  const total = lr.total;
  const share = (n: number) => (total ? (100 * n) / total : 0);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-2">
        {(
          [
            ["Over", lr.over, lr.over_pct, "text-over", "from-over/20"],
            ["Under", lr.under, lr.under_pct, "text-under", "from-under/20"],
            ["Push", lr.push, lr.push_pct, "text-push", "from-push/15"],
          ] as const
        ).map(([label, count, pct, color, grad]) => (
          <div
            key={label}
            className={cn("rounded-xl border border-border bg-gradient-to-b to-transparent px-3 py-3", grad)}
          >
            <p className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{label}</p>
            <p className={cn("text-2xl font-bold tabular", color)}>{total ? fmtPct(pct) : "—"}</p>
            <p className="text-xs text-muted-foreground tabular">
              {count} of {total} games
            </p>
          </div>
        ))}
      </div>

      <div className="flex h-2 overflow-hidden rounded-full bg-secondary" aria-hidden>
        <div className="bg-over transition-all duration-500" style={{ width: `${share(lr.over)}%` }} />
        <div className="bg-push transition-all duration-500" style={{ width: `${share(lr.push)}%` }} />
        <div className="bg-under transition-all duration-500" style={{ width: `${share(lr.under)}%` }} />
      </div>
      {lr.push > 0 && (
        <p className="text-xs text-muted-foreground">
          Excluding pushes: over {fmtPct(lr.over_pct_excluding_pushes)} of {lr.over + lr.under} decided games.
        </p>
      )}

      <div className="grid grid-cols-3 gap-2">
        <Metric label="Average" value={fmtNum(d.mean)} />
        <Metric label="Median" value={fmtNum(d.median)} />
        <Metric label="Std dev" value={fmtNum(d.std_dev)} hint={d.count === 1 ? "needs 2+ games" : undefined} />
        <Metric label="Games" value={String(d.count)} />
        <Metric label="Min" value={fmtNum(d.minimum, 0)} />
        <Metric label="Max" value={fmtNum(d.maximum, 0)} />
      </div>

      <p
        className={cn(
          "flex gap-2 rounded-lg px-3 py-2 text-xs leading-relaxed",
          analysis.small_sample ? "bg-push/10 text-push" : "bg-secondary/50 text-muted-foreground",
        )}
      >
        <Info className="mt-0.5 size-3.5 shrink-0" />
        {analysis.note}
      </p>
    </div>
  );
}
