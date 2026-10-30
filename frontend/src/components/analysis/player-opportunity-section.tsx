"use client";

import { Activity } from "lucide-react";
import { useMemo, useState } from "react";
import useSWR from "swr";

import { OpportunityBarChart, type OpportunityMetric } from "@/components/charts/opportunity-bar-chart";
import { Segmented } from "@/components/common/segmented";
import { ErrorState, Spinner } from "@/components/common/states";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { fmtNum } from "@/lib/format";
import type { PlayerOpportunity } from "@/lib/types";

type OppWindow = "l5" | "l10" | "l20" | "season";

const METRICS: { value: OpportunityMetric; label: string }[] = [
  { value: "minutes", label: "Minutes" },
  { value: "fga", label: "FGA" },
  { value: "fg3a", label: "3PA" },
];

const WINDOWS: { value: OppWindow; label: string }[] = [
  { value: "l5", label: "L5" },
  { value: "l10", label: "L10" },
  { value: "l20", label: "L20" },
  { value: "season", label: "Season" },
];

function windowGames(data: PlayerOpportunity, window: OppWindow, metric: OpportunityMetric) {
  const n = window === "season" ? data.games.length : Number(window.slice(1));
  const slice = window === "season" ? data.games : data.games.slice(-n);
  return slice.filter((g) => g[metric] != null);
}

function windowAvg(data: PlayerOpportunity, window: OppWindow) {
  if (window === "season") return data.season_to_date;
  return data[window];
}

export function PlayerOpportunitySection({
  playerId,
  embedded = false,
  data: externalData,
}: {
  playerId: number;
  embedded?: boolean;
  data?: PlayerOpportunity | null;
}) {
  const [metric, setMetric] = useState<OpportunityMetric>("minutes");
  const [chartWindow, setChartWindow] = useState<OppWindow>("l10");

  const fetched = useSWR(
    externalData ? null : ["opportunity", playerId],
    () => api.playerOpportunity(playerId),
    { revalidateOnFocus: false },
  );
  const data = externalData ?? fetched.data;
  const loading = !externalData && !fetched.data && !fetched.error;

  const chartGames = useMemo(
    () => (data ? windowGames(data, chartWindow, metric) : []),
    [data, chartWindow, metric],
  );

  const header = (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-semibold">
          <Activity className="size-5 text-violet" /> Player opportunity
        </h2>
        <p className="text-sm text-muted-foreground">
          Observed minutes and shot volume from synced box scores — not projected usage.
        </p>
      </div>
      {fetched.isValidating && <Spinner />}
    </div>
  );

  if (fetched.error && !data) {
    return (
      <section className={embedded ? "space-y-4" : "panel space-y-4 p-5"}>
        {header}
        <ErrorState error={fetched.error} onRetry={() => fetched.mutate()} />
      </section>
    );
  }

  if (loading) {
    return (
      <section className={embedded ? "space-y-4" : "panel space-y-4 p-5"}>
        {header}
        <Skeleton className="h-[320px] rounded-xl bg-secondary/50" />
      </section>
    );
  }

  if (!data) return null;

  const avg = windowAvg(data, chartWindow);
  const metricVal = avg[metric];

  return (
    <section className={embedded ? "space-y-4" : "panel space-y-4 p-5"}>
      {header}

      <div className="grid gap-3 sm:grid-cols-4">
        {(["l5", "l10", "l20"] as const).map((w) => (
          <div key={w} className="rounded-xl bg-secondary/40 px-3 py-2">
            <p className="text-[10px] uppercase text-muted-foreground">{w} minutes</p>
            <p className="font-semibold tabular">{fmtNum(data[w].minutes, 1)}</p>
            <p className="text-[10px] text-muted-foreground">{data[w].games} games</p>
          </div>
        ))}
        <div className="rounded-xl bg-secondary/40 px-3 py-2">
          <p className="text-[10px] uppercase text-muted-foreground">Season minutes</p>
          <p className="font-semibold tabular">{fmtNum(data.season_to_date.minutes, 1)}</p>
          <p className="text-[10px] text-muted-foreground">{data.season_to_date.games} games</p>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        {data.trends.slice(0, 4).map((t) => (
          <div key={`${t.metric}-${t.recent_window}`} className="rounded-lg border border-border/60 px-3 py-2 text-sm">
            <p className="text-xs text-muted-foreground">
              {t.label} · {t.recent_window} vs {t.baseline_window}
            </p>
            <p className="tabular">
              {fmtNum(t.recent_avg, 1)} → {fmtNum(t.baseline_avg, 1)}
              {t.difference != null && (
                <span className={t.difference >= 0 ? " text-over" : " text-under"}>
                  {" "}
                  ({t.difference >= 0 ? "+" : ""}
                  {fmtNum(t.difference, 1)})
                </span>
              )}
            </p>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap gap-2">
        <Segmented options={METRICS} value={metric} onChange={setMetric} ariaLabel="Opportunity metric" size="sm" />
        <Segmented options={WINDOWS} value={chartWindow} onChange={setChartWindow} ariaLabel="Chart window" size="sm" />
      </div>
      <p className="text-xs text-muted-foreground">
        {METRICS.find((m) => m.value === metric)?.label} average ({chartWindow.toUpperCase()}):{" "}
        <span className="font-medium text-foreground">{metricVal != null ? fmtNum(metricVal, 1) : "—"}</span>
      </p>
      <OpportunityBarChart games={chartGames} metric={metric} />
    </section>
  );
}
