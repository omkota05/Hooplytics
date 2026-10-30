"use client";

import { ExternalLink, X } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";

import { HcsBreakdownCard } from "@/components/analysis/hcs-breakdown";
import { HitRateSummary } from "@/components/analysis/hit-rate-summary";
import { PlayerAnalysis } from "@/components/analysis/player-analysis";
import { PlayerOpportunitySection } from "@/components/analysis/player-opportunity-section";
import { ErrorState, Spinner } from "@/components/common/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { fmtDateTime, fmtNum, fmtShortDate } from "@/lib/format";
import { fmtHitSample } from "@/lib/prop-hit-format";
import { useCategories, useTeams } from "@/lib/hooks";
import type { PropAnalyzerGameRow, PropHitWindow } from "@/lib/types";
import { cn } from "@/lib/utils";

const HIT_ORDER = ["L5", "L10", "L15", "L20", "L30", "season", "H2H_L5", "H2H_L3", "H2H_L10"];

function sortWindows(windows: PropHitWindow[]) {
  return [...windows].sort((a, b) => {
    const ai = HIT_ORDER.indexOf(a.window);
    const bi = HIT_ORDER.indexOf(b.window);
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
  });
}

function BetResult({ pickSide, outcome }: { pickSide: "over" | "under"; outcome: "over" | "under" | "push" | null }) {
  if (!outcome) return <span>—</span>;
  if (outcome === "push") {
    return <span className="text-push text-xs font-semibold uppercase">Push</span>;
  }
  const hit = pickSide === outcome;
  return (
    <span className={cn("text-xs font-semibold uppercase", hit ? "text-over" : "text-under")}>
      {hit ? "Hit" : "Miss"}
    </span>
  );
}

