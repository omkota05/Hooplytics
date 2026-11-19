"use client";

import { FlaskConical } from "lucide-react";
import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import useSWR from "swr";

import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { mlApi } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import type { MlMetrics, MlStatus } from "@/lib/ml-types";
import { cn } from "@/lib/utils";

import { CATEGORY_ORDER, CATEGORY_SHORT, Stat, StatusBadge, WarningList, fmt, pct } from "./ml-shared";
import { PlayerExplorer } from "./player-explorer";
import { ProspectivePanel } from "./prospective-panel";

const TABS = ["overview", "performance", "calibration", "prospective", "explorer", "health"] as const;
type Tab = (typeof TABS)[number];

export function MlLabView() {
  const [tab, setTab] = useState<Tab>("overview");
  const status = useSWR("ml-status", () => mlApi.status());
  const metrics = useSWR(status.data?.loaded ? ["ml-metrics", status.data.active_version] : null, () => mlApi.metrics());

  return (
    <div className="space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
          <FlaskConical className="size-6 text-electric" /> ML Lab
        </h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Research dashboard for the v2 player-stat engine: chronological held-out evaluation, predictive
          uncertainty, calibration, and live projections. Projections are statistical estimates — not betting advice.
        </p>
      </div>

      <div className="flex flex-wrap gap-1">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "rounded-lg px-3 py-1.5 text-sm capitalize",
              tab === t ? "bg-primary/20 text-foreground ring-1 ring-primary/30" : "text-muted-foreground hover:bg-secondary/60",
            )}
          >
            {t === "explorer" ? "Player explorer" : t}
          </button>
        ))}
      </div>

      {status.error && <ErrorState error={status.error} onRetry={() => status.mutate()} />}
      {!status.data && !status.error && <LoadingRows />}
      {status.data && !status.data.loaded && (
        <Card className="border-red-500/40 bg-red-500/10 p-4 text-sm">
          No usable v2 model is loaded. Train one with <code>make ml-train</code>.
          <div className="mt-2">
            <WarningList warnings={status.data.warnings} />
          </div>
        </Card>
      )}
      {status.data?.loaded && (
        <>
          {tab === "overview" && <Overview status={status.data} metrics={metrics.data} />}
          {tab === "performance" && (metrics.data ? <Performance m={metrics.data} /> : <LoadingRows />)}
          {tab === "calibration" && (metrics.data ? <Calibration m={metrics.data} status={status.data} /> : <LoadingRows />)}
          {tab === "prospective" && <ProspectivePanel />}
          {tab === "explorer" && <PlayerExplorer />}
          {tab === "health" && <Health status={status.data} />}
        </>
      )}
    </div>
  );
}

function Overview({ status, metrics }: { status: MlStatus; metrics?: MlMetrics }) {
  const sp = status.split;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Active model" value={status.active_version} hint={`rollback: ${status.previous_version ?? "none"}`} />
        <Stat label="Trained" value={status.trained_at ? fmtDateTime(status.trained_at) : "—"} hint={`features ${status.feature_version}`} />
        <Stat label="Training-data cutoff" value={status.dataset_cutoff ? fmtDateTime(status.dataset_cutoff) : "—"} hint={`${status.final_games_since_training_cutoff ?? 0} final games since`} />
        <Stat label="Deploy fit rows" value={sp?.rows.deploy_fit.toLocaleString()} hint={`train ${sp?.rows.train.toLocaleString()} · val ${sp?.rows.val_eval.toLocaleString()} · test ${sp?.rows.test_eval.toLocaleString()}`} />
        <Stat label="Training period" value={sp ? `${sp.train_dates[0]} → ${sp.train_dates[1]}` : "—"} />
        <Stat label="Validation period" value={sp ? `${sp.val_dates[0]} → ${sp.val_dates[1]}` : "—"} hint="model selection + residual distribution" />
        <Stat label="Test period (untouched)" value={sp ? `${sp.test_dates[0]} → ${sp.test_dates[1]}` : "—"} hint="refit on train+val, scored once" />
        <Stat label="Odds archive" value={`${status.odds_archive?.snapshots.toLocaleString() ?? 0} snapshots`} hint={`${status.odds_archive?.graded.toLocaleString() ?? 0} graded · ${status.odds_archive?.games ?? 0} games`} />
      </div>
      <Card className="p-4">
        <p className="mb-3 text-sm font-semibold">Selected model & probability status per category</p>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {CATEGORY_ORDER.map((c) => (
            <div key={c} className="flex items-center justify-between rounded-lg border border-border/60 px-3 py-2">
              <div>
                <p className="text-sm font-medium">{CATEGORY_SHORT[c]}</p>
                <p className="text-[11px] text-muted-foreground">{status.selected_models?.[c] ?? "sum of components"}</p>
                {metrics?.test[c] && (
                  <p className="text-[11px] text-muted-foreground">
                    test MAE {fmt(metrics.test[c].model.mae, 3)} ({fmt(metrics.test[c].mae_improvement_vs_best_baseline_pct, 1)}% vs best baseline)
                  </p>
                )}
              </div>
              {status.probability_status?.[c] && <StatusBadge status={status.probability_status[c]} />}
            </div>
          ))}
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          Gates — {Object.entries(status.probability_gates?.rules ?? {}).map(([k, v]) => `${k}: ${v}`).join(" · ")}
        </p>
      </Card>
      <WarningList warnings={status.warnings} />
    </div>
  );
}

