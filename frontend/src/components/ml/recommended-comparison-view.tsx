"use client";

import { Sparkles } from "lucide-react";
import { useState } from "react";
import useSWR from "swr";

import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { mlApi } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { CATEGORY_ORDER, CATEGORY_SHORT, StatusBadge, WarningList, pct } from "./ml-shared";

const selectCls = "rounded-md border border-border bg-background px-3 py-2 text-sm";

export function RecommendedComparisonView() {
  const [prizepicksOnly, setPrizepicksOnly] = useState(false);
  const [sportsbook, setSportsbook] = useState("");
  const [category, setCategory] = useState("");
  const [side, setSide] = useState("");
  const [gameDate, setGameDate] = useState("");
  const [q, setQ] = useState("");
  const [minSample, setMinSample] = useState(10);
  const [eligibleOnly, setEligibleOnly] = useState(true);

  const data = useSWR(
    ["ml-comparison", prizepicksOnly, sportsbook, category, side, gameDate, q, minSample, eligibleOnly],
    () =>
      mlApi.comparison({
        prizepicksOnly,
        sportsbook: prizepicksOnly ? undefined : sportsbook || undefined,
        category: category || undefined,
        side: side || undefined,
        gameDate: gameDate || undefined,
        q: q || undefined,
        minSample,
        eligibleOnly,
      }),
    { keepPreviousData: true },
  );
  const d = data.data;
  const validated = d?.mode === "validated";

  return (
    <div className="space-y-5">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
          <Sparkles className="size-6 text-electric" /> Recommended
          <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-200">
            {validated ? "Validated categories only" : "Experimental comparison"}
          </span>
        </h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Imported sportsbook and PrizePicks lines compared against the v2 projection model. Nothing here is a
          guaranteed or profitable pick.
        </p>
      </div>

      {d && (
        <Card className={cn("p-4 text-sm", validated ? "border-emerald-500/30 bg-emerald-500/5" : "border-amber-500/30 bg-amber-500/5")}>
          <p>{d.mode_explanation}</p>
          <div className="mt-2 flex flex-wrap gap-2 text-xs">
            {CATEGORY_ORDER.map((c) =>
              d.gating.probability_status?.[c] ? (
                <span key={c} className="flex items-center gap-1">
                  {CATEGORY_SHORT[c]} <StatusBadge status={d.gating.probability_status[c]} />
                </span>
              ) : null,
            )}
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            Eligibility: ≥10 prior appearances (and your minimum sample), category not withheld by the calibration gate,
            no recent team change or long layoff{validated ? ", category validated on archived real lines" : ""}. Projection
            gap = (projected mean − line) ÷ predictive SD — a descriptive distance, not a win probability.
          </p>
        </Card>
      )}

      <Card className="border-border/80 bg-surface/60 p-4">
        <div className="mb-3 flex items-center gap-3">
          <button
            onClick={() => setPrizepicksOnly((v) => !v)}
            className={cn(
              "rounded-lg border px-4 py-2 text-sm font-semibold transition",
              prizepicksOnly ? "border-violet-400/60 bg-violet-500/20 text-violet-100" : "border-border text-muted-foreground hover:bg-secondary/60",
            )}
          >
            {prizepicksOnly ? "✓ PrizePicks only" : "PrizePicks only"}
          </button>
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            <input type="checkbox" checked={eligibleOnly} onChange={(e) => setEligibleOnly(e.target.checked)} />
            Eligible rows only
          </label>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
          <select className={selectCls} value={sportsbook} disabled={prizepicksOnly} onChange={(e) => setSportsbook(e.target.value)}>
            <option value="">All books</option>
            {d?.sportsbooks.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
          <select className={selectCls} value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">All categories</option>
            {CATEGORY_ORDER.map((c) => <option key={c} value={c}>{CATEGORY_SHORT[c]}</option>)}
          </select>
          <select className={selectCls} value={side} onChange={(e) => setSide(e.target.value)}>
            <option value="">Over & under</option>
            <option value="over">Over</option>
            <option value="under">Under</option>
          </select>
          <Input type="date" value={gameDate} onChange={(e) => setGameDate(e.target.value)} />
          <Input placeholder="Player" value={q} onChange={(e) => setQ(e.target.value)} />
          <select className={selectCls} value={String(minSample)} onChange={(e) => setMinSample(Number(e.target.value))}>
            <option value="10">Min sample: 10+</option>
            <option value="20">Min sample: 20+</option>
            <option value="40">Min sample: 40+</option>
          </select>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          {d ? `${d.total.toLocaleString()} rows of ${d.total_offers_considered.toLocaleString()} active upcoming offers` : "Loading…"} · odds import{" "}
          {d?.last_import_finished_at ? fmtDateTime(d.last_import_finished_at) : "—"} · model {d?.model_version ?? "—"}. This page never calls the odds provider.
        </p>
      </Card>

      {data.error && <ErrorState error={data.error} onRetry={() => data.mutate()} />}
      {!d && !data.error && <LoadingRows />}
      {d && d.mode === "disabled" && <EmptyState title="ML comparison disabled" description={d.mode_explanation} />}
      {d && d.mode !== "disabled" && d.rows.length === 0 && (
        <EmptyState
          title="No matching lines"
          description="There are no active imported lines for upcoming games that match these filters. Lines appear after the next scheduled odds import."
        />
      )}
      {d && d.rows.length > 0 && (
        <Card className="overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead className="bg-surface/60 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2">Player</th><th>Game</th><th>Book</th><th>Line</th><th>Projection (80%)</th>
                <th>Gap</th><th>Model lean</th><th>{validated ? "P(side)" : "Probability"}</th><th>L10 / L20 hit</th><th>HCS</th><th>Status</th>
              </tr>
            </thead>
            <tbody>
              {d.rows.map((r) => (
                <tr key={r.offer_id} className={cn("border-t border-border/50 align-top", !r.eligible && "opacity-60")}>
                  <td className="px-3 py-2">
                    <p className="font-medium">{r.player_name}</p>
                    <p className="text-[11px] text-muted-foreground">{r.appearances} prior games</p>
                  </td>
                  <td className="py-2 text-xs">{r.team_abbreviation} vs {r.opponent_abbreviation}<br />{fmtDateTime(r.start_time)}</td>
                  <td className="py-2 text-xs">{r.sportsbook}</td>
                  <td className="py-2">
                    <span className="font-medium capitalize">{r.side}</span> {r.line} {CATEGORY_SHORT[r.category] ?? r.category_label}
                    {r.american_odds != null && <span className="ml-1 text-[11px] text-muted-foreground">({r.american_odds > 0 ? "+" : ""}{r.american_odds})</span>}
                  </td>
                  <td className="py-2">{r.projected_mean.toFixed(1)} <span className="text-[11px] text-muted-foreground">({r.p10}–{r.p90})</span></td>
                  <td className="py-2">{r.projection_gap > 0 ? "+" : ""}{r.projection_gap.toFixed(2)}</td>
                  <td className={cn("py-2 capitalize", r.agrees_with_side ? "text-emerald-300" : "text-muted-foreground")}>{r.model_leans}</td>
                  <td className="py-2">{r.p_side != null ? pct(r.p_side) : <span className="text-xs text-muted-foreground">withheld</span>}</td>
                  <td className="py-2 text-xs">
                    {r.l10_hit_pct != null ? pct(r.l10_hit_pct / 100, 0) : "—"} / {r.l20_hit_pct != null ? pct(r.l20_hit_pct / 100, 0) : "—"}
                    <p className="text-[10px] text-muted-foreground">historical, not a probability</p>
                  </td>
                  <td className="py-2 text-xs">{r.hcs_score != null ? r.hcs_score.toFixed(1) : "—"}</td>
                  <td className="py-2 pr-3">
                    <StatusBadge status={r.probability_status} />
                    {!r.eligible && <p className="mt-1 text-[10px] text-red-300">{r.ineligible_reasons.join("; ")}</p>}
                    {r.warnings.length > 0 && <div className="mt-1 max-w-56"><WarningList warnings={r.warnings} /></div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
