"use client";

import useSWR from "swr";

import { ErrorState, LoadingRows } from "@/components/common/states";
import { Card } from "@/components/ui/card";
import { mlApi } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import type { ProspectiveSummary } from "@/lib/ml-types";

import { CATEGORY_ORDER, CATEGORY_SHORT, Stat, WarningList, fmt, pct } from "./ml-shared";

export function ProspectivePanel() {
  const data = useSWR("ml-prospective", () => mlApi.prospective());
  if (data.error) return <ErrorState error={data.error} onRetry={() => data.mutate()} />;
  if (!data.data) return <LoadingRows />;
  const d = data.data;
  return (
    <div className="space-y-4">
      <Card className="border-amber-500/30 bg-amber-500/5 p-4 text-xs text-muted-foreground">
        <p>
          <b className="text-amber-200">Prospective, not backtested.</b> Forecasts are written before tip-off by the scheduled sync and
          odds-import jobs, stored write-once (a database trigger rejects edits), and graded after box scores sync. Opening this page
          never creates a forecast. Small samples are noisy — do not read these numbers as a production result until the warning clears.
        </p>
      </Card>
      <WarningList warnings={d.warnings} />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Stat label="Forecasts recorded" value={d.forecasts_recorded.toLocaleString()} hint={`${d.games_forecast} games`} />
        <Stat label="Settled" value={d.forecasts_settled.toLocaleString()} hint={`${d.games_settled ?? 0} games`} />
        <Stat label="Pending" value={d.forecasts_pending.toLocaleString()} />
        <Stat label="Unresolved / void" value={`${d.forecasts_unresolved} / ${(d.by_status.void_dnp ?? 0) + (d.by_status.void_game ?? 0)}`} hint="no box row / DNP or postponed" />
        <Stat label="Lines captured" value={d.lines_recorded.toLocaleString()} hint={`${d.forecasts_with_lines} forecasts with lines`} />
      </div>
      <p className="text-xs text-muted-foreground">
        First forecast {d.first_predicted_at ? fmtDateTime(d.first_predicted_at) : "—"} · latest {d.last_predicted_at ? fmtDateTime(d.last_predicted_at) : "—"}
      </p>
      {Object.keys(d.categories).length > 0 ? <ProspectiveTables d={d} /> : (
        <Card className="p-4 text-sm text-muted-foreground">No forecasts have settled yet. Metrics appear after the first forecast games finish and box scores sync.</Card>
      )}
    </div>
  );
}

function ProspectiveTables({ d }: { d: ProspectiveSummary }) {
  return (
    <>
      <Card className="overflow-x-auto p-4">
        <p className="mb-2 text-sm font-semibold">Settled forecasts by category</p>
        <table className="w-full text-sm [&_td]:px-2 [&_td]:whitespace-nowrap [&_th]:px-2">
          <thead className="text-left text-xs text-muted-foreground">
            <tr><th>Category</th><th>n</th><th>Games</th><th>MAE</th><th>RMSE</th><th>Bias</th><th>Weighted baseline MAE</th><th>Last 10 MAE</th><th>Season avg MAE</th><th>50% / 80% / 90% coverage</th><th>80% width</th></tr>
          </thead>
          <tbody>
            {CATEGORY_ORDER.map((c) => {
              const x = d.categories[c];
              if (!x) return null;
              return (
                <tr key={c} className="border-t border-border/50">
                  <td className="py-1.5 font-medium">{CATEGORY_SHORT[c]}</td>
                  <td>{x.n}</td><td>{x.games}</td><td className="font-semibold">{fmt(x.mae, 3)}</td><td>{fmt(x.rmse, 3)}</td><td>{fmt(x.bias, 2)}</td>
                  <td>{fmt(x.baselines.weighted?.mae, 3)}</td><td>{fmt(x.baselines.last_10?.mae, 3)}</td><td>{fmt(x.baselines.season_avg?.mae, 3)}</td>
                  <td>{pct(x.coverage_50, 0)} / {pct(x.coverage_80, 0)} / {pct(x.coverage_90, 0)}</td><td>{fmt(x.mean_width_80, 1)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
      <div className="grid gap-4 lg:grid-cols-3">
        {([["Model version", d.by_model_version], ["Minutes tier (L10)", d.by_minutes_tier], ["Usage tier (FGA share L10)", d.by_usage_tier]] as const).map(([title, groups]) => (
          <Card key={title} className="p-4">
            <p className="mb-2 text-sm font-semibold">{title}</p>
            <table className="w-full text-xs">
              <thead className="text-left text-muted-foreground"><tr><th>Group</th><th>n</th><th>PTS MAE</th><th>PRA MAE</th><th>PRA 80% cov.</th></tr></thead>
              <tbody>
                {Object.entries(groups).map(([k, v]) => (
                  <tr key={k} className="border-t border-border/40">
                    <td className="py-0.5">{k}</td><td>{v.pts?.n}</td><td>{fmt(v.pts?.mae)}</td><td>{fmt(v.pts_reb_ast?.mae)}</td><td>{pct(v.pts_reb_ast?.coverage_80, 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        ))}
      </div>
    </>
  );
}