function Performance({ m }: { m: MlMetrics }) {
  const [sliceCat, setSliceCat] = useState("pts");
  const chart = CATEGORY_ORDER.map((c) => {
    const t = m.test[c];
    return {
      cat: CATEGORY_SHORT[c],
      Model: t.model.mae,
      "Best baseline": t.baselines[t.best_baseline].mae,
      "Last 10": t.baselines.last_10.mae,
      "Season avg": t.baselines.season_avg.mae,
      "Old v1": t.old_model?.old.mae,
    };
  });
  const slices = m.test[sliceCat]?.slices ?? {};
  return (
    <div className="space-y-4">
      <Card className="overflow-x-auto p-4">
        <p className="mb-2 text-sm font-semibold">Untouched test period — identical examples for every column</p>
        <table className="w-full text-sm [&_td]:px-2 [&_th]:px-2 [&_td]:whitespace-nowrap">
          <thead className="text-left text-xs text-muted-foreground">
            <tr>
              <th className="py-1">Category</th><th>n</th><th>Model MAE</th><th>RMSE</th><th>MedAE</th><th>Bias</th>
              <th>Best baseline</th><th>Last 10</th><th>Season avg</th><th>Old v1 (same rows)</th><th>Δ vs best</th>
            </tr>
          </thead>
          <tbody>
            {CATEGORY_ORDER.map((c) => {
              const t = m.test[c];
              return (
                <tr key={c} className="border-t border-border/50">
                  <td className="py-1.5 font-medium">{CATEGORY_SHORT[c]}</td>
                  <td>{t.model.n.toLocaleString()}</td>
                  <td className="font-semibold">{fmt(t.model.mae, 3)}</td>
                  <td>{fmt(t.model.rmse, 3)}</td>
                  <td>{fmt(t.model.median_ae, 2)}</td>
                  <td>{fmt(t.model.bias, 2)}</td>
                  <td>{fmt(t.baselines[t.best_baseline].mae, 3)} <span className="text-[11px] text-muted-foreground">{t.best_baseline}</span></td>
                  <td>{fmt(t.baselines.last_10.mae, 3)}</td>
                  <td>{fmt(t.baselines.season_avg.mae, 3)}</td>
                  <td>{t.old_model ? fmt(t.old_model.old.mae, 3) : "—"}</td>
                  <td className={t.mae_improvement_vs_best_baseline_pct > 0 ? "text-emerald-300" : "text-muted-foreground"}>
                    {fmt(t.mae_improvement_vs_best_baseline_pct, 2)}%
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {m.test.pts.old_model && <p className="mt-2 text-xs text-muted-foreground">Old v1: {m.test.pts.old_model.note}</p>}
      </Card>
      <Card className="p-4">
        <p className="mb-2 text-sm font-semibold">Test MAE: model vs baselines</p>
        <div className="h-72">
          <ResponsiveContainer>
            <BarChart data={chart}>
              <CartesianGrid strokeDasharray="3 3" stroke="#ffffff14" />
              <XAxis dataKey="cat" stroke="#9aa4b2" fontSize={12} />
              <YAxis stroke="#9aa4b2" fontSize={12} />
              <Tooltip contentStyle={{ background: "#111827", border: "1px solid #334155" }} formatter={(v) => (typeof v === "number" ? v.toFixed(3) : v)} />
              <Legend />
              <Bar dataKey="Model" fill="#4f7cff" />
              <Bar dataKey="Best baseline" fill="#a78bfa" />
              <Bar dataKey="Last 10" fill="#64748b" />
              <Bar dataKey="Season avg" fill="#334155" />
              <Bar dataKey="Old v1" fill="#f59e0b" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>
      <Card className="p-4">
        <div className="mb-2 flex items-center justify-between">
          <p className="text-sm font-semibold">Error by slice (test)</p>
          <select className="rounded-md border border-border bg-background px-2 py-1 text-sm" value={sliceCat} onChange={(e) => setSliceCat(e.target.value)}>
            {CATEGORY_ORDER.map((c) => <option key={c} value={c}>{CATEGORY_SHORT[c]}</option>)}
          </select>
        </div>
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {Object.entries(slices).map(([name, groups]) => (
            <div key={name} className="rounded-lg border border-border/60 p-2">
              <p className="mb-1 text-xs font-medium text-muted-foreground">{name.replaceAll("_", " ")}</p>
              <table className="w-full text-xs">
                <tbody>
                  {Object.entries(groups).map(([k, v]) => (
                    <tr key={k}><td className="py-0.5">{k}</td><td className="text-right">n {v.n}</td><td className="text-right">MAE {fmt(v.mae)}</td><td className="text-right">bias {fmt(v.bias)}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      </Card>
      <Card className="p-4">
        <p className="mb-2 text-sm font-semibold">Permutation importance (validation, MAE increase when shuffled)</p>
        <div className="grid gap-3 md:grid-cols-3">
          {Object.entries(m.feature_importance_validation ?? {}).map(([stat, rows]) => (
            <div key={stat}>
              <p className="text-xs font-medium uppercase text-muted-foreground">{stat}</p>
              {rows.slice(0, 10).map((r) => (
                <div key={r.feature} className="flex justify-between text-xs"><span>{r.feature}</span><span>{r.mae_increase.toFixed(3)}</span></div>
              ))}
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function Calibration({ m, status }: { m: MlMetrics; status: MlStatus }) {
  const [cat, setCat] = useState("pts");
  const s = m.synthetic_thresholds[cat];
  const real = m.real_lines.categories?.[cat];
  const curve = useMemo(() => {
    const pts: Record<string, number | undefined>[] = [];
    s?.empirical_joint.reliability?.forEach((b) => pts.push({ x: b.predicted_mean, synthetic: b.observed_rate }));
    real?.model.reliability?.forEach((b) => pts.push({ x: b.predicted_mean, real: b.observed_rate }));
    pts.push({ x: 0, ideal: 0 }, { x: 1, ideal: 1 });
    return pts.sort((a, b) => (a.x ?? 0) - (b.x ?? 0));
  }, [s, real]);
  return (
    <div className="space-y-4">
      <Card className="border-amber-500/30 bg-amber-500/5 p-4 text-xs text-muted-foreground">
        <p>
        <b className="text-amber-200">Synthetic thresholds</b> = floor(player L10 average) + 0.5, built from pregame data only. They test
        whether the predictive distribution is calibrated; they are not sportsbook lines and say nothing about profitability.{" "}
        <b className="text-amber-200">Archived real lines</b> are genuine pregame sportsbook offers (last observation before tip-off),
        scored against the fold model that never trained on those games. Sample: {m.real_lines.games ?? 0} games
        {m.real_lines.date_range ? ` (${m.real_lines.date_range[0].slice(0, 10)} → ${m.real_lines.date_range[1].slice(0, 10)})` : ""}.
        </p>
      </Card>
      <Card className="overflow-x-auto p-4">
        <table className="w-full text-sm [&_td]:px-2 [&_th]:px-2 [&_td]:whitespace-nowrap">
          <thead className="text-left text-xs text-muted-foreground">
            <tr>
              <th>Category</th><th>Status</th><th>Synthetic Brier</th><th>ECE</th><th>Normal (legacy) Brier / ECE</th><th>Constant Brier</th>
              <th>80% interval coverage</th><th>Real lines n</th><th>Real Brier / ECE</th><th>Market de-vig Brier (model on same)</th>
            </tr>
          </thead>
          <tbody>
            {CATEGORY_ORDER.map((c) => {
              const x = m.synthetic_thresholds[c];
              const r = m.real_lines.categories?.[c];
              return (
                <tr key={c} className={cn("border-t border-border/50 cursor-pointer", c === cat && "bg-primary/10")} onClick={() => setCat(c)}>
                  <td className="py-1.5 font-medium">{CATEGORY_SHORT[c]}</td>
                  <td>{status.probability_status?.[c] && <StatusBadge status={status.probability_status[c]} />}</td>
                  <td>{fmt(x.empirical_joint.brier, 4)}</td>
                  <td>{fmt(x.empirical_joint.ece, 4)}</td>
                  <td>{fmt(x.normal_legacy.brier, 4)} / {fmt(x.normal_legacy.ece, 4)}</td>
                  <td>{fmt(x.climatology_constant.brier, 4)}</td>
                  <td>{pct(x.interval_80_coverage)}</td>
                  <td>{r?.unique_lines ?? 0}</td>
                  <td>{r ? `${fmt(r.model.brier, 4)} / ${fmt(r.model.ece, 4)}` : "—"}</td>
                  <td>{r?.market_comparison ? `${fmt(r.market_comparison.market_devigged.brier, 4)} (${fmt(r.market_comparison.model.brier, 4)}) n=${r.market_comparison.n_book_lines}` : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
      <Card className="p-4">
        <p className="mb-2 text-sm font-semibold">Reliability — {CATEGORY_SHORT[cat]} (predicted P(over) vs observed)</p>
        <div className="h-72">
          <ResponsiveContainer>
            <LineChart data={curve}>
              <CartesianGrid strokeDasharray="3 3" stroke="#ffffff14" />
              <XAxis dataKey="x" type="number" domain={[0, 1]} stroke="#9aa4b2" fontSize={12} />
              <YAxis domain={[0, 1]} stroke="#9aa4b2" fontSize={12} />
              <Tooltip contentStyle={{ background: "#111827", border: "1px solid #334155" }} formatter={(v) => (typeof v === "number" ? v.toFixed(3) : v)} />
              <Legend />
              <Line dataKey="ideal" stroke="#64748b" strokeDasharray="4 4" dot={false} connectNulls />
              <Line dataKey="synthetic" stroke="#4f7cff" connectNulls />
              <Line dataKey="real" stroke="#f59e0b" connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>
    </div>
  );
}

function Health({ status }: { status: MlStatus }) {
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <p className="mb-2 text-sm font-semibold">Warnings</p>
        {status.warnings.length ? <WarningList warnings={status.warnings} /> : <EmptyState title="No warnings" />}
      </Card>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Last NBA sync" value={status.last_sync_at ? fmtDateTime(status.last_sync_at) : "never"} />
        <Stat label="Model load" value={status.model_load_seconds != null ? `${status.model_load_seconds}s` : "not loaded yet"} />
        <Stat label="Last batch inference" value={status.last_batch_seconds != null ? `${status.last_batch_seconds}s` : "—"} />
        <Stat label="Flags" value={Object.entries(status.flags).filter(([, v]) => v).length + "/4 on"} hint={Object.entries(status.flags).map(([k, v]) => `${k.replace("enable_ml_", "")}=${v ? "on" : "off"}`).join(" · ")} />
      </div>
      <Card className="p-4 text-sm">
        <p className="mb-2 font-semibold">Acceptance checks</p>
        {Object.entries(status.acceptance_checks ?? {}).map(([k, v]) => (
          <p key={k} className={v ? "text-emerald-300" : "text-red-300"}>{v ? "✓" : "✗"} {k.replaceAll("_", " ")}</p>
        ))}
        <p className="mt-3 mb-1 font-semibold">Training stage timings (s)</p>
        <p className="text-xs text-muted-foreground">{Object.entries(status.timings_seconds ?? {}).map(([k, v]) => `${k} ${v}`).join(" · ")}</p>
        <p className="mt-3 mb-1 font-semibold">Odds archive</p>
        <p className="text-xs text-muted-foreground">
          {status.odds_archive ? Object.entries(status.odds_archive.by_result).map(([k, v]) => `${k} ${v.toLocaleString()}`).join(" · ") : "—"} · live-import snapshots{" "}
          {status.odds_archive?.from_live_imports.toLocaleString()} · backfilled last-seen {status.odds_archive?.from_prop_offers_last_seen.toLocaleString()}
        </p>
      </Card>
    </div>
  );
}

export function PlayerSearchBox({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return <Input placeholder="Filter players" value={value} onChange={(e) => onChange(e.target.value)} className="max-w-xs" />;
}
