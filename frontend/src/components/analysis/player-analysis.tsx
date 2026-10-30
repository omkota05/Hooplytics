"use client";

import { Swords } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import useSWR from "swr";

import { StatBarChart } from "@/components/charts/stat-bar-chart";
import { Segmented } from "@/components/common/segmented";
import { EmptyState, ErrorState, Spinner } from "@/components/common/states";
import { TeamLogo } from "@/components/common/team-logo";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type AnalysisQuery } from "@/lib/api";
import { fmtNum, fmtShortDate } from "@/lib/format";
import type { PlayerProfile, SeasonScope, StatCategory, Team } from "@/lib/types";
import { cn } from "@/lib/utils";

import { HitRateSummary } from "./hit-rate-summary";
import { LineInput } from "./line-input";
import { StatPicker } from "./stat-picker";
import { TeamSelect } from "./team-select";

type GeneralWindow = "l5" | "l10" | "l15" | "l20" | "l30" | "season" | "custom";
type H2HWindow = "h3" | "h5" | "h10" | "hall";

const GENERAL_WINDOWS: { value: GeneralWindow; label: string }[] = [
  { value: "l5", label: "L5" },
  { value: "l10", label: "L10" },
  { value: "l15", label: "L15" },
  { value: "l20", label: "L20" },
  { value: "l30", label: "L30" },
  { value: "season", label: "Season" },
  { value: "custom", label: "Custom" },
];

const H2H_WINDOWS: { value: H2HWindow; label: string }[] = [
  { value: "h3", label: "Last 3" },
  { value: "h5", label: "Last 5" },
  { value: "h10", label: "Last 10" },
  { value: "hall", label: "All matchups" },
];

const SCOPES: { value: SeasonScope; label: string }[] = [
  { value: "all", label: "All games" },
  { value: "regular", label: "Regular season" },
  { value: "postseason", label: "Playoffs" },
];

export function suggestedLine(category: StatCategory | undefined, profile: PlayerProfile): number {
  const avg = profile.season_averages;
  if (!category || !avg) return 0.5;
  let total = 0;
  for (const component of category.components) {
    const value = avg[component as keyof typeof avg];
    if (typeof value !== "number") return 0.5;
    total += value;
  }
  return Math.max(0.5, Math.floor(total) + 0.5);
}