function PropGameLogTable({
  rows,
  pickSide,
  line,
  statLabel,
}: {
  rows: PropAnalyzerGameRow[];
  pickSide: "over" | "under";
  line: number;
  statLabel: string;
}) {
  const [sortKey, setSortKey] = useState<"date" | "prop">("date");
  const [windowN, setWindowN] = useState(20);

  const displayed = useMemo(() => {
    let list = rows.slice(0, windowN);
    if (sortKey === "prop") {
      list = [...list].sort((a, b) => (b.prop_value ?? -1) - (a.prop_value ?? -1));
    }
    return list;
  }, [rows, sortKey, windowN]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Recent games</h3>
        <div className="flex gap-2 text-xs">
          <select
            className="rounded-md border border-border bg-background px-2 py-1"
            value={windowN}
            onChange={(e) => setWindowN(Number(e.target.value))}
          >
            {[5, 10, 20, 50].map((n) => (
              <option key={n} value={n}>Last {n}</option>
            ))}
          </select>
          <Button variant="outline" size="sm" onClick={() => setSortKey(sortKey === "date" ? "prop" : "date")}>
            Sort: {sortKey === "date" ? "date" : statLabel}
          </Button>
        </div>
      </div>
      <div className="max-h-80 overflow-auto rounded-xl border border-border">
        <table className="w-full text-sm tabular">
          <thead className="sticky top-0 bg-surface-2 text-[11px] uppercase text-muted-foreground">
            <tr>
              <th className="px-2 py-2 text-left">Date</th>
              <th className="px-2 py-2 text-left">Opp</th>
              <th className="px-2 py-2 text-right">Min</th>
              <th className="px-2 py-2 text-right">PTS</th>
              <th className="px-2 py-2 text-right">REB</th>
              <th className="px-2 py-2 text-right">AST</th>
              <th className="px-2 py-2 text-right">FGA</th>
              <th className="px-2 py-2 text-right">3PA</th>
              <th className="px-2 py-2 text-right">{statLabel}</th>
              <th className="px-2 py-2 text-right">{pickSide} {line}</th>
            </tr>
          </thead>
          <tbody>
            {displayed.map((g) => (
              <tr key={g.game_id} className="border-t border-border/60">
                <td className="px-2 py-1.5">{fmtShortDate(g.game_date)}</td>
                <td className="px-2 py-1.5">{g.is_home ? "vs" : "@"} {g.opponent.abbreviation}</td>
                <td className="px-2 py-1.5 text-right">{g.minutes != null ? fmtNum(g.minutes, 0) : "—"}</td>
                <td className="px-2 py-1.5 text-right">{g.pts ?? "—"}</td>
                <td className="px-2 py-1.5 text-right">{g.reb ?? "—"}</td>
                <td className="px-2 py-1.5 text-right">{g.ast ?? "—"}</td>
                <td className="px-2 py-1.5 text-right">{g.fga ?? "—"}</td>
                <td className="px-2 py-1.5 text-right">{g.fg3a ?? "—"}</td>
                <td className="px-2 py-1.5 text-right font-medium">{g.prop_value ?? "—"}</td>
                <td className="px-2 py-1.5 text-right">
                  <BetResult pickSide={pickSide} outcome={g.outcome} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function PropAnalyzerPanel({ propId, onClose }: { propId: number; onClose: () => void }) {
  const analyzer = useSWR(["prop-analyzer", propId], () => api.propFinderAnalyzer(propId));
  const categories = useCategories();
  const teams = useTeams();
  const prop = analyzer.data?.prop;
  const playerId = prop?.player_id;

  const profile = useSWR(
    playerId ? ["profile", playerId] : null,
    () => api.playerProfile(playerId!),
    { revalidateOnFocus: false },
  );

  const windows = useMemo(() => (prop ? sortWindows(prop.hit_windows) : []), [prop]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button type="button" className="absolute inset-0 bg-black/65" aria-label="Close" onClick={onClose} />
      <div className="relative flex h-full w-full max-w-3xl flex-col border-l border-border bg-background shadow-2xl">
        <header className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0">
            {analyzer.error && <ErrorState error={analyzer.error} />}
            {!prop && !analyzer.error && <Skeleton className="h-10 w-64" />}
            {prop && (
              <>
                <h2 className="truncate text-xl font-bold">{prop.player_name}</h2>
                <p className="text-sm text-muted-foreground">
                  {prop.matchup_label} · {prop.category.label}{" "}
                  <span className="font-medium text-foreground">
                    {prop.pick_side.toUpperCase()} {prop.line}
                  </span>
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {prop.sportsbook}
                  {prop.american_odds != null && ` · ${prop.american_odds > 0 ? "+" : ""}${prop.american_odds}`}
                  {prop.game_start_time && ` · ${fmtDateTime(prop.game_start_time)}`}
                  {prop.line_modified_at && ` · Line updated ${fmtDateTime(prop.line_modified_at)}`}
                </p>
              </>
            )}
          </div>
          <div className="flex shrink-0 gap-2">
            {analyzer.isValidating && <Spinner />}
            <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close panel">
              <X className="size-5" />
            </Button>
          </div>
        </header>

        <div className="flex-1 space-y-6 overflow-y-auto px-5 py-4">
          {prop && (
            <div className="flex flex-wrap gap-2">
              {prop.player_analysis_href && (
                <Link href={prop.player_analysis_href}>
                  <Button variant="outline" size="sm">Full player profile</Button>
                </Link>
              )}
              {prop.deep_link_published && (
                <a href={prop.deep_link_published} target="_blank" rel="noopener noreferrer">
                  <Button variant="secondary" size="sm" className="gap-1">
                    Sportsbook <ExternalLink className="size-3.5" />
                  </Button>
                </a>
              )}
              {prop.source_kind !== "unabated" && <Badge variant="outline">Manual line</Badge>}
            </div>
          )}

          {prop?.hcs_breakdown && <HcsBreakdownCard breakdown={prop.hcs_breakdown} />}

          {prop && windows.length > 0 && (
            <section>
              <h3 className="mb-3 text-sm font-semibold">Historical hit rates vs {prop.line} line</h3>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {windows.map((w) => {
                  const pct = prop.pick_side === "over" ? w.over_hit_pct : w.under_hit_pct;
                  return (
                    <div key={w.window} className="rounded-lg bg-secondary/40 px-3 py-2">
                      <p className="text-[10px] uppercase text-muted-foreground">{w.window}</p>
                      <p className="text-sm font-semibold tabular">
                        {fmtHitSample(w.side_hits, w.side_attempts, pct)}
                      </p>
                      <p className="text-[10px] text-muted-foreground">{w.games} in window · {w.pushes} push</p>
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {prop && playerId && profile.data && categories.data && teams.data && (
            <PlayerAnalysis
              profile={profile.data}
              categories={categories.data}
              teams={teams.data}
              initialStat={prop.category.key}
              initialLine={prop.line}
              initialOpponentId={prop.opponent_team_id ?? null}
              lockStat
              lockLine
            />
          )}

          {analyzer.data?.matchup && (
            <section className="grid gap-4 md:grid-cols-2">
              <div className="rounded-xl border border-border p-4">
                <h4 className="mb-2 text-sm font-semibold">Recent form (all opponents)</h4>
                <HitRateSummary analysis={analyzer.data.matchup.recent} />
              </div>
              <div className="rounded-xl border border-border p-4">
                <h4 className="mb-2 text-sm font-semibold">vs {analyzer.data.matchup.opponent.abbreviation}</h4>
                <HitRateSummary analysis={analyzer.data.matchup.head_to_head} />
              </div>
            </section>
          )}

          {playerId && analyzer.data?.opportunity && (
            <PlayerOpportunitySection playerId={playerId} embedded data={analyzer.data.opportunity} />
          )}

          {prop && analyzer.data?.game_log && analyzer.data.game_log.length > 0 && (
            <PropGameLogTable
              rows={analyzer.data.game_log}
              pickSide={prop.pick_side}
              line={prop.line}
              statLabel={prop.category.short_label}
            />
          )}
        </div>
      </div>
    </div>
  );
}
