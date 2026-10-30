"use client";

import { RefreshCw, Search, TrendingUp } from "lucide-react";
import { useEffect, useState } from "react";
import useSWR from "swr";

import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { fmtDateTime, fmtNum } from "@/lib/format";
import { fmtHitSample } from "@/lib/prop-hit-format";
import { useCategories } from "@/lib/hooks";
import { PropAnalyzerPanel } from "@/components/prop-finder/prop-analyzer-panel";
import type { PropFinderRow } from "@/lib/types";
import { cn } from "@/lib/utils";

function hitCell(
  hits: number | null | undefined,
  attempts: number | null | undefined,
  pct: number | null,
) {
  return fmtHitSample(hits, attempts, pct);
}

export function PropFinderView() {
  const [sportsbook, setSportsbook] = useState("");
  const [category, setCategory] = useState("");
  const [pickSide, setPickSide] = useState<"" | "over" | "under">("");
  const [minHit, setMinHit] = useState("");
  const [minGames, setMinGames] = useState(10);
  const [sort, setSort] = useState("hcs");
  const [page, setPage] = useState(0);
  const pageSize = 10;
  const maxPages = 10;
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const categories = useCategories();

  const status = useSWR("prop-finder-status", () => api.propFinderStatus(), {
    refreshInterval: (data) => (data?.refresh_in_progress ? 3000 : 0),
  });
  const list = useSWR(
    ["prop-finder", sportsbook, category, pickSide, minHit, minGames, sort, page],
    () =>
      api.propFinder({
        sportsbook: sportsbook || undefined,
        category: category || undefined,
        pickSide: pickSide || undefined,
        minHitPct: minHit ? Number(minHit) : undefined,
        minGames,
        sort,
        limit: pageSize,
        offset: page * pageSize,
      }),
  );
  useEffect(() => {
    setPage(0);
  }, [sportsbook, category, pickSide, minHit, minGames, sort]);

  const refresh = () => {
    void api.refreshPropOdds().then(() => status.mutate());
  };

  useEffect(() => {
    if (!status.data?.refresh_in_progress) {
      list.mutate();
    }
  }, [status.data?.refresh_in_progress, status.data?.last_run_finished_at]);

  const rows = list.data?.rows ?? [];
  const total = list.data?.total ?? 0;
  const totalAvailable =
    list.data?.total_available ?? status.data?.offers_eligible_upcoming ?? total;
  const pageCount = Math.min(maxPages, Math.max(1, Math.ceil(total / pageSize)));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <TrendingUp className="size-6 text-electric" /> Prop Finder
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Live sportsbook player props ranked by historical hit rates against the posted line — not ML predictions.
          </p>
        </div>
        <Button
          onClick={refresh}
          disabled={!status.data?.configured || status.data?.refresh_in_progress}
          className="gap-2"
        >
          <RefreshCw className={cn("size-4", status.data?.refresh_in_progress && "animate-spin")} />
          {status.data?.refresh_in_progress ? "Refreshing…" : "Refresh odds"}
        </Button>
      </div>

      {status.data?.last_run_error && !status.data.refresh_in_progress && (
        <Card className="border-red-500/40 bg-red-500/10 p-4 text-sm text-red-200">
          Last odds refresh failed: {status.data.last_run_error}
        </Card>
      )}

      {status.data && !status.data.configured && (
        <Card className="border-amber-500/40 bg-amber-500/10 p-4 text-sm">
          Unabated API is not configured. Add <code className="text-xs">UNABATED_API_KEY</code> to{" "}
          <code className="text-xs">backend/.env</code> or use manual line entry below.
        </Card>
      )}

      <Card className="border-border/80 bg-surface/60 p-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
          <Input placeholder="Sportsbook" value={sportsbook} onChange={(e) => setSportsbook(e.target.value)} />
          <select
            className="rounded-md border border-border bg-background px-3 py-2 text-sm"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            <option value="">All categories</option>
            {categories.data?.map((c) => (
              <option key={c.key} value={c.key}>{c.label}</option>
            ))}
          </select>
          <select
            className="rounded-md border border-border bg-background px-3 py-2 text-sm"
            value={pickSide}
            onChange={(e) => setPickSide(e.target.value as "" | "over" | "under")}
          >
            <option value="">Over & under</option>
            <option value="over">Over</option>
            <option value="under">Under</option>
          </select>
          <Input placeholder="Min hit %" value={minHit} onChange={(e) => setMinHit(e.target.value)} />
          <select
            className="rounded-md border border-border bg-background px-3 py-2 text-sm"
            value={String(minGames)}
            onChange={(e) => setMinGames(Number(e.target.value))}
          >
            <option value="1">Min games: 1+</option>
            <option value="5">Min games: 5+</option>
            <option value="10">Min games: 10+</option>
            <option value="20">Min games: 20+</option>
          </select>
          <select
            className="rounded-md border border-border bg-background px-3 py-2 text-sm"
            value={sort}
            onChange={(e) => setSort(e.target.value)}
          >
            <option value="hcs">Sort: HCS (L20 window)</option>
            <option value="wilson_l10">Sort: L10 Wilson (95%)</option>
            <option value="wilson_l5">Sort: L5 Wilson (95%)</option>
            <option value="wilson_l20">Sort: L20 Wilson (95%)</option>
            <option value="wilson_h2h">Sort: H2H Wilson (95%)</option>
            <option value="l10">Sort: L10 raw hit %</option>
            <option value="l5">Sort: L5 raw hit %</option>
            <option value="l20">Sort: L20 raw hit %</option>
            <option value="h2h">Sort: H2H raw hit %</option>
            <option value="time">Sort: game time</option>
          </select>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          Showing top {total.toLocaleString()} of {Number(totalAvailable).toLocaleString()} eligible upcoming offers
          (ranked globally, then paginated 10 per page). Odds import{" "}
          {list.data?.last_import_finished_at ? fmtDateTime(list.data.last_import_finished_at) : "—"} · Hit rates{" "}
          {list.data?.last_hit_computed_at ? fmtDateTime(list.data.last_hit_computed_at) : "—"}
          {status.data?.refresh_in_progress && (
            <>
              {" "}
              · Refresh in progress
              {status.data.refresh_progress?.processed != null && status.data.refresh_progress?.parsed_total
                ? ` (${status.data.refresh_progress.processed}/${status.data.refresh_progress.parsed_total})`
                : ""}
            </>
          )}
          {process.env.NODE_ENV === "development" && status.data?.diagnostics && (
            <>
              {" "}
              · Dev: active matched primary{" "}
              {status.data.diagnostics.offers_active_matched_primary?.toLocaleString() ?? "—"}, eligible upcoming{" "}
              {status.data.diagnostics.offers_eligible_upcoming?.toLocaleString() ?? "—"}
              {status.data.diagnostics.last_import_duration_ms != null
                ? `, last import ${status.data.diagnostics.last_import_duration_ms}ms`
                : ""}
              {status.data.diagnostics.last_hit_reused_offer != null
                ? `, HCS reused ${status.data.diagnostics.last_hit_reused_offer}`
                : ""}
              {status.data.diagnostics.last_hit_computed != null
                ? ` / computed ${status.data.diagnostics.last_hit_computed}`
                : ""}
            </>
          )}
        </p>
      </Card>

      {list.error && <ErrorState error={list.error} onRetry={() => list.mutate()} />}
      {!list.data && !list.error && <LoadingRows />}
      {list.data && rows.length === 0 && (
        <EmptyState
          title="No props to show"
          description={
            (status.data?.offers_eligible_upcoming ?? 0) === 0 && (status.data?.offers_matched ?? 0) > 0
              ? "No upcoming matched lines — past games were excluded. Refresh odds after the next slate is loaded."
              : "Refresh odds from Unabated or add a manual line. Filters may also hide results."
          }
        />
      )}

      {rows.length > 0 && (
        <div className="panel overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-muted-foreground">
              <tr>
                <th className="p-3">Player</th>
                <th className="p-3">Matchup</th>
                <th className="p-3">Book</th>
                <th className="p-3">Prop</th>
                <th className="p-3">Odds</th>
                <th className="p-3">L5</th>
                <th className="p-3">HCS</th>
                <th className="p-3">L10</th>
                <th className="p-3">L20</th>
                <th className="p-3">H2H</th>
                <th className="p-3">Avg</th>
                <th className="p-3">Time</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r: PropFinderRow) => (
                <tr
                  key={r.id}
                  className={cn(
                    "border-t border-border/60 cursor-pointer hover:bg-primary/5",
                    selectedId === r.id && "bg-primary/10",
                  )}
                  onClick={() => setSelectedId(r.id)}
                >
                  <td className="p-3 font-medium">{r.player_name}</td>
                  <td className="p-3 text-xs text-muted-foreground">{r.matchup_label}</td>
                  <td className="p-3">{r.sportsbook}</td>
                  <td className="p-3">
                    {r.category.short_label} {r.pick_side} {r.line}
                    {r.is_alternate_line && <span className="ml-1 text-[10px] text-muted-foreground">alt</span>}
                  </td>
                  <td className="p-3 tabular">{r.american_odds ?? "—"}</td>
                  <td className="p-3 tabular text-xs">{hitCell(r.l5_hits, r.l5_attempts, r.l5_hit_pct)}</td>
                  <td className="p-3 tabular font-semibold text-electric">{fmtNum(r.hcs_score, 1)}</td>
                  <td className="p-3 tabular text-xs font-semibold">
                    {hitCell(r.l10_hits, r.l10_attempts, r.l10_hit_pct)}
                  </td>
                  <td className="p-3 tabular text-xs">{hitCell(r.l20_hits, r.l20_attempts, r.l20_hit_pct)}</td>
                  <td className="p-3 tabular text-xs">{hitCell(r.h2h_hits, r.h2h_attempts, r.h2h_hit_pct)}</td>
                  <td className="p-3 tabular">{fmtNum(r.historical_avg)}</td>
                  <td className="p-3 text-xs whitespace-nowrap">{r.game_start_time ? fmtDateTime(r.game_start_time) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {total > pageSize && (
        <div className="flex items-center justify-between gap-3 text-sm">
          <p className="text-muted-foreground">
            Page {page + 1} of {pageCount} · {pageSize} per page
          </p>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page + 1 >= pageCount || page + 1 >= maxPages}
              onClick={() => setPage((p) => Math.min(p + 1, maxPages - 1))}
            >
              Next
            </Button>
          </div>
        </div>
      )}

      {selectedId != null && (
        <PropAnalyzerPanel propId={selectedId} onClose={() => setSelectedId(null)} />
      )}

      <ManualEntryHint />
    </div>
  );
}

function ManualEntryHint() {
  return (
    <Card className="border-dashed border-border/80 p-4 text-sm text-muted-foreground">
      <p className="flex items-center gap-2 font-medium text-foreground">
        <Search className="size-4" /> Manual lines
      </p>
      <p className="mt-1">
        POST to <code className="text-xs">/api/prop-finder/manual</code> or upload CSV via{" "}
        <code className="text-xs">/api/prop-finder/import-csv</code> when Unabated markets are unavailable.
      </p>
    </Card>
  );
}
