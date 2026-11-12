"use client";

import { Flame } from "lucide-react";
import { useEffect, useState } from "react";
import useSWR from "swr";

import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { PropAnalyzerPanel } from "@/components/prop-finder/prop-analyzer-panel";
import { StreakViz } from "@/components/hit-streaks/streak-viz";
import { Card } from "@/components/ui/card";
import { api } from "@/lib/api";
import { fmtDateTime, fmtNum } from "@/lib/format";
import { useCategories } from "@/lib/hooks";
import type { HitStreakRow } from "@/lib/types";
import { cn } from "@/lib/utils";

export function HitStreaksView() {
  const [category, setCategory] = useState("");
  const [pickSide, setPickSide] = useState<"" | "over" | "under">("");
  const [minStreak, setMinStreak] = useState(1);
  const [gameDate, setGameDate] = useState("");
  const [currentSeasonOnly, setCurrentSeasonOnly] = useState(false);
  const [sort, setSort] = useState("streak");
  const [page, setPage] = useState(0);
  const pageSize = 25;
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const categories = useCategories();

  const list = useSWR(
    ["hit-streaks", category, pickSide, minStreak, gameDate, currentSeasonOnly, sort, page],
    () =>
      api.hitStreaks({
        category: category || undefined,
        pickSide: pickSide || undefined,
        minStreak,
        gameDate: gameDate || undefined,
        currentSeasonOnly,
        sort,
        limit: pageSize,
        offset: page * pageSize,
      }),
  );

  useEffect(() => {
    setPage(0);
  }, [category, pickSide, minStreak, gameDate, currentSeasonOnly, sort]);

  const rows = list.data?.rows ?? [];
  const total = list.data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
          <Flame className="size-6 text-electric" /> Hit Streaks
        </h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          PrizePicks NBA lines with the longest consecutive historical hit streaks (completed appearances only).
          DNPs and incomplete box scores are excluded — not counted as hits or misses.
        </p>
        {list.data && (
          <p className="mt-1 text-xs text-muted-foreground">
            {list.data.total_eligible_offers} eligible PrizePicks offers · {list.data.total_available} after streak
            filters · loaded in {list.data.timing_ms ?? "—"}ms
          </p>
        )}
      </div>

      <Card className="border-border/80 bg-surface/60 p-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-7">
          <select
            className="rounded-md border border-border bg-background px-3 py-2 text-sm"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            <option value="">All stats</option>
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
          <select
            className="rounded-md border border-border bg-background px-3 py-2 text-sm"
            value={String(minStreak)}
            onChange={(e) => setMinStreak(Number(e.target.value))}
          >
            {[1, 3, 5, 7, 10].map((n) => (
              <option key={n} value={n}>Min streak {n}+</option>
            ))}
          </select>
          <input
            type="date"
            className="rounded-md border border-border bg-background px-3 py-2 text-sm"
            value={gameDate}
            onChange={(e) => setGameDate(e.target.value)}
          />
          <label className="flex items-center gap-2 rounded-md border border-border bg-background px-3 py-2 text-sm">
            <input
              type="checkbox"
              checked={currentSeasonOnly}
              onChange={(e) => setCurrentSeasonOnly(e.target.checked)}
            />
            Current season only
          </label>
          <select
            className="rounded-md border border-border bg-background px-3 py-2 text-sm lg:col-span-2"
            value={sort}
            onChange={(e) => setSort(e.target.value)}
          >
            <option value="streak">Sort: longest streak</option>
            <option value="hcs">Sort: highest HCS</option>
            <option value="clearance">Sort: avg clearance margin</option>
            <option value="l10_hit_pct">Sort: best L10 hit rate</option>
          </select>
        </div>
      </Card>

      {list.error && <ErrorState error={list.error} />}
      {list.isLoading && <LoadingRows />}

      {!list.isLoading && !list.error && rows.length === 0 && (
        <EmptyState title="No streaks match filters" description="Try lowering the minimum streak or clearing filters." />
      )}

      {rows.length > 0 && (
        <Card className="overflow-hidden border-border/80">
          <StreakTable rows={rows} onSelect={setSelectedId} />
          <div className="flex items-center justify-between border-t border-border px-4 py-3 text-sm">
            <span className="text-muted-foreground">
              Page {page + 1} of {pageCount} (top {total} streaks)
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={page === 0}
                className="rounded-md border border-border px-3 py-1 disabled:opacity-40"
                onClick={() => setPage((p) => Math.max(0, p - 1))}
              >
                Previous
              </button>
              <button
                type="button"
                disabled={(page + 1) * pageSize >= total}
                className="rounded-md border border-border px-3 py-1 disabled:opacity-40"
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </button>
            </div>
          </div>
        </Card>
      )}

      {list.data?.disclaimer && (
        <p className="text-xs text-muted-foreground">{list.data.disclaimer}</p>
      )}

      {selectedId != null && <PropAnalyzerPanel propId={selectedId} onClose={() => setSelectedId(null)} />}
    </div>
  );
}

