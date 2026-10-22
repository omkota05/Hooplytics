"use client";

import { FlaskConical, Info } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";

import { LineInput } from "@/components/analysis/line-input";
import { StatPicker } from "@/components/analysis/stat-picker";
import { PlayerAvatar } from "@/components/common/player-avatar";
import { Segmented } from "@/components/common/segmented";
import { EmptyState, ErrorState, LoadingRows, Spinner } from "@/components/common/states";
import { TeamLogo } from "@/components/common/team-logo";
import { api } from "@/lib/api";
import { fmtDateTime, fmtNum, fmtPct } from "@/lib/format";
import { useCategories } from "@/lib/hooks";
import type { TrendRow } from "@/lib/types";
import { cn } from "@/lib/utils";

type Sort = "over_pct" | "under_pct" | "mean" | "consistency";

export default function PicksPage() {
  const categories = useCategories();
  const [stat, setStat] = useState("pts");
  const [line, setLine] = useState(19.5);
  const [lastN, setLastN] = useState<"5" | "10" | "20">("10");
  const [days, setDays] = useState<"1" | "2" | "3">("1");
  const [sort, setSort] = useState<Sort>("over_pct");

  const minGames = Math.min(5, Number(lastN));
  const { data, error, isValidating, mutate } = useSWR(
    ["trends", stat, line, lastN, days, sort],
    () => api.trends({ stat, line, lastN: Number(lastN), minGames, days: Number(days), sort }),
    { keepPreviousData: true },
  );

  return (
    <div className="space-y-6">
      <div className="panel relative overflow-hidden p-5">
        <div className="pointer-events-none absolute -top-16 right-0 h-48 w-48 rounded-full bg-violet/25 blur-3xl" />
        <div className="relative flex gap-4">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-violet/20">
            <FlaskConical className="size-5 text-violet" />
          </span>
          <div>
            <h1 className="text-xl font-bold tracking-tight">
              Picks <span className="ml-1 rounded-md bg-violet/20 px-1.5 py-0.5 align-middle text-xs text-violet">ML coming later</span>
            </h1>
            <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
              Model-driven projections and over/under probabilities will live here once an XGBoost model is trained
              and backtested. Until then, this is a <b className="text-foreground">historical trend explorer</b>: for
              every player whose team plays soon, how often their recent games cleared the line you choose. It
              describes the past; it does not predict outcomes.
            </p>
          </div>
        </div>
      </div>

      <div className="panel space-y-4 p-5">
        {categories.data && <StatPicker categories={categories.data} value={stat} onChange={setStat} />}
        <div className="flex flex-wrap items-end gap-4">
          <label className="flex flex-col gap-1">
            <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Line</span>
            <LineInput value={line} onChange={setLine} />
          </label>
          <Field label="Sample">
            <Segmented
              options={[
                { value: "5", label: "L5" },
                { value: "10", label: "L10" },
                { value: "20", label: "L20" },
              ]}
              value={lastN}
              onChange={setLastN}
            />
          </Field>
          <Field label="Games within">
            <Segmented
              options={[
                { value: "1", label: "24 hours" },
                { value: "2", label: "2 days" },
                { value: "3", label: "3 days" },
              ]}
              value={days}
              onChange={setDays}
            />
          </Field>
          <Field label="Sort by">
            <Segmented
              options={[
                { value: "over_pct", label: "Over %" },
                { value: "under_pct", label: "Under %" },
                { value: "mean", label: "Average" },
                { value: "consistency", label: "Consistency" },
              ]}
              value={sort}
              onChange={setSort}
            />
          </Field>
          {isValidating && <Spinner className="mb-3" />}
        </div>
      </div>

      {error && !data ? (
        <ErrorState error={error} onRetry={() => mutate()} />
      ) : !data ? (
        <LoadingRows rows={8} />
      ) : data.rows.length === 0 ? (
        <EmptyState
          title="No players to show"
          description="No scheduled games in this range, or players lack enough synced games. Try a wider range."
        />
      ) : (
        <div className="panel overflow-hidden">
          <p className="flex items-center gap-2 border-b border-border px-4 py-2.5 text-xs text-muted-foreground">
            <Info className="size-3.5" /> {data.note} Players need at least {data.min_games} played games.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm tabular">
              <thead className="bg-surface-2/70 text-[11px] tracking-wide text-muted-foreground uppercase">
                <tr>
                  <th className="px-4 py-3 text-left">Player</th>
                  <th className="px-3 py-3 text-left">Next game</th>
                  <th className="px-3 py-3 text-left">Last {data.last_n}</th>
                  <th className="px-3 py-3 text-right">Avg</th>
                  <th className="px-3 py-3 text-right">Median</th>
                  <th className="px-3 py-3 text-right">Std</th>
                  <th className="px-3 py-3 text-right">Over {data.line}</th>
                  <th className="px-3 py-3 text-right">Under</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <TrendTableRow key={row.player.id} row={row} line={data.line} stat={stat} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{label}</span>
      {children}
    </div>
  );
}

function TrendTableRow({ row, line, stat }: { row: TrendRow; line: number; stat: string }) {
  const lr = row.line_result;
  const max = Math.max(line, ...row.recent_values, 1);
  return (
    <tr className="border-t border-border/60 hover:bg-primary/5">
      <td className="px-4 py-2.5">
        <Link
          href={`/players/${row.player.id}?stat=${stat}${row.opponent ? `&opponent=${row.opponent.id}` : ""}`}
          className="flex items-center gap-3 hover:text-electric"
        >
          <PlayerAvatar name={row.player.full_name} src={row.player.headshot_url} size={32} />
          <span>
            <span className="block font-medium">{row.player.full_name}</span>
            <span className="text-xs text-muted-foreground">{row.player.team?.abbreviation}</span>
          </span>
        </Link>
      </td>
      <td className="px-3 py-2.5 text-xs">
        {row.opponent && (
          <span className="flex items-center gap-1.5">
            vs <TeamLogo team={row.opponent} size={18} /> {row.opponent.abbreviation}
          </span>
        )}
        {row.game_start && <span className="text-muted-foreground">{fmtDateTime(row.game_start)}</span>}
      </td>
      <td className="px-3 py-2.5">
        <div className="flex h-8 items-end gap-0.5" aria-label="Recent values, oldest to newest">
          {row.recent_values.map((v, i) => (
            <span
              key={i}
              title={String(v)}
              className={cn("w-1.5 rounded-sm", v > line ? "bg-over" : v < line ? "bg-under" : "bg-push")}
              style={{ height: `${Math.max(8, (v / max) * 100)}%` }}
            />
          ))}
        </div>
      </td>
      <td className="px-3 py-2.5 text-right font-semibold">{fmtNum(row.distribution.mean)}</td>
      <td className="px-3 py-2.5 text-right">{fmtNum(row.distribution.median)}</td>
      <td className="px-3 py-2.5 text-right text-muted-foreground">{fmtNum(row.distribution.std_dev)}</td>
      <td className="px-3 py-2.5 text-right">
        <span className="font-semibold text-over">{fmtPct(lr.over_pct)}</span>
        <span className="ml-1 text-xs text-muted-foreground">
          {lr.over}/{lr.total}
        </span>
      </td>
      <td className="px-3 py-2.5 text-right">
        <span className="font-semibold text-under">{fmtPct(lr.under_pct)}</span>
        <span className="ml-1 text-xs text-muted-foreground">
          {lr.under}/{lr.total}
        </span>
        {lr.push > 0 && <span className="ml-1 text-xs text-push">({lr.push}P)</span>}
      </td>
    </tr>
  );
}