function isoDaysBefore(iso: string, days: number) {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

export function PlayerAnalysis({
  profile,
  categories,
  teams,
  initialStat = "pts",
  initialOpponentId = null,
  initialLine,
  lockStat = false,
  lockLine = false,
}: {
  profile: PlayerProfile;
  categories: StatCategory[];
  teams: Team[];
  initialStat?: string;
  initialOpponentId?: number | null;
  initialLine?: number;
  lockStat?: boolean;
  lockLine?: boolean;
}) {
  const playerId = profile.player.id;
  const categoryByKey = useMemo(() => new Map(categories.map((c) => [c.key, c])), [categories]);
  const [stat, setStat] = useState(categoryByKey.has(initialStat) ? initialStat : "pts");
  const [line, setLine] = useState(
    () => initialLine ?? suggestedLine(categoryByKey.get(stat), profile),
  );
  const [opponentId, setOpponentId] = useState<number | null>(initialOpponentId);
  const [generalWindow, setGeneralWindow] = useState<GeneralWindow>("l10");
  const [h2hWindow, setH2hWindow] = useState<H2HWindow>("h5");
  const [scope, setScope] = useState<SeasonScope>("all");
  const seasons = profile.available_seasons;
  const [season, setSeason] = useState<number | undefined>(seasons[0]);
  const lastDate = profile.last_game_date ?? new Date().toISOString().slice(0, 10);
  const [range, setRange] = useState({ start: isoDaysBefore(lastDate, 30), end: lastDate });

  const category = categoryByKey.get(stat);

  const changeStat = useCallback(
    (key: string) => {
      setStat(key);
      setLine(suggestedLine(categoryByKey.get(key), profile));
    },
    [categoryByKey, profile],
  );

  const query: AnalysisQuery = useMemo(() => {
    const base = { stat, line, opponentId, seasonScope: scope };
    if (opponentId !== null) {
      const n = { h3: 3, h5: 5, h10: 10, hall: undefined }[h2hWindow];
      return n ? { ...base, window: "last_n", n } : { ...base, window: "all" };
    }
    switch (generalWindow) {
      case "season":
        return { ...base, window: "season", season };
      case "custom":
        return { ...base, window: "date_range", startDate: range.start, endDate: range.end };
      default:
        return { ...base, window: "last_n", n: Number(generalWindow.slice(1)) };
    }
  }, [stat, line, opponentId, scope, h2hWindow, generalWindow, season, range]);

  const rangeInvalid = generalWindow === "custom" && opponentId === null && range.start > range.end;
  const { data, error, isLoading, isValidating, mutate } = useSWR(
    rangeInvalid ? null : ["analysis", playerId, JSON.stringify(query)],
    () => api.statAnalysis(playerId, query),
    { keepPreviousData: true, revalidateOnFocus: false },
  );

  const opponent = teams.find((t) => t.id === opponentId) ?? null;
  const statLabel = category?.label ?? stat;

  return (
    <section className="panel overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border px-5 py-4">
        <div>
          <h2 className="text-lg font-semibold">Performance vs. line</h2>
          <p className="text-sm text-muted-foreground">
            {opponent ? (
              <span className="inline-flex items-center gap-1.5">
                <Swords className="size-3.5 text-violet" /> Head-to-head vs {opponent.display_name}
                {" · all synced seasons"}
              </span>
            ) : (
              "Every bar is a real game from the synced box scores."
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {isValidating && <Spinner />}
          <Segmented options={SCOPES} value={scope} onChange={setScope} size="sm" ariaLabel="Season type" />
        </div>
      </div>

      <div className="space-y-4 border-b border-border px-5 py-4">
        {!lockStat && <StatPicker categories={categories} value={stat} onChange={changeStat} />}
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
              Line
            </span>
            {lockLine ? (
              <span className="flex h-10 items-center rounded-xl border border-border bg-secondary/30 px-3 text-sm font-semibold tabular">
                {line}
              </span>
            ) : (
              <LineInput value={line} onChange={setLine} />
            )}
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
              Opponent
            </span>
            <TeamSelect
              teams={teams}
              value={opponentId}
              onChange={setOpponentId}
              excludeTeamId={profile.player.team?.id}
            />
          </label>
          <div className="flex flex-col gap-1">
            <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
              {opponent ? "Matchup window" : "Game window"}
            </span>
            {opponent ? (
              <Segmented options={H2H_WINDOWS} value={h2hWindow} onChange={setH2hWindow} ariaLabel="Head-to-head window" />
            ) : (
              <Segmented options={GENERAL_WINDOWS} value={generalWindow} onChange={setGeneralWindow} ariaLabel="Game window" />
            )}
          </div>
          {!opponent && generalWindow === "season" && seasons.length > 0 && (
            <Segmented
              options={seasons.map((s) => ({ value: String(s), label: `${s - 1}-${String(s).slice(2)}` }))}
              value={String(season)}
              onChange={(v) => setSeason(Number(v))}
              ariaLabel="Season"
            />
          )}
          {!opponent && generalWindow === "custom" && (
            <div className="flex items-center gap-2">
              <input
                type="date"
                value={range.start}
                max={range.end}
                onChange={(e) => e.target.value && setRange((r) => ({ ...r, start: e.target.value }))}
                className="h-10 rounded-xl border border-border bg-surface px-3 text-sm"
                aria-label="Start date"
              />
              <span className="text-muted-foreground">to</span>
              <input
                type="date"
                value={range.end}
                min={range.start}
                onChange={(e) => e.target.value && setRange((r) => ({ ...r, end: e.target.value }))}
                className="h-10 rounded-xl border border-border bg-surface px-3 text-sm"
                aria-label="End date"
              />
              {rangeInvalid && <span className="text-xs text-under">Start must be before end</span>}
            </div>
          )}
        </div>
      </div>

      <div className="grid gap-0 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0 px-3 py-4 sm:px-5">
          {error && !data ? (
            <ErrorState error={error} title="Could not load game history" onRetry={() => mutate()} />
          ) : !data ? (
            <Skeleton className="h-[340px] w-full rounded-xl bg-secondary/50" />
          ) : data.games.length === 0 ? (
            <EmptyState
              className="h-[340px]"
              title={opponent ? `No games vs ${opponent.abbreviation} in synced history` : "No games in this window"}
              description={
                opponent
                  ? "Head-to-head history covers the seasons synced so far. Backfill more seasons to extend it."
                  : "Try a wider window, or check that this player's box scores have been synced."
              }
            />
          ) : (
            <div className={cn("transition-opacity", isLoading && "opacity-60")}>
              <div className="mb-2 flex items-center justify-between px-1 text-xs text-muted-foreground">
                <span>
                  {data.category.label} · {data.games.length} game{data.games.length === 1 ? "" : "s"}
                  {opponent && ` vs ${opponent.abbreviation}`}
                </span>
                <span className="flex items-center gap-3">
                  <Legend color="bg-over" label="Over" />
                  <Legend color="bg-under" label="Under" />
                  <Legend color="bg-push" label="Push" />
                </span>
              </div>
              <StatBarChart games={data.games} line={data.line_result.line} statLabel={statLabel} />
            </div>
          )}
        </div>
        <aside className="border-t border-border px-5 py-4 xl:border-t-0 xl:border-l">
          {data ? (
            <HitRateSummary analysis={data} />
          ) : error ? null : (
            <div className="space-y-2">
              {Array.from({ length: 4 }, (_, i) => (
                <Skeleton key={i} className="h-16 w-full rounded-xl bg-secondary/50" />
              ))}
            </div>
          )}
        </aside>
      </div>

      {data && data.games.length > 0 && (
        <div className="border-t border-border px-5 py-4">
          <h3 className="mb-3 text-sm font-semibold">Games analyzed</h3>
          <div className="max-h-80 overflow-auto rounded-xl border border-border">
            <table className="w-full text-sm tabular">
              <thead className="sticky top-0 bg-surface-2 text-[11px] tracking-wide text-muted-foreground uppercase">
                <tr>
                  <th className="px-3 py-2 text-left">Date</th>
                  <th className="px-3 py-2 text-left">Season</th>
                  <th className="px-3 py-2 text-left">Opponent</th>
                  <th className="px-3 py-2 text-left">Result</th>
                  <th className="px-3 py-2 text-right">Min</th>
                  <th className="px-3 py-2 text-right">{data.category.short_label}</th>
                  <th className="px-3 py-2 text-right">vs {data.line_result.line}</th>
                </tr>
              </thead>
              <tbody>
                {[...data.games].reverse().map((g) => (
                  <tr key={g.game_id} className="border-t border-border/60 hover:bg-secondary/30">
                    <td className="px-3 py-2">{fmtShortDate(g.game_date)}</td>
                    <td className="px-3 py-2 text-muted-foreground">
                      {g.season_label}
                      {g.season_type !== 2 && <span className="ml-1 text-violet">PO</span>}
                    </td>
                    <td className="px-3 py-2">
                      <span className="flex items-center gap-2">
                        <span className="w-4 text-muted-foreground">{g.is_home ? "vs" : "@"}</span>
                        <TeamLogo team={g.opponent} size={18} />
                        {g.opponent.abbreviation}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      {g.result && (
                        <span className={g.result === "W" ? "text-over" : "text-under"}>
                          {g.result} {g.team_score}–{g.opponent_score}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right text-muted-foreground">{fmtNum(g.minutes, 0)}</td>
                    <td className="px-3 py-2 text-right font-semibold">{g.value}</td>
                    <td className="px-3 py-2 text-right">
                      <OutcomePill outcome={g.outcome} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className={cn("size-2 rounded-sm", color)} />
      {label}
    </span>
  );
}

export function OutcomePill({ outcome }: { outcome: "over" | "under" | "push" }) {
  const styles = {
    over: "bg-over/15 text-over",
    under: "bg-under/15 text-under",
    push: "bg-push/15 text-push",
  }[outcome];
  return <span className={cn("rounded-md px-2 py-0.5 text-xs font-semibold uppercase", styles)}>{outcome}</span>;
}
