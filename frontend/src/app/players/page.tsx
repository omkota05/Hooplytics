"use client";

import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";

import { TeamSelect } from "@/components/analysis/team-select";
import { PlayerAvatar } from "@/components/common/player-avatar";
import { Segmented } from "@/components/common/segmented";
import { EmptyState, ErrorState, LoadingRows, Spinner } from "@/components/common/states";
import { TeamLogo } from "@/components/common/team-logo";
import { api } from "@/lib/api";
import { fmtNum } from "@/lib/format";
import { useDebounced, useTeams } from "@/lib/hooks";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 50;
type Sort = "pts" | "reb" | "ast" | "minutes" | "games" | "name";

const COLUMNS: { key: Sort; label: string }[] = [
  { key: "games", label: "GP" },
  { key: "minutes", label: "MIN" },
  { key: "pts", label: "PTS" },
  { key: "reb", label: "REB" },
  { key: "ast", label: "AST" },
];

export default function PlayersPage() {
  const router = useRouter();
  const teams = useTeams();
  const [q, setQ] = useState("");
  const [teamId, setTeamId] = useState<number | null>(null);
  const [status, setStatus] = useState<"active" | "all">("active");
  const [sort, setSort] = useState<Sort>("pts");
  const [page, setPage] = useState(1);
  const query = useDebounced(q.trim(), 250);

  const { data, error, isValidating, mutate } = useSWR(
    ["players", query, teamId, status, sort, page],
    () =>
      api.listPlayers({ q: query || undefined, teamId, activeOnly: status === "active", sort, page, pageSize: PAGE_SIZE }),
    { keepPreviousData: true },
  );

  const reset = <T,>(setter: (v: T) => void) => (v: T) => {
    setter(v);
    setPage(1);
  };
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  const seasonLabel = data?.items[0]?.season ? `${data.items[0].season - 1}-${String(data.items[0].season).slice(2)}` : "";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Players</h1>
        <p className="text-sm text-muted-foreground">
          Every player on a current NBA roster, plus everyone who appeared in a synced game. Averages are for the{" "}
          {seasonLabel || "current"} season.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex h-10 w-full max-w-sm items-center gap-2 rounded-xl border border-input bg-surface px-3 focus-within:border-primary/70">
          <Search className="size-4 text-muted-foreground" />
          <input
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
            placeholder="Filter by name"
            className="w-full bg-transparent text-sm outline-none"
          />
          {isValidating && <Spinner />}
        </div>
        {teams.data && (
          <TeamSelect teams={teams.data} value={teamId} onChange={reset(setTeamId)} allLabel="All teams" />
        )}
        <Segmented
          options={[
            { value: "active", label: "On a roster" },
            { value: "all", label: "Include inactive" },
          ]}
          value={status}
          onChange={reset(setStatus)}
        />
      </div>

      {error && !data ? (
        <ErrorState error={error} onRetry={() => mutate()} />
      ) : !data ? (
        <LoadingRows rows={10} />
      ) : data.items.length === 0 ? (
        <EmptyState title="No players found" description="Try a different name or team." />
      ) : (
        <div className="panel overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm tabular">
              <thead className="bg-surface-2/70 text-[11px] tracking-wide text-muted-foreground uppercase">
                <tr>
                  <th className="px-4 py-3 text-left">
                    <SortButton active={sort === "name"} onClick={() => reset(setSort)("name")}>
                      Player
                    </SortButton>
                  </th>
                  <th className="px-3 py-3 text-left">Team</th>
                  <th className="px-3 py-3 text-left">Pos</th>
                  {COLUMNS.map((c) => (
                    <th key={c.key} className="px-3 py-3 text-right">
                      <SortButton active={sort === c.key} onClick={() => reset(setSort)(c.key)}>
                        {c.label}
                      </SortButton>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr
                    key={row.player.id}
                    onClick={() => router.push(`/players/${row.player.id}`)}
                    className="cursor-pointer border-t border-border/60 transition-colors hover:bg-primary/5"
                  >
                    <td className="px-4 py-2.5">
                      <Link href={`/players/${row.player.id}`} className="flex items-center gap-3">
                        <PlayerAvatar name={row.player.full_name} src={row.player.headshot_url} size={34} />
                        <span className="font-medium">{row.player.full_name}</span>
                      </Link>
                    </td>
                    <td className="px-3 py-2.5">
                      {row.player.team ? (
                        <span className="flex items-center gap-2">
                          <TeamLogo team={row.player.team} size={20} />
                          {row.player.team.abbreviation}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-muted-foreground">{row.player.position ?? "—"}</td>
                    <td className="px-3 py-2.5 text-right">{row.games || "—"}</td>
                    <td className="px-3 py-2.5 text-right text-muted-foreground">{fmtNum(row.minutes)}</td>
                    <td className="px-3 py-2.5 text-right font-semibold">{fmtNum(row.pts)}</td>
                    <td className="px-3 py-2.5 text-right">{fmtNum(row.reb)}</td>
                    <td className="px-3 py-2.5 text-right">{fmtNum(row.ast)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between border-t border-border px-4 py-3 text-sm text-muted-foreground">
            <span>
              {data.total.toLocaleString()} players · page {page} of {pages}
            </span>
            <div className="flex gap-2">
              <PageButton disabled={page <= 1} onClick={() => setPage((p) => p - 1)} label="Previous page">
                <ChevronLeft className="size-4" />
              </PageButton>
              <PageButton disabled={page >= pages} onClick={() => setPage((p) => p + 1)} label="Next page">
                <ChevronRight className="size-4" />
              </PageButton>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function SortButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick} className={cn("uppercase hover:text-foreground", active && "text-electric")}>
      {children}
      {active && " ↓"}
    </button>
  );
}

function PageButton({
  disabled,
  onClick,
  label,
  children,
}: {
  disabled: boolean;
  onClick: () => void;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <button
      disabled={disabled}
      onClick={onClick}
      aria-label={label}
      className="rounded-lg border border-border p-1.5 hover:bg-secondary disabled:opacity-40"
    >
      {children}
    </button>
  );
}
