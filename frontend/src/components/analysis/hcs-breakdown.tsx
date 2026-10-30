"use client";

import type { HCSBreakdown } from "@/lib/types";
import { fmtNum } from "@/lib/format";

export function HcsBreakdownCard({ breakdown }: { breakdown: HCSBreakdown }) {
  return (
    <div className="rounded-lg border border-border/80 bg-secondary/20 p-4 space-y-3 text-sm">
      <div>
        <p className="text-xs font-medium uppercase text-violet">Historical Consistency Score</p>
        <p className="text-2xl font-bold tabular text-electric">{fmtNum(breakdown.hcs, 1)}</p>
        <p className="text-xs text-muted-foreground">
          Descriptive ranking index — not a win probability. Methodology {breakdown.version} · window{" "}
          {breakdown.analysis_window} · cushion from {breakdown.cushion_window}.
        </p>
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        <Metric label="Historical performance" value={breakdown.component_historical} />
        <Metric label="Line cushion" value={breakdown.component_cushion} />
        <Metric label="Minutes / role" value={breakdown.component_minutes} />
      </div>
      <dl className="grid gap-1 text-xs text-muted-foreground sm:grid-cols-2">
        <div>
          Recency-weighted hit: {fmtNum(breakdown.h_weighted * 100, 1)}% · shrunk{" "}
          {fmtNum(breakdown.h_shrunk * 100, 1)}%
        </div>
        <div>
          Record {breakdown.hits}/{breakdown.hits + breakdown.misses + breakdown.pushes} ({breakdown.qualifying_games}{" "}
          games, N<sub>eff</sub> {fmtNum(breakdown.effective_sample_size, 1)})
        </div>
        {breakdown.median != null && (
          <div>
            Median {fmtNum(breakdown.median)} · IQR {breakdown.iqr != null ? fmtNum(breakdown.iqr) : "—"}
          </div>
        )}
        {breakdown.m5_minutes != null && breakdown.m20_minutes != null && (
          <div>
            Minutes L5 {fmtNum(breakdown.m5_minutes, 1)} · L20 {fmtNum(breakdown.m20_minutes, 1)}
          </div>
        )}
        {breakdown.last_game_date && <div>Last historical game: {breakdown.last_game_date}</div>}
      </dl>
      {breakdown.missing_data_flags.length > 0 && (
        <p className="text-xs text-amber-400">Data notes: {breakdown.missing_data_flags.join(", ")}</p>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md bg-background/40 px-3 py-2">
      <p className="text-[10px] uppercase text-muted-foreground">{label}</p>
      <p className="text-lg font-semibold tabular">{fmtNum(value, 0)}/100</p>
    </div>
  );
}