function StreakTable({ rows, onSelect }: { rows: HitStreakRow[]; onSelect: (id: number) => void }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[960px] text-sm">
        <thead className="bg-surface-2 text-[11px] uppercase text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left">Player</th>
            <th className="px-3 py-2 text-left">Matchup</th>
            <th className="px-3 py-2 text-left">Line</th>
            <th className="px-3 py-2 text-right">Streak</th>
            <th className="px-3 py-2 text-left">Last 10</th>
            <th className="px-3 py-2 text-right">L10</th>
            <th className="px-3 py-2 text-right">HCS</th>
            <th className="px-3 py-2 text-right">Avg margin</th>
            <th className="px-3 py-2 text-left">Start</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.offer_id}
              className="cursor-pointer border-t border-border/60 transition hover:bg-secondary/30"
              onClick={() => onSelect(row.offer_id)}
            >
              <td className="px-3 py-2">
                <div className="font-medium">{row.player_name}</div>
                {row.team_abbreviation && (
                  <div className="text-xs text-muted-foreground">{row.team_abbreviation}</div>
                )}
                {row.streak.missing_data_flags.length > 0 && (
                  <StreakWarnings flags={row.streak.missing_data_flags} />
                )}
              </td>
              <td className="px-3 py-2 text-muted-foreground">
                {row.matchup_label}
                {row.opponent_abbreviation && ` · vs ${row.opponent_abbreviation}`}
              </td>
              <td className="px-3 py-2">
                <span className={cn("font-semibold uppercase", row.pick_side === "over" ? "text-over" : "text-under")}>
                  {row.pick_side} {row.line}
                </span>
                <br />
                <span className="text-xs text-muted-foreground">{row.category.short_label}</span>
              </td>
              <td className="px-3 py-2 text-right">
                <span className="text-lg font-bold tabular text-electric">{row.streak.streak_label}</span>
              </td>
              <td className="px-3 py-2">
                <StreakViz results={row.streak.recent_results} line={row.line} />
              </td>
              <td className="px-3 py-2 text-right tabular text-xs">{row.streak.l10_record}</td>
              <td className="px-3 py-2 text-right tabular">{row.hcs_score != null ? fmtNum(row.hcs_score, 1) : "—"}</td>
              <td className="px-3 py-2 text-right tabular">
                {row.streak.avg_clearance_margin != null ? fmtNum(row.streak.avg_clearance_margin, 2) : "—"}
              </td>
              <td className="px-3 py-2 text-xs text-muted-foreground whitespace-nowrap">
                {row.game_start_time ? fmtDateTime(row.game_start_time) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StreakWarnings({ flags }: { flags: string[] }) {
  const label = flags.includes("no_completed_appearances")
    ? "No history"
    : flags.includes("limited_history")
      ? "Limited history"
      : flags.join(", ");
  return <span className="text-[10px] text-push">{label}</span>;
}
