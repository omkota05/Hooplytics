"use client";

import type { HitStreakGameResult } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATE: Record<string, string> = {
  hit: "bg-over/25 text-over border-over/40",
  miss: "bg-under/20 text-under border-under/40",
  push: "bg-push/20 text-push border-push/40",
};

export function StreakViz({ results, line }: { results: HitStreakGameResult[]; line: number }) {
  if (!results.length) {
    return <span className="text-xs text-muted-foreground">No recent games</span>;
  }
  return (
    <div className="flex flex-wrap gap-0.5" title={`Line ${line}`}>
      {results.map((r) => {
        const key = r.bet_result ?? "miss";
        const letter = key === "hit" ? "H" : key === "push" ? "P" : "M";
        const tip =
          r.stat_value != null
            ? `${r.game_date}: ${r.stat_value} vs ${line}`
            : `${r.game_date}: incomplete`;
        return (
          <span
            key={`${r.game_id}-${r.game_date}`}
            title={tip}
            className={cn(
              "inline-flex size-5 items-center justify-center rounded border text-[9px] font-bold tabular",
              STATE[key] ?? "bg-secondary text-muted-foreground",
            )}
          >
            {letter}
          </span>
        );
      })}
    </div>
  );
}
