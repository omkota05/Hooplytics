"use client";

import { ArrowUpRight, Swords, TrendingUp } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";

import { StatBarChart } from "@/components/charts/stat-bar-chart";
import { PlayerAvatar } from "@/components/common/player-avatar";
import { Segmented } from "@/components/common/segmented";
import { EmptyState, ErrorState, Spinner } from "@/components/common/states";
import { TeamLogo } from "@/components/common/team-logo";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { fmtNum } from "@/lib/format";
import type { PlayerSummary, RecentForm, StatAnalysis, StatCategory, Team } from "@/lib/types";

import { HitRateSummary } from "./hit-rate-summary";
import { LineInput } from "./line-input";
import { StatPicker } from "./stat-picker";

type RecentN = "5" | "10" | "20";
type H2HN = "3" | "5" | "10" | "all";

function defaultLine(category: StatCategory | undefined, form: RecentForm | null): number {
  if (!category || !form) return 0.5;
  let total = 0;
  for (const c of category.components) {
    const v = form[c as keyof RecentForm];
    if (typeof v !== "number") return 0.5;
    total += v;
  }
  return Math.max(0.5, Math.floor(total) + 0.5);
}

export function MatchupComparison({
  player,
  recentForm,
  opponent,
  categories,
}: {
  player: PlayerSummary;
  recentForm: RecentForm | null;
  opponent: Team;
  categories: StatCategory[];
}) {
  const byKey = useMemo(() => new Map(categories.map((c) => [c.key, c])), [categories]);
  const [stat, setStat] = useState("pts");
  const [line, setLine] = useState(() => defaultLine(byKey.get("pts"), recentForm));
  const [recentN, setRecentN] = useState<RecentN>("10");
  const [h2hN, setH2hN] = useState<H2HN>("all");

  const { data, error, isValidating, mutate } = useSWR(
    ["comparison", player.id, opponent.id, stat, line, recentN, h2hN],
    () =>
      api.matchupComparison(player.id, {
        opponentId: opponent.id,
        stat,
        line,
        recentN: Number(recentN),
        h2hN: h2hN === "all" ? null : Number(h2hN),
      }),
    { keepPreviousData: true, revalidateOnFocus: false },
  );

  const changeStat = (key: string) => {
    setStat(key);
    setLine(defaultLine(byKey.get(key), recentForm));
  };
  const statLabel = byKey.get(stat)?.label ?? stat;

  return (
    <section className="panel overflow-hidden">
      <div className="flex flex-wrap items-center gap-4 border-b border-border px-5 py-4">
        <PlayerAvatar name={player.full_name} src={player.headshot_url} size={48} />
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-semibold">{player.full_name}</h2>
          <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
            Recent form vs. history against <TeamLogo team={opponent} size={16} /> {opponent.display_name}
          </p>
        </div>
        {isValidating && <Spinner />}
        <Link
          href={`/players/${player.id}?opponent=${opponent.id}&stat=${stat}`}
          className="flex items-center gap-1 rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-secondary"
        >
          Full profile <ArrowUpRight className="size-3.5" />
        </Link>
      </div>

      <div className="flex flex-wrap items-end gap-4 border-b border-border px-5 py-4">
        <div className="w-full">
          <StatPicker categories={categories} value={stat} onChange={changeStat} />
        </div>
        <label className="flex flex-col gap-1">
          <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Line</span>
          <LineInput value={line} onChange={setLine} />
        </label>
        <div className="flex flex-col gap-1">
          <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Recent window</span>
          <Segmented
            options={[
              { value: "5", label: "L5" },
              { value: "10", label: "L10" },
              { value: "20", label: "L20" },
            ]}
            value={recentN}
            onChange={setRecentN}
          />
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
            vs {opponent.abbreviation}
          </span>
          <Segmented
            options={[
              { value: "3", label: "Last 3" },
              { value: "5", label: "Last 5" },
              { value: "10", label: "Last 10" },
              { value: "all", label: "All" },
            ]}
            value={h2hN}
            onChange={setH2hN}
          />
        </div>
      </div>

      {error && !data ? (
        <div className="p-5">
          <ErrorState error={error} onRetry={() => mutate()} />
        </div>
      ) : !data ? (
        <div className="grid gap-4 p-5 lg:grid-cols-2">
          <Skeleton className="h-96 rounded-xl bg-secondary/40" />
          <Skeleton className="h-96 rounded-xl bg-secondary/40" />
        </div>
      ) : (
        <>
          <DeltaBanner recent={data.recent} h2h={data.head_to_head} opponent={opponent} />
          <div className="grid divide-y divide-border lg:grid-cols-2 lg:divide-x lg:divide-y-0">
            <ComparisonColumn
              icon={<TrendingUp className="size-4 text-electric" />}
              title={`Last ${recentN} games · all opponents`}
              analysis={data.recent}
              statLabel={statLabel}
            />
            <ComparisonColumn
              icon={<Swords className="size-4 text-violet" />}
              title={`${h2hN === "all" ? "All" : `Last ${h2hN}`} games vs ${opponent.abbreviation}`}
              analysis={data.head_to_head}
              statLabel={statLabel}
              emptyText={`${player.full_name} has no synced games against the ${opponent.display_name}.`}
            />
          </div>
        </>
      )}
    </section>
  );
}

function DeltaBanner({ recent, h2h, opponent }: { recent: StatAnalysis; h2h: StatAnalysis; opponent: Team }) {
  const r = recent.distribution.mean;
  const h = h2h.distribution.mean;
  if (r === null || h === null) return null;
  const diff = h - r;
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-1 border-b border-border bg-surface/50 px-5 py-3 text-sm">
      <span>
        Recent avg <b className="tabular">{fmtNum(r)}</b>
      </span>
      <span>
        vs {opponent.abbreviation} avg <b className="tabular">{fmtNum(h)}</b>
      </span>
      <span className={diff >= 0 ? "text-over" : "text-under"}>
        {diff >= 0 ? "+" : ""}
        {fmtNum(diff)} against this opponent
      </span>
      {h2h.small_sample && <span className="text-push">Small head-to-head sample ({h2h.distribution.count})</span>}
    </div>
  );
}

function ComparisonColumn({
  icon,
  title,
  analysis,
  statLabel,
  emptyText,
}: {
  icon: React.ReactNode;
  title: string;
  analysis: StatAnalysis;
  statLabel: string;
  emptyText?: string;
}) {
  return (
    <div className="min-w-0 space-y-4 p-5">
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        {icon}
        {title}
      </h3>
      {analysis.games.length === 0 ? (
        <EmptyState title="No games" description={emptyText} className="h-64" />
      ) : (
        <>
          <StatBarChart games={analysis.games} line={analysis.line_result.line} statLabel={statLabel} height={260} dense />
          <HitRateSummary analysis={analysis} />
        </>
      )}
    </div>
  );
}
