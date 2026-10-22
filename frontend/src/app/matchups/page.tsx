"use client";

import { useState } from "react";
import useSWR from "swr";

import { Segmented } from "@/components/common/segmented";
import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { GameCard } from "@/components/games/game-card";
import { api } from "@/lib/api";
import { fmtDayHeading } from "@/lib/format";
import type { Game } from "@/lib/types";

type Days = "3" | "7" | "14";

export default function MatchupsPage() {
  const [days, setDays] = useState<Days>("7");
  const { data, error, mutate } = useSWR(["upcoming", days], () => api.upcomingGames(Number(days)), {
    keepPreviousData: true,
    refreshInterval: 60_000,
  });

  const groups = new Map<string, Game[]>();
  for (const g of data ?? []) groups.set(g.game_date, [...(groups.get(g.game_date) ?? []), g]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Matchups</h1>
          <p className="text-sm text-muted-foreground">
            Scheduled NBA games. Open one to compare each player&apos;s recent form with their history against that
            opponent.
          </p>
        </div>
        <Segmented
          options={[
            { value: "3", label: "3 days" },
            { value: "7", label: "7 days" },
            { value: "14", label: "14 days" },
          ]}
          value={days}
          onChange={setDays}
          ariaLabel="Schedule range"
        />
      </div>

      {error && !data ? (
        <ErrorState error={error} onRetry={() => mutate()} />
      ) : !data ? (
        <LoadingRows rows={6} />
      ) : data.length === 0 ? (
        <EmptyState
          title="No scheduled games in this range"
          description="During the offseason or the All-Star break there may be no games. The schedule updates on every sync."
        />
      ) : (
        <div className="space-y-8">
          {[...groups.entries()].map(([date, games]) => (
            <section key={date}>
              <h2 className="mb-3 flex items-baseline gap-2 font-semibold">
                {fmtDayHeading(date)}
                <span className="text-sm font-normal text-muted-foreground">{games.length} games</span>
              </h2>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {games.map((g) => (
                  <GameCard key={g.id} game={g} />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
